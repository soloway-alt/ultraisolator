import unittest
from unittest.mock import MagicMock

from isolator.app import EsportsIsolatorPro
from isolator.runtime import MonitorCycle

_PROCESSES = [(10, "cs2.exe"), (200, "encoder.exe"), (300, "steam.exe"), (400, "browser.exe")]


def _make_isolator():
    isolator = EsportsIsolatorPro(
        config_path="__no_local_config__.json",
        scan_game_libraries=False,
    )
    isolator.messages = []
    isolator._log = isolator.messages.append
    return isolator


def _make_probalance_isolator():
    isolator = _make_isolator()
    isolator.enable_probalance = True
    isolator.probalance_cpu_threshold_pct = 15
    isolator.probalance_sustain_cycles = 3
    isolator.probalance_restore_cycles = 2
    isolator._jail_process = MagicMock(return_value=True)
    isolator._restore_process = MagicMock(return_value=True)
    return isolator


def _game_cycle(fg_pid=400):
    cycle = MonitorCycle.create(100.0)
    cycle.current_game_pids = {10}
    cycle.game_was_running = True
    cycle.last_fg_pid = fg_pid
    return cycle


class ComputeCpuSamplesTests(unittest.TestCase):
    def test_first_sight_returns_no_samples_and_seeds_baselines(self):
        isolator = _make_isolator()
        isolator._logical_cpu_count = 4
        isolator._process_cpu_times = {200: 10_000_000, 300: 5_000_000}
        cycle = MonitorCycle.create(100.0)

        samples = isolator._compute_cpu_samples(cycle, 100.0)

        self.assertEqual({}, samples)
        self.assertEqual(
            {200: (10_000_000, 100.0), 300: (5_000_000, 100.0)}, cycle.cpu_prev
        )

    def test_second_sample_yields_normalized_percentage(self):
        isolator = _make_isolator()
        isolator._logical_cpu_count = 2
        cycle = MonitorCycle.create(100.0)
        isolator._process_cpu_times = {200: 10_000_000}
        isolator._compute_cpu_samples(cycle, 100.0)

        # +1e7 busy units = 1 CPU-second over dt=2s on 2 logical CPUs:
        # 1 / 2 / 2 * 100 = 25%.
        isolator._process_cpu_times = {200: 20_000_000}
        samples = isolator._compute_cpu_samples(cycle, 102.0)

        self.assertEqual({200}, set(samples))
        self.assertAlmostEqual(25.0, samples[200])
        self.assertEqual({200: (20_000_000, 102.0)}, cycle.cpu_prev)

    def test_percentage_is_clamped_to_zero_and_one_hundred(self):
        isolator = _make_isolator()
        isolator._logical_cpu_count = 1
        cycle = MonitorCycle.create(100.0)
        isolator._process_cpu_times = {200: 50_000_000, 300: 50_000_000}
        isolator._compute_cpu_samples(cycle, 100.0)

        # pid 200 claims 100 CPU-seconds in 1s -> clamp high; pid 300's busy
        # counter went backwards (impossible delta) -> clamp low.
        isolator._process_cpu_times = {200: 1_050_000_000, 300: 40_000_000}
        samples = isolator._compute_cpu_samples(cycle, 101.0)

        self.assertEqual({200: 100.0, 300: 0.0}, samples)

    def test_non_advancing_clock_keeps_the_existing_baseline(self):
        isolator = _make_isolator()
        isolator._logical_cpu_count = 1
        cycle = MonitorCycle.create(100.0)
        isolator._process_cpu_times = {200: 10_000_000}
        isolator._compute_cpu_samples(cycle, 100.0)

        isolator._process_cpu_times = {200: 20_000_000}
        samples = isolator._compute_cpu_samples(cycle, 100.0)

        self.assertEqual({}, samples)
        # The baseline is untouched so the busy delta is not consumed: the
        # next advancing sample still sees the full +2e7 delta.
        self.assertEqual({200: (10_000_000, 100.0)}, cycle.cpu_prev)
        isolator._process_cpu_times = {200: 30_000_000}
        samples = isolator._compute_cpu_samples(cycle, 102.0)
        self.assertEqual({200: 100.0}, samples)

    def test_exited_pids_are_pruned_from_the_baselines(self):
        isolator = _make_isolator()
        isolator._logical_cpu_count = 1
        cycle = MonitorCycle.create(100.0)
        isolator._process_cpu_times = {200: 10_000_000, 300: 10_000_000}
        isolator._compute_cpu_samples(cycle, 100.0)

        isolator._process_cpu_times = {200: 10_000_000}
        isolator._compute_cpu_samples(cycle, 101.0)

        self.assertEqual({200}, set(cycle.cpu_prev))


