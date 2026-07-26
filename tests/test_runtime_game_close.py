import unittest
from unittest import mock

from isolator.app import EsportsIsolatorPro


class GameCloseDebounceTests(unittest.TestCase):
    def test_single_miss_does_not_confirm_close(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.game_close_debounce_s = 3.0

        new_games, confirmed, active, pending = isolator._process_game_pid_transitions(
            active_games={12328},
            current_game_pids=set(),
            pending_closed={},
            now=100.0,
        )

        self.assertEqual(set(), new_games)
        self.assertEqual([], confirmed)
        self.assertEqual({12328}, active)
        self.assertEqual({12328: 100.0}, pending)

    def test_miss_long_enough_confirms_close(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.game_close_debounce_s = 3.0

        _, _, active, pending = isolator._process_game_pid_transitions(
            {12328}, set(), {}, 100.0
        )
        new_games, confirmed, active, pending = isolator._process_game_pid_transitions(
            active, set(), pending, 104.0
        )

        self.assertEqual(set(), new_games)
        self.assertEqual([12328], confirmed)
        self.assertEqual(set(), active)
        self.assertEqual({}, pending)

    def test_reappear_before_debounce_cancels_pending(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        isolator.game_close_debounce_s = 3.0

        _, _, active, pending = isolator._process_game_pid_transitions(
            {12328}, set(), {}, 100.0
        )
        new_games, confirmed, active, pending = isolator._process_game_pid_transitions(
            active, {12328}, pending, 101.0
        )

        self.assertEqual(set(), new_games)
        self.assertEqual([], confirmed)
        self.assertEqual({12328}, active)
        self.assertEqual({}, pending)


class _FakeClock:
    def __init__(self, start=0.0):
        self.value = start

    def __call__(self):
        return self.value


class _ScriptedStopEvent:
    """Run `max_cycles` monitor-loop bodies; each wait() advances the fake clock."""

    def __init__(self, clock, max_cycles):
        self.clock = clock
        self.max_cycles = max_cycles
        self.cycles = 0

    def is_set(self):
        return self.cycles >= self.max_cycles

    def wait(self, interval):
        self.clock.value += interval
        self.cycles += 1
        return self.cycles >= self.max_cycles


class MonitorLoopGameCloseTests(unittest.TestCase):
    def _make_isolator(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.messages = []
        isolator._log = isolator.messages.append
        isolator.auto_detect_steam = False
        isolator.auto_detect_epic = False
        isolator.enable_background_jailing = False
        isolator.poll_interval_active_s = 2.0
        isolator.poll_interval_idle_s = 2.0
        isolator.game_close_debounce_s = 3.0
        isolator.game_exit_restore_delay_s = 4.0
        isolator._last_topology_refresh = 10**12
        isolator._refresh_topology = lambda reason: None
        isolator._run_background_jail = lambda initial, processes: {}
        isolator._cleanup_dead_processes = lambda *args, **kwargs: None
        isolator._set_preferred_power_scheme = lambda: False
        isolator._restore_power_scheme = lambda: None
        isolator._find_game_process_entries = lambda processes: {
            int(pid): name for pid, name in processes if name == "cs2.exe"
        }
        return isolator

    def _run_monitor_loop(self, isolator, clock):
        with mock.patch("isolator.runtime.time.monotonic", clock), \
                mock.patch("isolator.runtime.user32.GetForegroundWindow", return_value=0), \
                mock.patch("isolator.runtime.gc.disable"), \
                mock.patch("isolator.runtime.gc.enable"), \
                mock.patch("isolator.runtime.gc.collect"):
            isolator._monitor_loop()

    def test_game_close_debounces_then_restores_after_exit_delay(self):
        isolator = self._make_isolator()
        clock = _FakeClock()
        # 7 cycles at 2s: game seen at t=0, missing from t=2. Debounce (3s)
        # confirms the close at t=6; the exit-restore delay (4s) elapses at t=12.
        isolator._stop_event = _ScriptedStopEvent(clock, max_cycles=7)
        events = []
        isolator._get_processes = lambda: (
            [(10, "cs2.exe"), (99, "other.exe")] if clock.value == 0.0 else [(99, "other.exe")]
        )
        isolator._optimize_game_with_state = (
            lambda pid, name=None, classified_as_game=False: events.append(
                ("optimize", pid, clock.value)
            )
            or "tuned"
        )
        isolator._restore_process = lambda pid: events.append(("restore", pid, clock.value)) or True
        isolator._restore_all_processes = lambda: events.append(("restore_all", clock.value))

        self._run_monitor_loop(isolator, clock)

        self.assertEqual([("optimize", 10, 0.0)], [e for e in events if e[0] == "optimize"])
        # Nothing restored within the debounce window (t=2, t=4); the per-game
        # restore fires only once the debounce has elapsed.
        self.assertEqual([("restore", 10, 6.0)], [e for e in events if e[0] == "restore"])
        # Full restore waits a further game_exit_restore_delay_s after the exit.
        self.assertEqual([("restore_all", 12.0)], [e for e in events if e[0] == "restore_all"])

    def test_empty_snapshot_does_not_trigger_game_close_or_restore(self):
        isolator = self._make_isolator()
        clock = _FakeClock()
        isolator._stop_event = _ScriptedStopEvent(clock, max_cycles=4)
        events = []
        isolator._get_processes = lambda: (
            [(10, "cs2.exe"), (99, "other.exe")] if clock.value == 0.0 else []
        )
        isolator._optimize_game_with_state = (
            lambda pid, name=None, classified_as_game=False: "tuned"
        )
        isolator._restore_process = lambda pid: events.append(("restore", pid)) or True
        isolator._restore_all_processes = lambda: events.append(("restore_all",))

        self._run_monitor_loop(isolator, clock)

        # Empty enumerations (t=2..6) must be treated as failures, not as
        # "every game exited": no restore paths run and the observation sticks.
        self.assertEqual([], events)
        self.assertIn(10, isolator._active_games)
        self.assertTrue(
            any("keeping the last game observation" in line for line in isolator.messages)
        )


class GameRestoreVacTests(unittest.TestCase):
    def test_restore_game_affinity_denied_logs_info(self):
        isolator = EsportsIsolatorPro(scan_game_libraries=False)
        messages = []
        isolator._log_once = lambda key, message: messages.append(message)

        with mock.patch("isolator.tuning.ctypes.get_last_error", return_value=5):
            isolator._log_restore_access_issue(12328, "cs2.exe", "optimize_game", "SetProcessAffinityMask")

        self.assertEqual(1, len(messages))
        self.assertTrue(messages[0].startswith("[INFO]"))
        self.assertIn("VAC/anti-cheat blocked", messages[0])


if __name__ == "__main__":
    unittest.main()
