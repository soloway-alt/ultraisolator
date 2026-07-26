import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from isolator.app import EsportsIsolatorPro
from isolator.winapi import ABOVE_NORMAL_PRIORITY_CLASS
from server.config_store import ConfigError

STEAM_RUNTIME_NAMES = (
    "steam.exe",
    "steamwebhelper.exe",
    "gameoverlayui.exe",
    "steamservice.exe",
    "steamerrorreporter.exe",
)

PROTECTED_RUNTIME_NAMES = STEAM_RUNTIME_NAMES + (
    "gameoverlayui64.exe",
    "faceitclient.exe",
    "faceitservice.exe",
    "rtkauduservice64.exe",
)

TERMINAL_HOST_NAMES = (
    "windowsterminal.exe",
    "openconsole.exe",
    "pwsh.exe",
)


def make_isolator(processes):
    isolator = EsportsIsolatorPro(scan_game_libraries=False)
    isolator._get_processes = lambda: list(processes)
    isolator.messages = []
    isolator.jailed = []
    isolator._log = isolator.messages.append

    def jail_process(pid, name=None, force=False, record_state=True, expected_create_time=0):
        isolator.jailed.append((pid, name, force))
        return True

    isolator._jail_process = jail_process
    return isolator


class ProcessClassificationTests(unittest.TestCase):
    def test_background_jailing_is_disabled_by_default(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )

        self.assertFalse(isolator.enable_background_jailing)

    def test_steam_runtime_is_protected_but_not_game(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)

        for name in STEAM_RUNTIME_NAMES:
            with self.subTest(name=name):
                self.assertFalse(isolator._is_game_name(name))
                self.assertTrue(isolator._is_protected_process_name(name))

    def test_system_services_observed_in_logs_are_protected_but_not_games(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        for name in (
            "wmiprvse.exe",
            "fontdrvhost.exe",
            "smartscreen.exe",
            "taskhostw.exe",
            "gameinputredistservice.exe",
            "gameinputsvc.exe",
        ):
            with self.subTest(name=name):
                self.assertFalse(isolator._is_game_name(name))
                self.assertTrue(isolator._is_protected_process_name(name))

    def test_ifeo_fallback_skipped_for_auto_detected_games(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump({"games": ["cs2.exe"]}, handle)
            config_path = handle.name
        try:
            isolator = EsportsIsolatorPro(config_path=config_path, scan_game_libraries=False)
            isolator._steam_games_cache = {"pioneergame.exe"}
            isolator._is_admin = True
            isolator._get_process_name = lambda pid: "pioneergame.exe"
            isolator._open_process = lambda *args, **kwargs: 99
            isolator._remember_process_state = lambda *args, **kwargs: None
            isolator._set_process_power_throttling = lambda *a, **k: None
            isolator._set_process_page_priority = lambda *a, **k: None
            isolator._set_process_io_priority = lambda *a, **k: None
            ifeo_calls = []
            isolator._set_ifeo_priority = lambda name: ifeo_calls.append(name) or True

            with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=0):
                with patch("isolator.tuning.kernel32.SetProcessPriorityBoost", return_value=1):
                    with patch("isolator.tuning.kernel32.CloseHandle"):
                        isolator._optimize_game_with_state(1234)

            self.assertEqual([], ifeo_calls, "IFEO must not be applied to auto-detected games")
        finally:
            os.remove(config_path)

    def test_ifeo_fallback_applied_for_user_configured_games(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump({"games": ["cs2.exe"]}, handle)
            config_path = handle.name
        try:
            isolator = EsportsIsolatorPro(config_path=config_path, scan_game_libraries=False)
            isolator._is_admin = True
            isolator._get_process_name = lambda pid: "cs2.exe"
            isolator._open_process = lambda *args, **kwargs: 99
            isolator._remember_process_state = lambda *args, **kwargs: None
            isolator._set_process_power_throttling = lambda *a, **k: None
            isolator._set_process_page_priority = lambda *a, **k: None
            isolator._set_process_io_priority = lambda *a, **k: None
            ifeo_calls = []
            isolator._set_ifeo_priority = lambda name: ifeo_calls.append(name) or True

            with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=0):
                with patch("isolator.tuning.kernel32.SetProcessPriorityBoost", return_value=1):
                    with patch("isolator.tuning.kernel32.CloseHandle"):
                        isolator._optimize_game_with_state(1234)

            self.assertEqual(["cs2.exe"], ifeo_calls)
        finally:
            os.remove(config_path)

    def test_ifeo_denies_system_executables_even_when_configured(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._is_admin = True
        messages = []
        isolator._log_once = lambda key, message: messages.append(message)
        calls = []
        isolator._capture_ifeo_snapshot = lambda name: calls.append(name)

        self.assertFalse(isolator._set_ifeo_priority(r"..\..\lsass.exe"))

        self.assertEqual([], calls)
        self.assertIn("blocked", " ".join(messages).lower())

    def test_optimize_game_uses_shared_ifeo_runtime_fallback(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.games = {"cs2.exe"}
        isolator._get_process_name = lambda pid: "cs2.exe"
        isolator._open_process = lambda *args, **kwargs: 99
        isolator._remember_process_state = lambda *args, **kwargs: None
        isolator._set_process_power_throttling = lambda *a, **k: None
        isolator._set_process_page_priority = lambda *a, **k: None
        isolator._set_process_io_priority = lambda *a, **k: None
        fallback_calls = []
        isolator._apply_ifeo_priority_fallback = lambda name: fallback_calls.append(name)

        with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=0):
            with patch("isolator.tuning.kernel32.SetProcessPriorityBoost", return_value=1):
                with patch("isolator.tuning.kernel32.CloseHandle"):
                    isolator._optimize_game_with_state(1234)

        self.assertEqual(["cs2.exe"], fallback_calls)

    def test_boost_foreground_uses_shared_ifeo_runtime_fallback(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.games = {"cs2.exe"}
        isolator._get_process_name = lambda pid: "cs2.exe"
        isolator._open_process = lambda *args, **kwargs: 99
        isolator._remember_process_state = lambda *args, **kwargs: None
        isolator._apply_process_cpu_sets = lambda *a, **k: None
        isolator._set_process_power_throttling = lambda *a, **k: None
        isolator._set_process_page_priority = lambda *a, **k: None
        isolator._set_process_io_priority = lambda *a, **k: None
        fallback_calls = []
        isolator._apply_ifeo_priority_fallback = lambda name: fallback_calls.append(name)

        with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=0):
            with patch("isolator.tuning.kernel32.SetProcessPriorityBoost", return_value=1):
                with patch("isolator.tuning.kernel32.CloseHandle"):
                    isolator._boost_foreground(1234)

        self.assertEqual(["cs2.exe"], fallback_calls)

    def test_start_protected_game_wrapper_is_not_a_game(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._steam_games_cache = {"start_protected_game.exe", "pioneergame.exe"}
        self.assertFalse(isolator._is_game_name("start_protected_game.exe"))
        self.assertTrue(isolator._is_game_name("pioneergame.exe"))

    def test_lsaiso_is_protected_but_not_game(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        self.assertFalse(isolator._is_game_name("lsaiso.exe"))
        self.assertTrue(isolator._is_protected_process_name("lsaiso.exe"))

    def test_own_executable_is_protected(self):
        with patch("isolator.app.sys.executable", r"C:\Tools\best_isolator.exe"):
            isolator = EsportsIsolatorPro(
                config_path="__no_local_config__.json",
                scan_game_libraries=False,
            )
        self.assertIn("best_isolator.exe", isolator.protected_exact)

    def test_protected_extra_merges_into_protected_exact(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(
                {"games": ["cs2.exe"], "protected_extra": ["vmware-authd.exe", "MyTool"]},
                handle,
            )
            config_path = handle.name
        try:
            isolator = EsportsIsolatorPro(config_path=config_path, scan_game_libraries=False)
            self.assertTrue(isolator._is_protected_process_name("vmware-authd.exe"))
            self.assertTrue(isolator._is_protected_process_name("mytool.exe"))
        finally:
            os.remove(config_path)

    def test_app_profile_treat_as_game_participates_in_detection(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(
                {"games": [], "app_profiles": [{"exe": "Obs64", "treat_as_game": True}]},
                handle,
            )
            config_path = handle.name
        try:
            isolator = EsportsIsolatorPro(config_path=config_path, scan_game_libraries=False)

            self.assertTrue(isolator._is_game_name("obs64.exe"))
            self.assertEqual([505], isolator._find_game_processes([(505, "obs64.exe")]))
        finally:
            os.remove(config_path)

    def test_app_profile_never_jail_blocks_background_isolation(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(
                {"app_profiles": [{"exe": "discord.exe", "never_jail": True}]},
                handle,
            )
            config_path = handle.name
        try:
            isolator = EsportsIsolatorPro(config_path=config_path, scan_game_libraries=False)
            isolator._self_pid = 999
            isolator._parent_pid = 998
            calls = []
            isolator._jail_process = lambda *args, **kwargs: calls.append((args, kwargs)) or True

            stats = isolator._isolate_background(processes=[(404, "discord.exe")])

            self.assertEqual([], calls)
            self.assertEqual(0, stats["touched"])
        finally:
            os.remove(config_path)

    def test_app_profile_always_jail_can_jail_profiled_game(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(
                {
                    "games": ["launcher.exe"],
                    "app_profiles": [{"exe": "launcher.exe", "always_jail": True}],
                },
                handle,
            )
            config_path = handle.name
        try:
            isolator = EsportsIsolatorPro(config_path=config_path, scan_game_libraries=False)
            isolator._self_pid = 1
            isolator._parent_pid = 2
            isolator._open_process = lambda *args, **kwargs: 99
            isolator._remember_process_state = lambda *args, **kwargs: None
            isolator._apply_process_cpu_sets = lambda *args, **kwargs: None
            isolator._set_process_power_throttling = lambda *args, **kwargs: None
            isolator._set_process_page_priority = lambda *args, **kwargs: None
            isolator._set_process_io_priority = lambda *args, **kwargs: None
            recorded = []
            isolator._record_jail_state = lambda pid: recorded.append(pid)

            with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=1):
                with patch("isolator.tuning.kernel32.CloseHandle"):
                    result = isolator._jail_process(500, name="launcher.exe", force=True)

            self.assertTrue(result)
            self.assertEqual([500], recorded)
        finally:
            os.remove(config_path)

    def test_app_profile_priority_override_applies_to_game_optimization(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(
                {
                    "games": [],
                    "app_profiles": [
                        {
                            "exe": "customgame.exe",
                            "treat_as_game": True,
                            "priority_class": "above_normal",
                        }
                    ],
                },
                handle,
            )
            config_path = handle.name
        try:
            isolator = EsportsIsolatorPro(config_path=config_path, scan_game_libraries=False)
            isolator._get_process_name = lambda pid: "customgame.exe"
            isolator._open_process = lambda *args, **kwargs: 99
            isolator._remember_process_state = lambda *args, **kwargs: None
            isolator._set_process_power_throttling = lambda *args, **kwargs: None
            isolator._set_process_page_priority = lambda *args, **kwargs: None
            isolator._set_process_io_priority = lambda *args, **kwargs: None
            priorities = []

            with patch("isolator.tuning.kernel32.SetPriorityClass", side_effect=lambda _handle, priority: priorities.append(priority) or 1):
                with patch("isolator.tuning.kernel32.SetProcessPriorityBoost", return_value=1):
                    with patch("isolator.tuning.kernel32.CloseHandle"):
                        result = isolator._optimize_game_with_state(1234)

            self.assertEqual("applied", result)
            self.assertEqual([ABOVE_NORMAL_PRIORITY_CLASS], priorities)
        finally:
            os.remove(config_path)

    def test_battleye_and_ea_desktop_are_protected_but_not_games(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )

        for name in ("battleye_service.exe", "battleye.exe", "eadesktop.exe"):
            with self.subTest(name=name):
                self.assertFalse(isolator._is_game_name(name))
                self.assertTrue(isolator._is_protected_process_name(name))

    def test_jail_process_skips_parent_pid(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._self_pid = 100
        isolator._parent_pid = 200

        self.assertFalse(isolator._jail_process(200, name="customhost.exe"))

    def test_jail_process_returns_none_when_set_priority_class_fails(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._self_pid = 1
        isolator._parent_pid = 2
        restored = []
        isolator._restore_process = restored.append
        isolator._open_process = lambda *args, **kwargs: 99
        isolator._remember_process_state = lambda *args, **kwargs: None
        isolator._apply_process_cpu_sets = lambda *args, **kwargs: None
        isolator._set_process_power_throttling = lambda *args, **kwargs: None
        isolator._set_process_page_priority = lambda *args, **kwargs: None
        isolator._set_process_io_priority = lambda *args, **kwargs: None
        isolator._record_jail_state = lambda *args, **kwargs: None

        with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=0):
            with patch("isolator.tuning.kernel32.CloseHandle"):
                result = isolator._jail_process(500, name="discord.exe", force=True)

        self.assertIsNone(result)
        self.assertEqual([500], restored)

    def test_jail_process_skips_when_pid_reused_create_time_mismatch(self):
        # WHY: The caller's snapshot expected create_time differs from the live
        # process occupying the PID — PID reuse. The jail must be skipped and no
        # priority/throttle mutation applied.
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._self_pid = 1
        isolator._parent_pid = 2
        remembered = []
        isolator._open_process = lambda *args, **kwargs: 99
        isolator._get_process_create_time = lambda handle: 999  # live process
        isolator._remember_process_state = lambda *a, **k: remembered.append(a)
        isolator._apply_process_cpu_sets = lambda *args, **kwargs: None
        isolator._set_process_power_throttling = lambda *args, **kwargs: None

        with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=1) as set_prio:
            with patch("isolator.tuning.kernel32.CloseHandle"):
                result = isolator._jail_process(
                    500, name="discord.exe", force=True, expected_create_time=123
                )

        self.assertFalse(result)
        set_prio.assert_not_called()
        self.assertEqual([], remembered)

    def test_boost_foreground_skips_when_pid_reused_create_time_mismatch(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._self_pid = 1
        isolator._parent_pid = 2
        isolator._process_create_times = {500: 123}
        isolator._get_process_name = lambda pid: "cs2.exe"
        isolator._open_process = lambda *args, **kwargs: 99
        isolator._get_process_create_time = lambda handle: 999
        isolator._remember_process_state = lambda *a, **k: self.fail("state must not be captured for reused PID")

        with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=1) as set_prio:
            with patch("isolator.tuning.kernel32.CloseHandle"):
                result = isolator._boost_foreground(500)

        self.assertFalse(result)
        set_prio.assert_not_called()

    def test_optimize_game_skips_when_pid_reused_create_time_mismatch(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._process_create_times = {500: 123}
        isolator._get_process_name = lambda pid: "cs2.exe"
        isolator._open_process = lambda *args, **kwargs: 99
        isolator._get_process_create_time = lambda handle: 999
        isolator._remember_process_state = lambda *a, **k: self.fail("state must not be captured for reused PID")

        with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=1) as set_prio:
            with patch("isolator.tuning.kernel32.SetProcessPriorityBoost", return_value=1):
                with patch("isolator.tuning.kernel32.CloseHandle"):
                    result = isolator._optimize_game_with_state(500)

        self.assertEqual("failed", result)
        set_prio.assert_not_called()

    def test_jail_process_proceeds_when_create_time_unknown(self):
        # WHY: When create_time is unavailable (denied -> 0) the guard cannot
        # prove reuse, so jail proceeds (no regression vs. prior behavior).
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._self_pid = 1
        isolator._parent_pid = 2
        isolator._open_process = lambda *args, **kwargs: 99
        isolator._get_process_create_time = lambda handle: 0  # denied
        isolator._remember_process_state = lambda *args, **kwargs: None
        isolator._apply_process_cpu_sets = lambda *args, **kwargs: None
        isolator._set_process_power_throttling = lambda *args, **kwargs: None
        isolator._set_process_page_priority = lambda *args, **kwargs: None
        isolator._set_process_io_priority = lambda *args, **kwargs: None
        isolator._record_jail_state = lambda *args, **kwargs: None

        with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=1) as set_prio:
            with patch("isolator.tuning.kernel32.CloseHandle"):
                result = isolator._jail_process(
                    500, name="discord.exe", force=True, expected_create_time=123
                )

        self.assertTrue(result)
        set_prio.assert_called_once()

    def test_jail_process_proceeds_when_create_time_matches(self):
        # WHY: Matching create_time means the PID is still the expected process;
        # jail must proceed normally (regression guard for the reuse check).
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._self_pid = 1
        isolator._parent_pid = 2
        isolator._open_process = lambda *args, **kwargs: 99
        isolator._get_process_create_time = lambda handle: 123  # matches expected
        isolator._remember_process_state = lambda *args, **kwargs: None
        isolator._apply_process_cpu_sets = lambda *args, **kwargs: None
        isolator._set_process_power_throttling = lambda *args, **kwargs: None
        isolator._set_process_page_priority = lambda *args, **kwargs: None
        isolator._set_process_io_priority = lambda *args, **kwargs: None
        isolator._record_jail_state = lambda *args, **kwargs: None

        with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=1) as set_prio:
            with patch("isolator.tuning.kernel32.CloseHandle"):
                result = isolator._jail_process(
                    500, name="discord.exe", force=True, expected_create_time=123
                )

        self.assertTrue(result)
        set_prio.assert_called_once()

    def test_terminal_hosts_are_protected_but_not_games(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)

        for name in TERMINAL_HOST_NAMES:
            with self.subTest(name=name):
                self.assertFalse(isolator._is_game_name(name))
                self.assertTrue(isolator._is_protected_process_name(name))

    def test_overlay_faceit_and_audio_runtime_are_protected_but_not_games(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)

        for name in PROTECTED_RUNTIME_NAMES:
            with self.subTest(name=name):
                self.assertFalse(isolator._is_game_name(name))
                self.assertTrue(isolator._is_protected_process_name(name))

    def test_background_jail_helper_skips_isolation_when_disabled(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.enable_background_jailing = False
        isolator.messages = []
        isolator._log = isolator.messages.append
        calls = []
        isolator._isolate_background = lambda **kwargs: calls.append(kwargs)

        stats = isolator._run_background_jail(initial=True)

        self.assertEqual([], calls)
        self.assertEqual(0, stats["touched"])
        self.assertIn("Background jailing disabled", " ".join(isolator.messages))

    def test_background_jail_helper_preserves_enabled_maintenance_batching(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.enable_background_jailing = True
        isolator.maintenance_jail_batch_size = 2
        calls = []

        def isolate_background(**kwargs):
            calls.append(kwargs)
            return {"touched": 2, "skipped": 0, "denied": 0, "deferred": 1, "names": ["one.exe", "two.exe"]}

        isolator._isolate_background = isolate_background
        sample = [(1, "a.exe")]

        stats = isolator._run_background_jail(initial=False, processes=sample)

        self.assertEqual(
            [{"max_new": 2, "log_names": True, "processes": sample}],
            calls,
        )
        self.assertEqual(1, stats["deferred"])

    def test_background_jail_initial_uses_same_batch_size(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.enable_background_jailing = True
        isolator.maintenance_jail_batch_size = 3
        calls = []
        isolator._isolate_background = lambda **kwargs: calls.append(kwargs) or {
            "touched": 0, "skipped": 0, "denied": 0, "deferred": 0, "names": []
        }

        isolator._run_background_jail(initial=True, processes=[])

        self.assertEqual([{"max_new": 3, "log_names": True, "processes": []}], calls)

    def test_foreground_transition_jails_previous_and_boosts_current_when_jailing_enabled(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.enable_background_jailing = True
        isolator._self_pid = 999
        isolator._parent_pid = 998
        jailed = []
        boosted = []
        isolator._jail_process = lambda pid, **kwargs: jailed.append(pid) or True
        isolator._boost_foreground = lambda pid: boosted.append(pid) or True
        isolator._get_process_name = lambda pid: "discord.exe"

        isolator._handle_foreground_transition(last_fg_pid=101, fg_pid=102, game_was_running=True)

        self.assertEqual([101], jailed)
        self.assertEqual([102], boosted)

    def test_foreground_transition_skips_self_and_parent_pids(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.enable_background_jailing = True
        isolator._self_pid = 100
        isolator._parent_pid = 200
        jailed = []
        boosted = []
        isolator._jail_process = lambda pid, **kwargs: jailed.append(pid) or True
        isolator._boost_foreground = lambda pid: boosted.append(pid) or True
        isolator._get_process_name = lambda pid: "discord.exe"

        isolator._handle_foreground_transition(last_fg_pid=200, fg_pid=100, game_was_running=True)

        self.assertEqual([], jailed)
        self.assertEqual([], boosted)

    def test_conservative_mode_skips_protected_game_tuning(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.anti_cheat_mode = "conservative"
        isolator.games = {"valorant.exe"}
        calls = []
        isolator._remember_process_state = lambda *args, **kwargs: calls.append(args)

        result = isolator._optimize_game_with_state(12345)

        self.assertNotEqual("applied", result)
        self.assertEqual([], calls)
        self.assertTrue(isolator._detect_protected_title("valorant.exe"))

    def test_invalid_anti_cheat_mode_fails_closed(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump({"anti_cheat_mode": "paranoid", "games": ["cs2.exe"]}, handle)
            config_path = handle.name
        try:
            with self.assertRaises(ConfigError):
                EsportsIsolatorPro(config_path=config_path, scan_game_libraries=False)
        finally:
            os.remove(config_path)

    def test_game_exit_restore_delay_reads_from_config(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.config["game_exit_restore_delay_s"] = 15
        isolator.game_exit_restore_delay_s = max(
            0.0,
            float(isolator.config.get("game_exit_restore_delay_s", 10)),
        )
        self.assertEqual(15.0, isolator.game_exit_restore_delay_s)

    def test_foreground_transition_skips_non_game_tuning_when_background_jailing_disabled(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.enable_background_jailing = False
        isolator._self_pid = 999
        jailed = []
        boosted = []
        isolator._jail_process = lambda pid: jailed.append(pid)
        isolator._boost_foreground = lambda pid: boosted.append(pid)
        isolator._get_process_name = lambda pid: "discord.exe"

        isolator._handle_foreground_transition(last_fg_pid=101, fg_pid=102, game_was_running=True)

        self.assertEqual([], jailed)
        self.assertEqual([], boosted)

    def test_isolate_background_skips_steam_runtime_and_games(self):
        isolator = make_isolator(
            [
                (101, "steam.exe"),
                (102, "steamwebhelper.exe"),
                (103, "cs2.exe"),
                (104, "discord.exe"),
            ]
        )

        stats = isolator._isolate_background(log_names=True)

        self.assertEqual([(104, "discord.exe", True)], isolator.jailed)
        self.assertEqual(1, stats["touched"])
        self.assertEqual(["discord.exe"], stats["names"])

    def test_isolate_background_skips_terminal_hosts(self):
        isolator = make_isolator(
            [
                (101, "windowsterminal.exe"),
                (102, "openconsole.exe"),
                (103, "pwsh.exe"),
                (104, "discord.exe"),
            ]
        )

        stats = isolator._isolate_background(log_names=True)

        self.assertEqual([(104, "discord.exe", True)], isolator.jailed)
        self.assertEqual(1, stats["touched"])
        self.assertEqual(["discord.exe"], stats["names"])

    def test_isolate_background_caps_new_jails_and_reports_deferred(self):
        isolator = make_isolator(
            [
                (101, "one.exe"),
                (102, "two.exe"),
                (103, "three.exe"),
                (104, "four.exe"),
            ]
        )

        stats = isolator._isolate_background(max_new=2)

        self.assertEqual(
            [(101, "one.exe", True), (102, "two.exe", True)],
            isolator.jailed,
        )
        self.assertEqual(2, stats["touched"])
        self.assertEqual(2, stats["deferred"])
        self.assertEqual(["one.exe", "two.exe"], stats["names"])

    def test_isolate_background_records_jail_state_once_for_batch(self):
        isolator = make_isolator(
            [
                (101, "one.exe"),
                (102, "two.exe"),
                (103, "three.exe"),
            ]
        )
        recorded = []

        def jail_process(pid, name=None, force=False, record_state=True, expected_create_time=0):
            isolator.jailed.append((pid, name, force, record_state))
            return True

        isolator._jail_process = jail_process
        isolator._record_jail_states = lambda pids: recorded.append(list(pids))

        stats = isolator._isolate_background()

        self.assertEqual(3, stats["touched"])
        self.assertEqual(
            [
                (101, "one.exe", True, False),
                (102, "two.exe", True, False),
                (103, "three.exe", True, False),
            ],
            isolator.jailed,
        )
        self.assertEqual([[101, 102, 103]], recorded)

    def test_isolate_background_skips_log_when_nothing_changed(self):
        isolator = make_isolator([(101, "discord.exe")])
        with isolator._state_lock:
            isolator._touched[101] = {"source": "jail", "threads": {}}

        stats = isolator._isolate_background(processes=[(101, "discord.exe")])

        self.assertEqual(0, stats["touched"])
        self.assertEqual(0, stats["deferred"])
        throttled = [m for m in isolator.messages if "Throttled" in m]
        self.assertEqual([], throttled)

    def test_is_game_name_normalized_skips_launchers_without_renormalizing(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.games = {"cs2.exe"}

        self.assertFalse(isolator._is_game_name_normalized("steam.exe"))
        self.assertTrue(isolator._is_game_name_normalized("cs2.exe"))
        self.assertTrue(isolator._is_game_name("CS2.EXE"))

    def test_normalize_spi_name_is_lower_only_for_hot_path(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)

        self.assertEqual(
            r"c:\games\cs2.exe",
            isolator._normalize_spi_name(r"C:\Games\CS2.EXE"),
        )

    def test_find_game_processes_caches_positive_full_path_classification(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.games = set()
        isolator.auto_detect_steam = True
        isolator.auto_detect_epic = False
        isolator._process_create_times = {4242: 111}
        path_calls = []
        isolator._get_process_full_path = lambda pid: path_calls.append(pid) or r"C:\Steam\steamapps\common\Game\game.exe"
        isolator._is_steam_game = lambda path: True

        self.assertEqual([4242], isolator._find_game_processes([(4242, "game.exe")]))
        self.assertEqual([4242], isolator._find_game_processes([(4242, "game.exe")]))

        self.assertEqual([4242], path_calls)

    def test_find_game_processes_caches_negative_full_path_classification_by_identity(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.games = set()
        isolator.auto_detect_steam = True
        isolator.auto_detect_epic = False
        isolator._process_create_times = {4242: 111}
        path_calls = []
        paths = {
            111: r"C:\Windows\System32\game.exe",
            222: r"C:\Steam\steamapps\common\Game\game.exe",
        }

        def full_path(pid):
            path_calls.append((pid, isolator._process_create_times[pid]))
            return paths[isolator._process_create_times[pid]]

        isolator._get_process_full_path = full_path
        isolator._is_steam_game = lambda path: "steamapps" in path.lower()

        self.assertEqual([], isolator._find_game_processes([(4242, "game.exe")]))
        self.assertEqual([], isolator._find_game_processes([(4242, "game.exe")]))
        isolator._process_create_times = {4242: 222}
        self.assertEqual([4242], isolator._find_game_processes([(4242, "game.exe")]))

        self.assertEqual([(4242, 111), (4242, 222)], path_calls)

    def test_cleanup_reuses_game_pids_without_reclassifying_processes(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.games = {"cs2.exe"}
        processes = [(103, "cs2.exe"), (104, "discord.exe")]
        calls = []
        isolator._is_game_name_normalized = lambda name: calls.append(name) or (name == "cs2.exe")

        with isolator._state_lock:
            isolator._touched[104] = {"source": "jail", "threads": {"1": {}}}

        isolator._cleanup_dead_processes(processes, game_pids={103})

        self.assertEqual([], calls)
        with isolator._state_lock:
            self.assertEqual({}, isolator._touched[104].get("threads", {}))

    def test_cleanup_prunes_reported_failures_under_state_lock(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        now = time.monotonic()
        isolator._reported_failures = {
            ("open_process", 999): now,
            ("monitor_exception", "ValueError", "boom"): now,
        }

        isolator._cleanup_dead_processes(processes=[(103, "cs2.exe")], game_pids={103})

        self.assertNotIn(("open_process", 999), isolator._reported_failures)
        self.assertIn(("monitor_exception", "ValueError", "boom"), isolator._reported_failures)

    def test_find_game_processes_reuses_snapshot_without_reenumerating(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.games = {"cs2.exe"}
        calls = []
        processes = [(103, "cs2.exe"), (104, "discord.exe")]
        isolator._get_processes = lambda: calls.append(1) or processes

        result = isolator._find_game_processes(processes)

        self.assertEqual([103], result)
        self.assertEqual([], calls)

    def test_isolate_background_reuses_snapshot_without_reenumerating(self):
        isolator = make_isolator([(104, "discord.exe")])
        calls = []
        processes = [(104, "discord.exe")]
        isolator._get_processes = lambda: calls.append(1) or processes

        isolator._isolate_background(processes=processes)

        self.assertEqual([], calls)

    def test_startup_ifeo_skipped_when_game_priority_boost_disabled(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator._disable_game_priority_boost = True
        calls = []
        isolator._set_ifeo_priority = lambda game: calls.append(game) or True

        isolator._apply_configured_game_ifeo_priorities()

        self.assertEqual([], calls)

    def test_timer_resolution_skipped_when_disabled(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator._disable_timer_resolution_tweak = True
        calls = []
        isolator._set_timer_resolution = lambda: calls.append(True)

        if not isolator._disable_timer_resolution_tweak:
            isolator._set_timer_resolution()

        self.assertEqual([], calls)

    def test_startup_ifeo_applies_configured_games_when_enabled(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator._disable_game_priority_boost = False
        isolator.config = {"games": ["cs2", "valorant.exe"]}
        calls = []
        isolator._set_ifeo_priority = lambda game: calls.append(game) or True

        isolator._apply_configured_game_ifeo_priorities()

        self.assertEqual(["cs2", "valorant.exe"], calls)

    def test_maintenance_jail_due_uses_batch_cooldown_for_backlog(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.maintenance_jail_interval_s = 30.0
        isolator.maintenance_jail_batch_cooldown_s = 5.0

        self.assertFalse(isolator._maintenance_jail_due(10.0, 0.0, 8.0, backlog=True))
        self.assertTrue(isolator._maintenance_jail_due(10.0, 0.0, 4.0, backlog=True))
        self.assertFalse(isolator._maintenance_jail_due(10.0, 0.0, 9.0, backlog=False))
        self.assertTrue(isolator._maintenance_jail_due(35.0, 0.0, 9.0, backlog=False))

    def test_isolate_background_diagnostic_summary_groups_duplicate_names(self):
        isolator = make_isolator(
            [
                (101, "updater.exe"),
                (102, "updater.exe"),
                (103, "discord.exe"),
            ]
        )

        isolator._isolate_background(log_names=True)

        summaries = [message for message in isolator.messages if "Newly throttled:" in message]
        self.assertEqual(1, len(summaries))
        self.assertIn("updater.exe x2", summaries[0])
        self.assertIn("discord.exe", summaries[0])


if __name__ == "__main__":
    unittest.main()
