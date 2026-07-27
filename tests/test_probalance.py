import unittest

from isolator.app import EsportsIsolatorPro
from isolator.runtime import MonitorCycle


def _make_isolator():
    isolator = EsportsIsolatorPro(
        config_path="__no_local_config__.json",
        scan_game_libraries=False,
    )
    isolator.messages = []
    isolator._log = isolator.messages.append
    return isolator


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


if __name__ == "__main__":
    unittest.main()
