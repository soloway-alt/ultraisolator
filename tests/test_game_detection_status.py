import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isolator.app import EsportsIsolatorPro
from isolator.outcomes import TuningState
from server.readiness import build_readiness_payload


class GameObservationStatusTests(unittest.TestCase):
    def make_isolator(self):
        return EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )

    def test_observed_blocked_game_is_visible_without_touched_state(self):
        isolator = self.make_isolator()
        with isolator._state_lock:
            isolator._active_games[4242] = {
                "pid": 4242,
                "name": "cs2.exe",
                "tuning_state": "blocked",
            }

        status = isolator.get_runtime_status()
        snapshot = isolator.get_live_snapshot()

        self.assertTrue(status["game_mode"])
        self.assertEqual([4242], status["active_game_pids"])
        self.assertEqual(
            [{"pid": 4242, "name": "cs2.exe", "tuning_state": "blocked"}],
            status["active_games"],
        )
        process = next(item for item in snapshot["processes"] if item["pid"] == 4242)
        self.assertEqual("observed_game", process["source"])
        self.assertEqual("blocked", process["tuning_state"])

    def test_monitoring_active_is_explicit(self):
        isolator = self.make_isolator()
        status = isolator.get_runtime_status()

        self.assertIn("monitoring_active", status)
        self.assertEqual(status["running"], status["monitoring_active"])

    def test_tuning_uses_snapshot_name_when_process_query_is_denied(self):
        isolator = self.make_isolator()
        isolator.games = {"cs2.exe"}
        isolator._get_process_name = lambda _pid: (_ for _ in ()).throw(
            AssertionError("SPI name must be reused")
        )
        isolator._open_process = lambda *_args, **_kwargs: None

        self.assertEqual(
            "blocked",
            isolator._optimize_game_with_state(4242, "cs2.exe"),
        )

    def test_conservative_protected_game_is_visible_as_skipped(self):
        isolator = self.make_isolator()
        isolator.games = {"valorant.exe"}
        isolator.anti_cheat_mode = "conservative"

        self.assertEqual(
            "skipped",
            isolator._optimize_game_with_state(4242, "valorant.exe"),
        )

    def test_tuning_state_enum_serializes_identically_to_raw_string(self):
        # TuningState is a str subclass precisely so the API wire format is
        # byte-identical to the raw strings it replaced.
        self.assertEqual(
            json.dumps({"pid": 4242, "name": "cs2.exe", "tuning_state": "applied"}),
            json.dumps({"pid": 4242, "name": "cs2.exe", "tuning_state": TuningState.APPLIED}),
        )

    def test_one_missed_poll_retains_observed_game_until_debounce(self):
        isolator = self.make_isolator()
        isolator.game_close_debounce_s = 3.0
        _, _, active, pending = isolator._update_active_game_observations(
            {4242: "cs2.exe"},
            {},
            100.0,
        )
        isolator._set_active_game_tuning_state(4242, "applied")

        _, confirmed, active, pending = isolator._update_active_game_observations(
            {},
            pending,
            101.0,
        )

        self.assertEqual([], confirmed)
        self.assertEqual({4242}, active)
        self.assertEqual("applied", isolator.get_runtime_status()["active_games"][0]["tuning_state"])

    def test_shutdown_clears_observed_games(self):
        isolator = self.make_isolator()
        with isolator._state_lock:
            isolator._active_games[4242] = {
                "pid": 4242,
                "name": "cs2.exe",
                "tuning_state": "blocked",
            }
        isolator._log = lambda _message: None
        isolator._restore_power_scheme = lambda: None
        isolator._restore_timer_resolution = lambda: None
        isolator._restore_ifeo_priorities = lambda: None
        isolator._restore_all_processes = lambda: None
        isolator._restore_system_critical = lambda: None
        isolator._close_log_file = lambda: None

        isolator.shutdown()

        self.assertEqual([], isolator.get_runtime_status()["active_games"])

    def test_monitor_reports_configured_game_when_direct_access_is_denied(self):
        isolator = self.make_isolator()

        class OneLoopStop:
            def __init__(self):
                self.waited = False

            def is_set(self):
                return self.waited

            def wait(self, _interval):
                self.waited = True
                return True

        isolator._stop_event = OneLoopStop()
        isolator._last_topology_refresh = 10**12
        isolator.auto_detect_steam = False
        isolator.auto_detect_epic = False
        isolator.games = {"cs2.exe"}
        isolator._get_processes = lambda: [(4242, "cs2.exe")]
        isolator._open_process = lambda *_args, **_kwargs: None
        isolator._refresh_topology = lambda _reason: None
        isolator._run_background_jail = lambda **_kwargs: {}
        isolator._set_preferred_power_scheme = lambda: False
        isolator._cleanup_dead_processes = lambda *_args, **_kwargs: None

        with mock.patch("isolator.runtime.user32.GetForegroundWindow", return_value=0), \
                mock.patch("isolator.runtime.gc.disable"), \
                mock.patch("isolator.runtime.gc.collect"):
            isolator._monitor_loop()

        self.assertEqual(
            [{"pid": 4242, "name": "cs2.exe", "tuning_state": "blocked"}],
            isolator.get_runtime_status()["active_games"],
        )

    def test_monitor_tunes_path_classified_store_game_with_generic_name(self):
        class OneLoopStop:
            def __init__(self):
                self.waited = False

            def is_set(self):
                return self.waited

            def wait(self, _interval):
                self.waited = True
                return True

        cases = (
            ("steam", r"D:\SteamLibrary\steamapps\common\Example\genericgame.exe"),
            ("epic", r"D:\Epic Games\Example\genericgame.exe"),
        )
        for provider, executable_path in cases:
            with self.subTest(provider=provider):
                isolator = self.make_isolator()
                isolator._stop_event = OneLoopStop()
                isolator._last_topology_refresh = 10**12
                isolator._last_steam_scan = 10**12
                isolator._last_epic_scan = 10**12
                isolator.auto_detect_steam = provider == "steam"
                isolator.auto_detect_epic = provider == "epic"
                isolator.games = set()
                isolator._get_processes = lambda: [(4242, "genericgame.exe")]
                isolator._get_process_full_path = lambda _pid, path=executable_path: path
                isolator._open_process = lambda *_args, **_kwargs: None
                isolator._refresh_topology = lambda _reason: None
                isolator._run_background_jail = lambda **_kwargs: {}
                isolator._set_preferred_power_scheme = lambda: False
                isolator._cleanup_dead_processes = lambda *_args, **_kwargs: None

                with mock.patch("isolator.runtime.user32.GetForegroundWindow", return_value=0), \
                        mock.patch("isolator.runtime.gc.disable"), \
                        mock.patch("isolator.runtime.gc.collect"):
                    isolator._monitor_loop()

                self.assertEqual(
                    [{"pid": 4242, "name": "genericgame.exe", "tuning_state": "blocked"}],
                    isolator.get_runtime_status()["active_games"],
                )

    def test_monitor_single_miss_does_not_restore_observed_game(self):
        isolator = self.make_isolator()

        class TwoLoopStop:
            def __init__(self):
                self.wait_count = 0

            def is_set(self):
                return self.wait_count >= 2

            def wait(self, _interval):
                self.wait_count += 1
                return self.wait_count >= 2

        snapshots = iter([[(4242, "cs2.exe")], []])
        restored = []
        isolator._stop_event = TwoLoopStop()
        isolator._last_topology_refresh = 10**12
        isolator.auto_detect_steam = False
        isolator.auto_detect_epic = False
        isolator.games = {"cs2.exe"}
        isolator._get_processes = lambda: next(snapshots)
        isolator._open_process = lambda *_args, **_kwargs: None
        isolator._restore_process = lambda pid: restored.append(pid)
        isolator._refresh_topology = lambda _reason: None
        isolator._run_background_jail = lambda **_kwargs: {}
        isolator._set_preferred_power_scheme = lambda: False
        isolator._cleanup_dead_processes = lambda *_args, **_kwargs: None

        with mock.patch("isolator.runtime.user32.GetForegroundWindow", return_value=0), \
                mock.patch("isolator.runtime.gc.disable"), \
                mock.patch("isolator.runtime.gc.collect"):
            isolator._monitor_loop()

        self.assertEqual([], restored)
        self.assertEqual([4242], isolator.get_runtime_status()["active_game_pids"])

    def test_repeated_empty_snapshots_do_not_expire_observed_game(self):
        isolator = self.make_isolator()

        class ThreeLoopStop:
            def __init__(self):
                self.wait_count = 0

            def is_set(self):
                return self.wait_count >= 3

            def wait(self, _interval):
                self.wait_count += 1
                return self.wait_count >= 3

        snapshots = iter([[(4242, "cs2.exe")], [], []])
        restored = []
        isolator._stop_event = ThreeLoopStop()
        isolator._last_topology_refresh = 10**12
        isolator.auto_detect_steam = False
        isolator.auto_detect_epic = False
        isolator.games = {"cs2.exe"}
        isolator.game_close_debounce_s = 3.0
        isolator._get_processes = lambda: next(snapshots)
        isolator._open_process = lambda *_args, **_kwargs: None
        isolator._restore_process = lambda pid: restored.append(pid)
        isolator._refresh_topology = lambda _reason: None
        isolator._run_background_jail = lambda **_kwargs: {}
        isolator._set_preferred_power_scheme = lambda: False
        isolator._cleanup_dead_processes = lambda *_args, **_kwargs: None
        isolator._log_once = lambda *_args, **_kwargs: None

        with mock.patch(
            "isolator.runtime.time.monotonic",
            side_effect=[0.0, 0.0, 0.0, 100.0, 101.0, 105.0],
        ), mock.patch(
            "isolator.runtime.user32.GetForegroundWindow", return_value=0
        ), mock.patch("isolator.runtime.gc.disable"), mock.patch("isolator.runtime.gc.collect"):
            isolator._monitor_loop()

        self.assertEqual([], restored)
        self.assertEqual([4242], isolator.get_runtime_status()["active_game_pids"])

    def test_runtime_status_copies_structured_capability_issues(self):
        isolator = self.make_isolator()
        issue = {
            "code": "processor_groups_unavailable",
            "data": {"group_count": 2},
            "severity": "warning",
        }
        with isolator._state_lock:
            isolator._capability_issues.append(issue)

        status = isolator.get_runtime_status()
        status_issue = next(
            candidate
            for candidate in status["capability_issues"]
            if candidate.get("code") == issue["code"]
        )
        status_issue["data"]["group_count"] = 99

        stored_issue = next(
            candidate
            for candidate in isolator._capability_issues
            if candidate.get("code") == issue["code"]
        )
        self.assertEqual(2, stored_issue["data"]["group_count"])

    def test_cleanup_keeps_debounced_game_state_missing_from_snapshot(self):
        isolator = self.make_isolator()
        with isolator._state_lock:
            isolator._touched[4242] = {
                "name": "cs2.exe",
                "source": "optimize_game",
                "threads": {},
            }

        isolator._cleanup_dead_processes(
            processes=[(77, "discord.exe")],
            game_pids={4242},
        )

        self.assertIn(4242, isolator._touched)


