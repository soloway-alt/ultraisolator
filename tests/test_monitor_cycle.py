import unittest
from unittest import mock
from unittest.mock import MagicMock

from isolator.app import EsportsIsolatorPro
from isolator.runtime import MonitorCycle


def _make_isolator():
    isolator = EsportsIsolatorPro(
        config_path="__no_local_config__.json",
        scan_game_libraries=False,
    )
    isolator.messages = []
    isolator._log = isolator.messages.append
    isolator.enable_background_jailing = True
    isolator.game_close_debounce_s = 3.0
    isolator.game_exit_restore_delay_s = 4.0
    isolator._refresh_topology = MagicMock()
    isolator._run_background_jail = MagicMock(return_value={"touched": 0, "deferred": 0})
    isolator._cleanup_dead_processes = MagicMock()
    isolator._set_preferred_power_scheme = MagicMock(return_value=False)
    isolator._restore_power_scheme = MagicMock()
    isolator._restore_all_processes = MagicMock()
    isolator._restore_process = MagicMock(return_value=True)
    isolator._optimize_game_with_state = MagicMock(return_value="applied")
    isolator._find_game_process_entries = lambda processes: {
        int(pid): name for pid, name in processes if name == "cs2.exe"
    }
    return isolator


def _enter_game_mode(isolator, cycle, now=100.0):
    isolator._advance_game_tracking(cycle, now, [(10, "cs2.exe")])
    isolator._advance_game_mode(cycle, now, [(10, "cs2.exe")])