class ProbalanceStepTests(unittest.TestCase):
    def test_no_jail_before_sustain_cycles(self):
        isolator = _make_probalance_isolator()
        cycle = _game_cycle()

        isolator._advance_probalance(cycle, 100.0, _PROCESSES, {200: 50.0})
        isolator._advance_probalance(cycle, 102.0, _PROCESSES, {200: 50.0})

        isolator._jail_process.assert_not_called()
        self.assertEqual({200: 2}, cycle.probalance_streaks)

    def test_jails_exactly_at_sustain_with_probalance_source(self):
        isolator = _make_probalance_isolator()
        isolator._process_create_times = {200: 777}
        cycle = _game_cycle()

        for step in range(3):
            isolator._advance_probalance(cycle, 100.0 + step, _PROCESSES, {200: 50.0})

        isolator._jail_process.assert_called_once_with(
            200, name="encoder.exe", expected_create_time=777, source="probalance"
        )
        self.assertEqual({200}, cycle.probalance_jailed)
        self.assertNotIn(200, cycle.probalance_streaks)
        self.assertTrue(
            any("[PROBALANCE] Restrained encoder.exe (pid=200)" in message for message in isolator.messages)
        )

    def test_streak_resets_when_sample_dips_below_threshold(self):
        isolator = _make_probalance_isolator()
        cycle = _game_cycle()

        isolator._advance_probalance(cycle, 100.0, _PROCESSES, {200: 50.0})
        isolator._advance_probalance(cycle, 101.0, _PROCESSES, {200: 50.0})
        isolator._advance_probalance(cycle, 102.0, _PROCESSES, {200: 5.0})
        isolator._advance_probalance(cycle, 103.0, _PROCESSES, {200: 50.0})
        isolator._advance_probalance(cycle, 104.0, _PROCESSES, {200: 50.0})

        isolator._jail_process.assert_not_called()
        self.assertEqual({200: 2}, cycle.probalance_streaks)

    def test_restores_after_consecutive_calm_cycles(self):
        isolator = _make_probalance_isolator()
        cycle = _game_cycle()
        cycle.probalance_jailed = {200}

        isolator._advance_probalance(cycle, 100.0, _PROCESSES, {200: 5.0})
        isolator._restore_process.assert_not_called()
        isolator._advance_probalance(cycle, 101.0, _PROCESSES, {200: 5.0})

        isolator._restore_process.assert_called_once_with(200)
        self.assertEqual(set(), cycle.probalance_jailed)
        self.assertNotIn(200, cycle.probalance_calm_streaks)
        self.assertTrue(
            any("[PROBALANCE] Released encoder.exe (pid=200)" in message for message in isolator.messages)
        )

    def test_calm_streak_resets_when_load_spikes_again(self):
        isolator = _make_probalance_isolator()
        cycle = _game_cycle()
        cycle.probalance_jailed = {200}

        isolator._advance_probalance(cycle, 100.0, _PROCESSES, {200: 5.0})
        isolator._advance_probalance(cycle, 101.0, _PROCESSES, {200: 60.0})
        isolator._advance_probalance(cycle, 102.0, _PROCESSES, {200: 5.0})

        isolator._restore_process.assert_not_called()
        self.assertEqual({200}, cycle.probalance_jailed)

        isolator._advance_probalance(cycle, 103.0, _PROCESSES, {200: 5.0})
        isolator._restore_process.assert_called_once_with(200)

    def test_never_jails_game_foreground_or_launcher_pids(self):
        isolator = _make_probalance_isolator()
        cycle = _game_cycle(fg_pid=400)

        for step in range(6):
            isolator._advance_probalance(
                cycle, 100.0 + step, _PROCESSES, {10: 95.0, 300: 95.0, 400: 95.0}
            )

        isolator._jail_process.assert_not_called()
        self.assertEqual({}, cycle.probalance_streaks)

    def test_skips_pids_already_touched_by_any_source(self):
        isolator = _make_probalance_isolator()
        with isolator._state_lock:
            isolator._touched[200] = {"name": "encoder.exe", "source": "foreground", "gen": 1}
        cycle = _game_cycle()

        for step in range(6):
            isolator._advance_probalance(cycle, 100.0 + step, _PROCESSES, {200: 95.0})

        isolator._jail_process.assert_not_called()

    def test_denied_jail_is_not_marked_restrained(self):
        isolator = _make_probalance_isolator()
        isolator._jail_process = MagicMock(return_value=None)
        cycle = _game_cycle()

        for step in range(3):
            isolator._advance_probalance(cycle, 100.0 + step, _PROCESSES, {200: 50.0})

        isolator._jail_process.assert_called_once()
        self.assertEqual(set(), cycle.probalance_jailed)
        # The streak was consumed by the attempt: re-restraint needs a fresh
        # sustained run instead of hammering the denied process every cycle.
        self.assertNotIn(200, cycle.probalance_streaks)

    def test_disabled_flag_is_a_complete_noop(self):
        isolator = _make_probalance_isolator()
        isolator.enable_probalance = False
        cycle = _game_cycle()

        for step in range(6):
            isolator._advance_probalance(cycle, 100.0 + step, _PROCESSES, {200: 95.0})

        isolator._jail_process.assert_not_called()
        self.assertEqual({}, cycle.probalance_streaks)

    def test_waits_for_the_initial_library_scan(self):
        isolator = _make_probalance_isolator()
        isolator._library_scan_ready.clear()
        cycle = _game_cycle()

        for step in range(6):
            isolator._advance_probalance(cycle, 100.0 + step, _PROCESSES, {200: 95.0})

        isolator._jail_process.assert_not_called()

    def test_bookkeeping_cleared_outside_game_mode_without_restores(self):
        isolator = _make_probalance_isolator()
        cycle = _game_cycle()
        cycle.probalance_streaks = {500: 2}
        cycle.probalance_calm_streaks = {200: 1}
        cycle.probalance_jailed = {200}
        cycle.current_game_pids = set()

        isolator._advance_probalance(cycle, 100.0, _PROCESSES, {})

        # The game-exit restore-all owns the actual reversal; the step only
        # forgets its bookkeeping.
        isolator._restore_process.assert_not_called()
        self.assertEqual({}, cycle.probalance_streaks)
        self.assertEqual({}, cycle.probalance_calm_streaks)
        self.assertEqual(set(), cycle.probalance_jailed)

    def test_bookkeeping_pruned_for_exited_pids(self):
        isolator = _make_probalance_isolator()
        cycle = _game_cycle()
        cycle.probalance_streaks = {500: 2}
        cycle.probalance_calm_streaks = {600: 1}
        cycle.probalance_jailed = {600}

        isolator._advance_probalance(cycle, 100.0, _PROCESSES, {200: 5.0})

        self.assertEqual({}, cycle.probalance_streaks)
        self.assertEqual({}, cycle.probalance_calm_streaks)
        self.assertEqual(set(), cycle.probalance_jailed)


