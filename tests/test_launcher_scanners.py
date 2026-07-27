import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from isolator.app import EsportsIsolatorPro

# (provider, scanner, roots method, cache attr, last-scan attr)
PROVIDERS = [
    ("gog", "_scan_gog_games", "_gog_library_roots", "_gog_games_cache", "_last_gog_scan"),
    ("ea", "_scan_ea_games", "_ea_library_roots", "_ea_games_cache", "_last_ea_scan"),
    ("battlenet", "_scan_battlenet_games", "_battlenet_library_roots", "_battlenet_games_cache", "_last_battlenet_scan"),
    ("ubisoft", "_scan_ubisoft_games", "_ubisoft_library_roots", "_ubisoft_games_cache", "_last_ubisoft_scan"),
    ("xbox", "_scan_xbox_games", "_xbox_library_roots", "_xbox_games_cache", "_last_xbox_scan"),
]


def _make_isolator():
    return EsportsIsolatorPro(
        config_path="__no_local_config__.json",
        scan_game_libraries=False,
    )


class _FakeRegistryKey:
    def __init__(self, subkeys=None, values=None):
        self.subkeys = dict(subkeys or {})
        self.values = dict(values or {})

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _fake_winreg(tree):
    """Patchers for winreg.OpenKey/EnumKey/QueryValueEx over a dict tree.

    tree maps a registry path to {subkey_name: {value_name: value}}.
    """

    def open_key(root_or_key, path):
        if isinstance(root_or_key, _FakeRegistryKey):
            if path not in root_or_key.subkeys:
                raise OSError(2, "subkey not found")
            return _FakeRegistryKey(values=root_or_key.subkeys[path])
        if path not in tree:
            raise OSError(2, "key not found")
        return _FakeRegistryKey(subkeys=tree[path])

    def enum_key(key, index):
        names = list(key.subkeys)
        if index >= len(names):
            raise OSError(22, "no more data")
        return names[index]

    def query_value(key, value_name):
        if value_name not in key.values:
            raise OSError(2, "value not found")
        return key.values[value_name], 1

    return (
        patch("isolator.discovery.winreg.OpenKey", side_effect=open_key),
        patch("isolator.discovery.winreg.EnumKey", side_effect=enum_key),
        patch("isolator.discovery.winreg.QueryValueEx", side_effect=query_value),
    )