class GameTrackingStepTests(unittest.TestCase):
    def test_new_game_is_optimized_and_tracked(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)

        isolator._advance_game_tracking(cycle, 100.0, [(10, "cs2.exe"), (99, "other.exe")])

        isolator._optimize_game_with_state.assert_called_once_with(
            10, "cs2.exe", classified_as_game=True
        )
        self.assertEqual({10}, cycle.current_game_pids)
        self.assertEqual({10}, cycle.active_games)
        self.assertEqual({10}, cycle.last_known_game_pids)

    def test_confirmed_close_restores_the_game_process(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)
        isolator._advance_game_tracking(cycle, 100.0, [(10, "cs2.exe")])
        # First miss starts the debounce; a miss past the window confirms it.
        isolator._advance_game_tracking(cycle, 101.0, [(99, "other.exe")])
        isolator._restore_process.assert_not_called()

        isolator._advance_game_tracking(cycle, 105.0, [(99, "other.exe")])

        isolator._restore_process.assert_called_once_with(10)
        self.assertEqual(set(), cycle.active_games)

    def test_due_cleanup_runs_inline_and_marks_the_cycle(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(0.0)
        cycle.cleanup_due = True

        isolator._advance_game_tracking(cycle, 100.0, [(99, "other.exe")])

        isolator._cleanup_dead_processes.assert_called_once()
        self.assertTrue(cycle.cleanup_ran)
        self.assertEqual(100.0, cycle.last_cleanup)


class GameModeStepTests(unittest.TestCase):
    def test_entry_transition_refreshes_topology_and_runs_initial_jail(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)

        _enter_game_mode(isolator, cycle)

        self.assertTrue(cycle.game_was_running)
        self.assertTrue(cycle.game_mode_entered)
        isolator._refresh_topology.assert_called_once_with("game_mode_entry")
        isolator._run_background_jail.assert_called_once_with(
            initial=True, processes=[(10, "cs2.exe")]
        )
        # Entry resets the GC sweep timers to "now".
        self.assertEqual(100.0, cycle.last_gc_sweep)
        self.assertEqual(100.0, cycle.last_gc_gen0_sweep)

    def test_exit_waits_for_restore_delay_then_restores_everything(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)
        _enter_game_mode(isolator, cycle)
        isolator._power_plan_active = True

        # Game gone: debounce confirms at 105, exit delay (4s) not yet elapsed.
        isolator._advance_game_tracking(cycle, 101.0, [])
        isolator._advance_game_mode(cycle, 101.0, [])
        isolator._advance_game_tracking(cycle, 105.0, [])
        isolator._advance_game_mode(cycle, 105.0, [])
        isolator._restore_all_processes.assert_not_called()
        self.assertTrue(cycle.game_was_running)

        isolator._advance_game_tracking(cycle, 110.0, [])
        isolator._advance_game_mode(cycle, 110.0, [])

        isolator._restore_all_processes.assert_called_once()
        isolator._restore_power_scheme.assert_called_once()
        self.assertFalse(cycle.game_was_running)
        self.assertFalse(cycle.power_scheme_attempted)

    def test_pending_close_holds_the_exit_timer(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)
        _enter_game_mode(isolator, cycle)

        # One miss: the pid is pending-closed (debounce), so the exit timer
        # must not start yet.
        isolator._advance_game_tracking(cycle, 101.0, [])
        isolator._advance_game_mode(cycle, 101.0, [])

        self.assertEqual(0.0, cycle.last_game_exit_time)
        isolator._restore_all_processes.assert_not_called()


class MaintenanceJailStepTests(unittest.TestCase):
    def _prime_game_mode(self, isolator, cycle):
        _enter_game_mode(isolator, cycle)
        isolator._run_background_jail.reset_mock()
        cycle.game_mode_entered = False

    def test_skipped_on_the_entry_cycle(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)
        _enter_game_mode(isolator, cycle)

        isolator._advance_maintenance_jail(cycle, 100.0, [(10, "cs2.exe")])

        # Only the initial jail from the entry transition; no maintenance pass.
        isolator._run_background_jail.assert_called_once_with(
            initial=True, processes=[(10, "cs2.exe")]
        )

    def test_runs_when_interval_elapses_and_tracks_idle_streak(self):
        isolator = _make_isolator()
        isolator.maintenance_jail_interval_s = 30.0
        isolator.maintenance_jail_batch_cooldown_s = 5.0
        isolator.maintenance_skip_after_quiet_cycles = 2
        cycle = MonitorCycle.create(100.0)
        self._prime_game_mode(isolator, cycle)

        isolator._advance_maintenance_jail(cycle, 120.0, [])
        isolator._run_background_jail.assert_not_called()

        isolator._advance_maintenance_jail(cycle, 131.0, [])
        isolator._run_background_jail.assert_called_once_with(initial=False, processes=[])
        self.assertEqual(1, cycle.maintenance_idle_streak)

    def test_quiet_streak_skips_the_batch(self):
        isolator = _make_isolator()
        isolator.maintenance_jail_interval_s = 30.0
        isolator.maintenance_skip_after_quiet_cycles = 1
        cycle = MonitorCycle.create(100.0)
        self._prime_game_mode(isolator, cycle)
        cycle.maintenance_idle_streak = 1

        isolator._advance_maintenance_jail(cycle, 131.0, [])

        isolator._run_background_jail.assert_not_called()
        # The skip still advances the interval clock.
        self.assertEqual(131.0, cycle.last_background_jail)

    def test_noop_outside_game_mode(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)

        isolator._advance_maintenance_jail(cycle, 200.0, [])

        isolator._run_background_jail.assert_not_called()


class GcPolicyStepTests(unittest.TestCase):
    def test_disables_gc_once_in_game_mode_and_sweeps_on_schedule(self):
        isolator = _make_isolator()
        isolator.gc_full_collect_interval_s = 600.0
        cycle = MonitorCycle.create(100.0)
        _enter_game_mode(isolator, cycle)

        with mock.patch("isolator.runtime.gc.disable") as gc_disable, \
                mock.patch("isolator.runtime.gc.collect") as gc_collect:
            isolator._advance_gc_policy(cycle, 100.0)
            gc_disable.assert_called_once()
            self.assertTrue(cycle.gc_disabled)

            # gen0 sweep after 30s.
            isolator._advance_gc_policy(cycle, 131.0)
            gc_collect.assert_called_once_with(0)

            # Full sweep after the configured interval.
            isolator._advance_gc_policy(cycle, 100.0 + 601.0)
            gc_collect.assert_called_with()

    def test_noop_outside_game_mode(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)

        with mock.patch("isolator.runtime.gc.disable") as gc_disable:
            isolator._advance_gc_policy(cycle, 100.0)

        gc_disable.assert_not_called()


class PowerStepTests(unittest.TestCase):
    def test_switches_once_per_game_session(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)
        _enter_game_mode(isolator, cycle)
        isolator._set_preferred_power_scheme = MagicMock(
            side_effect=lambda: setattr(isolator, "_power_plan_active", True) or True
        )

        isolator._advance_power(cycle, 100.0)
        self.assertTrue(cycle.power_scheme_attempted)
        isolator._refresh_topology.assert_any_call("power_scheme_switch")

        # A second cycle must not retry the switch.
        isolator._set_preferred_power_scheme = MagicMock()
        isolator._advance_power(cycle, 102.0)
        isolator._set_preferred_power_scheme.assert_not_called()

    def test_noop_outside_game_mode(self):
        isolator = _make_isolator()
        cycle = MonitorCycle.create(100.0)

        isolator._advance_power(cycle, 100.0)

        isolator._set_preferred_power_scheme.assert_not_called()


class ForegroundStepTests(unittest.TestCase):
    def test_debounced_transition_invokes_handler_once(self):
        isolator = _make_isolator()
        isolator._foreground_transition_debounce_s = 0.5
        isolator._last_fg_transition_time = 0.0
        calls = []
        isolator._handle_foreground_transition = lambda *args: calls.append(args)
        cycle = MonitorCycle.create(100.0)

        fg_value = {"value": 20}

        def get_fg_pid(_hwnd, byref_arg):
            isolator._fg_pid_dword.value = fg_value["value"]
            return True

        with mock.patch("isolator.runtime.user32.GetForegroundWindow", return_value=123), \
                mock.patch("isolator.runtime.user32.GetWindowThreadProcessId", side_effect=get_fg_pid):
            isolator._advance_foreground(cycle, 100.0)
            # Same pid again: no second transition.
            isolator._advance_foreground(cycle, 101.0)

        self.assertEqual([(0, 20, False)], calls)
        self.assertEqual(20, cycle.last_fg_pid)


if __name__ == "__main__":
    unittest.main()