class JailSourceThreadingTests(unittest.TestCase):
    def test_remember_process_state_records_the_probalance_source(self):
        isolator = _make_isolator()
        isolator._get_process_create_time = lambda handle: 123
        isolator._query_process_state = lambda handle: {"priority_class": 32}

        isolator._remember_process_state(4242, 99, "encoder.exe", source="probalance")

        entry = isolator._touched[4242]
        self.assertEqual("probalance", entry["source"])
        self.assertEqual("encoder.exe", entry["name"])

    def test_record_jail_states_persists_probalance_entries(self):
        isolator = _make_isolator()
        with isolator._state_lock:
            isolator._touched[101] = {
                "name": "encoder.exe",
                "create_time": 123,
                "state": {"priority_class": 32},
                "threads": {},
                "source": "probalance",
                "gen": 1,
            }
            isolator._touched[102] = {
                "name": "focused.exe",
                "create_time": 456,
                "state": {},
                "threads": {},
                "source": "foreground",
                "gen": 2,
            }
        saved = []
        isolator._load_jail_state = lambda: {"pids": {}}
        isolator._save_jail_state = lambda state: saved.append(state) or True

        isolator._record_jail_states([101, 102])

        self.assertEqual(1, len(saved))
        self.assertEqual({"101"}, set(saved[0]["pids"]))
        self.assertEqual("probalance", saved[0]["pids"]["101"]["source"])


if __name__ == "__main__":
    unittest.main()