class LibraryDiscoveryTests(unittest.TestCase):
    def make_isolator(self):
        return EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )

    def test_manual_steam_root_works_without_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            common = Path(tmpdir) / "steamapps" / "common" / "ExampleGame"
            common.mkdir(parents=True)
            (common / "example.exe").write_bytes(b"")
            isolator = self.make_isolator()
            isolator.auto_detect_steam = True
            isolator.steam_library_paths = [tmpdir]
            isolator._get_steam_path = lambda: None

            isolator._scan_steam_games(force=True)

        self.assertIn("example.exe", isolator._steam_games_cache)
        self.assertTrue(isolator.auto_detect_steam)

    def test_missing_steam_install_keeps_retry_enabled_and_reports_code(self):
        isolator = self.make_isolator()
        isolator.auto_detect_steam = True
        isolator.steam_library_paths = []
        isolator._get_steam_path = lambda: None

        isolator._scan_steam_games(force=True)

        self.assertTrue(isolator.auto_detect_steam)
        self.assertIn(
            "steam_install_not_found",
            {issue["code"] for issue in isolator._discovery_issues},
        )

    def test_epic_item_manifest_discovers_external_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            manifests = base / "Manifests"
            install = base / "ExternalLibrary" / "ExampleGame"
            manifests.mkdir()
            install.mkdir(parents=True)
            (install / "examplegame.exe").write_bytes(b"")
            (manifests / "example.item").write_text(
                json.dumps(
                    {
                        "InstallLocation": str(install),
                        "LaunchExecutable": "examplegame.exe",
                    }
                ),
                encoding="utf-8",
            )
            isolator = self.make_isolator()
            isolator.auto_detect_epic = True
            isolator.epic_library_paths = []
            isolator._get_epic_path = lambda: None
            isolator._get_epic_manifest_dirs = lambda: [str(manifests)]

            isolator._scan_epic_games(force=True)

        self.assertIn("examplegame.exe", isolator._epic_games_cache)

    def test_epic_non_object_manifest_is_reported_and_next_manifest_is_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifests = Path(tmpdir) / "Manifests"
            install = Path(tmpdir) / "ExternalLibrary" / "ExampleGame"
            manifests.mkdir()
            install.mkdir(parents=True)
            (manifests / "invalid.item").write_text("[]", encoding="utf-8")
            (manifests / "valid.item").write_text(
                json.dumps(
                    {
                        "InstallLocation": str(install),
                        "LaunchExecutable": "examplegame.exe",
                    }
                ),
                encoding="utf-8",
            )
            isolator = self.make_isolator()
            isolator._get_epic_manifest_dirs = lambda: [str(manifests)]

            with mock.patch(
                "isolator.discovery.os.listdir",
                return_value=["invalid.item", "valid.item"],
            ):
                paths, executables = isolator._read_epic_manifests()

        self.assertEqual([os.path.normpath(str(install))], paths)
        self.assertEqual({"examplegame.exe"}, executables)
        self.assertIn(
            "epic_manifest_invalid",
            {issue["code"] for issue in isolator._discovery_issues},
        )

    def test_steam_walk_permission_error_reports_provider_scan_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            common = Path(tmpdir) / "steamapps" / "common"
            common.mkdir(parents=True)
            isolator = self.make_isolator()
            isolator.auto_detect_steam = True
            isolator.steam_library_paths = [tmpdir]
            isolator._get_steam_path = lambda: None

            with mock.patch(
                "isolator.discovery.os.scandir",
                side_effect=PermissionError("denied"),
            ):
                isolator._scan_steam_games(force=True)

        self.assertIn(
            "steam_library_scan_failed",
            {issue["code"] for issue in isolator._discovery_issues},
        )

    def test_epic_walk_permission_error_reports_provider_scan_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            library = Path(tmpdir) / "EpicLibrary"
            library.mkdir()
            isolator = self.make_isolator()
            isolator.auto_detect_epic = True
            isolator.epic_library_paths = [str(library)]
            isolator._get_epic_path = lambda: None
            isolator._get_epic_manifest_dirs = lambda: []

            with mock.patch(
                "isolator.discovery.os.scandir",
                side_effect=PermissionError("denied"),
            ):
                isolator._scan_epic_games(force=True)

        self.assertIn(
            "epic_library_scan_failed",
            {issue["code"] for issue in isolator._discovery_issues},
        )


class ReadinessConfigurationTests(unittest.TestCase):
    def test_configured_power_timer_and_games_are_ready_before_game(self):
        payload = build_readiness_payload(
            {
                "admin": True,
                "game_mode": False,
                "power_plan_active": False,
                "timer_resolution_applied": None,
                "persistent_recovery_incomplete": False,
                "reported_failure_count": 0,
                "capability_notes": [],
            },
            {"available": True, "summary": {}},
            {
                "games": ["cs2.exe"],
                "disable_power_scheme_switch": False,
                "disable_timer_resolution_tweak": False,
                "disable_game_priority_boost": False,
                "enable_background_jailing": True,
            },
        )
        by_id = {check["id"]: check for check in payload["checks"]}

        self.assertEqual("ok", by_id["power_plan"]["status"])
        self.assertEqual("ok", by_id["timer_resolution"]["status"])
        self.assertEqual("ok", by_id["configured_games"]["status"])
        self.assertIn("1", by_id["configured_games"]["detail"])


if __name__ == "__main__":
    unittest.main()