class LauncherScannerTests(unittest.TestCase):
    def test_scanner_collects_game_exes_and_filters_redistributables(self):
        for provider, scanner, roots_method, cache_attr, _last_attr in PROVIDERS:
            with self.subTest(provider=provider):
                isolator = _make_isolator()
                with tempfile.TemporaryDirectory() as tmpdir:
                    game_dir = os.path.join(tmpdir, "Some Game")
                    redist_dir = os.path.join(game_dir, "_CommonRedist")
                    os.makedirs(redist_dir)
                    for path in (
                        os.path.join(game_dir, "somegame.exe"),
                        os.path.join(game_dir, "unins000.exe"),
                        os.path.join(redist_dir, "vcredist_x64.exe"),
                    ):
                        with open(path, "w", encoding="utf-8") as handle:
                            handle.write("")
                    setattr(isolator, roots_method, lambda tmpdir=tmpdir: [tmpdir])

                    getattr(isolator, scanner)(force=True)

                self.assertEqual({"somegame.exe"}, getattr(isolator, cache_attr))
                with isolator._state_lock:
                    issues = list(isolator._discovery_issues)
                self.assertEqual([], issues)

    def test_absent_launcher_records_install_not_found_without_walking(self):
        for provider, scanner, roots_method, cache_attr, _last_attr in PROVIDERS:
            with self.subTest(provider=provider):
                isolator = _make_isolator()
                setattr(isolator, roots_method, lambda: [])
                isolator._scan_for_game_exes = MagicMock()

                getattr(isolator, scanner)(force=True)

                self.assertEqual(set(), getattr(isolator, cache_attr))
                isolator._scan_for_game_exes.assert_not_called()
                with isolator._state_lock:
                    codes = [issue["code"] for issue in isolator._discovery_issues]
                self.assertEqual([f"{provider}_install_not_found"], codes)

    def test_budget_overrun_records_provider_issue(self):
        for provider, scanner, roots_method, _cache_attr, _last_attr in PROVIDERS:
            with self.subTest(provider=provider):
                isolator = _make_isolator()
                with tempfile.TemporaryDirectory() as tmpdir:
                    setattr(isolator, roots_method, lambda tmpdir=tmpdir: [tmpdir])
                    isolator._scan_for_game_exes = lambda *args, **kwargs: False

                    getattr(isolator, scanner)(force=True)

                with isolator._state_lock:
                    codes = [issue["code"] for issue in isolator._discovery_issues]
                self.assertIn(f"{provider}_scan_budget_exceeded", codes)

    def test_scan_is_throttled_within_300_seconds(self):
        for provider, scanner, roots_method, _cache_attr, last_attr in PROVIDERS:
            with self.subTest(provider=provider):
                isolator = _make_isolator()
                setattr(isolator, last_attr, time.monotonic())
                roots = MagicMock(return_value=[])
                setattr(isolator, roots_method, roots)

                getattr(isolator, scanner)(force=False)
                roots.assert_not_called()

                getattr(isolator, scanner)(force=True)
                roots.assert_called_once()

    def test_rescan_clears_previous_provider_issues(self):
        isolator = _make_isolator()
        isolator._gog_library_roots = lambda: []
        isolator._scan_gog_games(force=True)
        with isolator._state_lock:
            self.assertEqual(
                ["gog_install_not_found"],
                [issue["code"] for issue in isolator._discovery_issues],
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            isolator._gog_library_roots = lambda: [tmpdir]
            isolator._scan_gog_games(force=True)

        with isolator._state_lock:
            issues = list(isolator._discovery_issues)
        self.assertEqual([], issues)


class RegistryRootDiscoveryTests(unittest.TestCase):
    def test_enum_registry_install_dirs_collects_and_dedupes_paths(self):
        isolator = _make_isolator()
        tree = {
            r"SOFTWARE\WOW6432Node\GOG.com\Games": {
                "1207658930": {"path": r"D:\GOG Games\Gwent  "},
                "1207658931": {"path": r"D:\GOG Games\Gwent"},
                "1207658932": {"path": r"E:\GOG\Cyberpunk"},
                "broken": {"other_value": "x"},
            },
        }
        patches = _fake_winreg(tree)
        with patches[0], patches[1], patches[2]:
            roots = isolator._enum_registry_install_dirs(
                r"SOFTWARE\WOW6432Node\GOG.com\Games", "path"
            )

        self.assertEqual([r"D:\GOG Games\Gwent", r"E:\GOG\Cyberpunk"], roots)

    def test_enum_registry_install_dirs_missing_hive_is_empty(self):
        isolator = _make_isolator()
        patches = _fake_winreg({})
        with patches[0], patches[1], patches[2]:
            roots = isolator._enum_registry_install_dirs(
                r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs", "InstallDir"
            )

        self.assertEqual([], roots)

    def test_provider_roots_query_the_documented_registry_locations(self):
        expectations = [
            ("_gog_library_roots", r"SOFTWARE\WOW6432Node\GOG.com\Games", "path"),
            ("_ea_library_roots", r"SOFTWARE\WOW6432Node\Origin Games", "Install Dir"),
            ("_battlenet_library_roots", r"SOFTWARE\WOW6432Node\Blizzard Entertainment", "InstallPath"),
            ("_ubisoft_library_roots", r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs", "InstallDir"),
        ]
        for roots_method, key_path, value_name in expectations:
            with self.subTest(roots_method=roots_method):
                isolator = _make_isolator()
                isolator._enum_registry_install_dirs = MagicMock(return_value=[r"C:\Games\One"])
                with patch("isolator.discovery.os.path.exists", return_value=False):
                    roots = getattr(isolator, roots_method)()

                isolator._enum_registry_install_dirs.assert_any_call(key_path, value_name)
                self.assertIn(r"C:\Games\One", roots)

    def test_gog_roots_merge_the_non_wow64_fallback(self):
        isolator = _make_isolator()
        calls = []

        def fake_enum(key_path, value_name):
            calls.append(key_path)
            if key_path == r"SOFTWARE\WOW6432Node\GOG.com\Games":
                return [r"D:\GOG\One", r"D:\GOG\Both"]
            return [r"D:\GOG\Both", r"D:\GOG\Two"]

        isolator._enum_registry_install_dirs = fake_enum
        roots = isolator._gog_library_roots()

        self.assertEqual([r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"], calls)
        self.assertEqual([r"D:\GOG\One", r"D:\GOG\Both", r"D:\GOG\Two"], roots)

    def test_ea_roots_add_default_directories_when_present(self):
        isolator = _make_isolator()
        isolator._enum_registry_install_dirs = MagicMock(return_value=[])
        with patch(
            "isolator.discovery.os.path.exists",
            side_effect=lambda path: path == r"C:\Program Files (x86)\Origin Games",
        ):
            roots = isolator._ea_library_roots()

        self.assertEqual([r"C:\Program Files (x86)\Origin Games"], roots)

    def test_xbox_roots_probe_only_present_drives(self):
        isolator = _make_isolator()
        probed = []

        def fake_exists(path):
            probed.append(path)
            return path == r"D:\XboxGames"

        # Bit 2 (C:) and bit 3 (D:) present.
        with patch("isolator.discovery.kernel32.GetLogicalDrives", return_value=0b1100), patch(
            "isolator.discovery.os.path.exists", side_effect=fake_exists
        ):
            roots = isolator._xbox_library_roots()

        self.assertEqual([r"C:\XboxGames", r"D:\XboxGames"], probed)
        self.assertEqual([r"D:\XboxGames"], roots)


class LibraryScanWiringTests(unittest.TestCase):
    def _disable_all_providers(self, isolator):
        isolator.auto_detect_steam = False
        isolator.auto_detect_epic = False
        isolator.auto_detect_gog = False
        isolator.auto_detect_ea = False
        isolator.auto_detect_battlenet = False
        isolator.auto_detect_ubisoft = False
        isolator.auto_detect_xbox = False

    def test_run_library_scans_honors_each_provider_flag(self):
        flag_by_provider = {
            "steam": "auto_detect_steam",
            "epic": "auto_detect_epic",
            "gog": "auto_detect_gog",
            "ea": "auto_detect_ea",
            "battlenet": "auto_detect_battlenet",
            "ubisoft": "auto_detect_ubisoft",
            "xbox": "auto_detect_xbox",
        }
        scanner_by_provider = {
            "steam": "_scan_steam_games",
            "epic": "_scan_epic_games",
            "gog": "_scan_gog_games",
            "ea": "_scan_ea_games",
            "battlenet": "_scan_battlenet_games",
            "ubisoft": "_scan_ubisoft_games",
            "xbox": "_scan_xbox_games",
        }
        for enabled_provider, flag in flag_by_provider.items():
            with self.subTest(provider=enabled_provider):
                isolator = _make_isolator()
                self._disable_all_providers(isolator)
                setattr(isolator, flag, True)
                mocks = {}
                for provider, scanner in scanner_by_provider.items():
                    mocks[provider] = MagicMock()
                    setattr(isolator, scanner, mocks[provider])

                isolator._run_library_scans()

                for provider, scanner_mock in mocks.items():
                    if provider == enabled_provider:
                        # The first scan forces past the throttle window.
                        scanner_mock.assert_called_once_with(force=True)
                    else:
                        scanner_mock.assert_not_called()

    def test_is_game_name_checks_enabled_caches_only(self):
        cache_by_flag = {
            "auto_detect_gog": "_gog_games_cache",
            "auto_detect_ea": "_ea_games_cache",
            "auto_detect_battlenet": "_battlenet_games_cache",
            "auto_detect_ubisoft": "_ubisoft_games_cache",
            "auto_detect_xbox": "_xbox_games_cache",
        }
        for flag, cache_attr in cache_by_flag.items():
            with self.subTest(flag=flag):
                isolator = _make_isolator()
                self._disable_all_providers(isolator)
                getattr(isolator, cache_attr).add("launchergame.exe")

                self.assertFalse(isolator._is_game_name_normalized("launchergame.exe"))
                setattr(isolator, flag, True)
                self.assertTrue(isolator._is_game_name_normalized("launchergame.exe"))

    def test_library_scan_due_tracks_enabled_provider_timestamps(self):
        isolator = _make_isolator()
        self._disable_all_providers(isolator)
        now = time.monotonic()
        self.assertFalse(isolator._library_scan_due(now))

        # A stale timestamp only matters while its provider is enabled.
        isolator._last_ubisoft_scan = now - 301.0
        self.assertFalse(isolator._library_scan_due(now))
        isolator.auto_detect_ubisoft = True
        self.assertTrue(isolator._library_scan_due(now))

        isolator._last_ubisoft_scan = now - 10.0
        self.assertFalse(isolator._library_scan_due(now))


if __name__ == "__main__":
    unittest.main()
