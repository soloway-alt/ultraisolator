import unittest
from unittest import mock

from isolator.app import EsportsIsolatorPro


class CpuSetApplicationTests(unittest.TestCase):
    def test_cpu_sets_success_does_not_apply_affinity_fallback(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._cpu_sets_by_id = {
            1: {"group": 0, "logical_index": 1},
            2: {"group": 0, "logical_index": 2},
        }
        cpu_set_calls = []
        affinity_calls = []
        isolator._is_wow64_process = lambda handle: False
        isolator._set_process_default_cpu_sets = lambda handle, ids: cpu_set_calls.append((handle, list(ids))) or True
        isolator._apply_process_affinity_fallback = lambda handle, ids: affinity_calls.append((handle, list(ids))) or True

        self.assertTrue(isolator._apply_process_cpu_sets(99, [1, 2]))

        self.assertEqual([(99, [1, 2])], cpu_set_calls)
        self.assertEqual([], affinity_calls)

    def test_cpu_sets_failure_uses_affinity_as_fallback(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._cpu_sets_by_id = {1: {"group": 0, "logical_index": 1}}
        cpu_set_calls = []
        affinity_calls = []
        isolator._is_wow64_process = lambda handle: False
        isolator._set_process_default_cpu_sets = lambda handle, ids: cpu_set_calls.append((handle, list(ids))) or False
        isolator._apply_process_affinity_fallback = lambda handle, ids: affinity_calls.append((handle, list(ids))) or True

        self.assertTrue(isolator._apply_process_cpu_sets(99, [1]))

        self.assertEqual([(99, [1])], cpu_set_calls)
        self.assertEqual([(99, [1])], affinity_calls)

    def test_affinity_fallback_uses_group_relative_mask_for_high_logical_indices(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        # Second processor group on a >64-logical-CPU machine: system-wide
        # logical indices 64..65 must map to group-relative bits 0..1.
        isolator._cpu_sets_by_id = {
            640: {"group": 1, "logical_index": 64},
            641: {"group": 1, "logical_index": 65},
        }

        with mock.patch("isolator.topology.kernel32.SetProcessAffinityMask", return_value=1) as set_affinity:
            self.assertTrue(isolator._apply_process_affinity_fallback(99, [640, 641]))

        (_handle, mask_arg) = set_affinity.call_args[0]
        self.assertEqual(0b11, mask_arg.value)

    def test_clearing_cpu_sets_does_not_reset_legacy_affinity_mask(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        cpu_set_calls = []
        isolator._set_process_default_cpu_sets = lambda handle, ids: cpu_set_calls.append((handle, list(ids))) or True

        with mock.patch("isolator.topology.kernel32.SetProcessAffinityMask") as set_affinity:
            self.assertTrue(isolator._apply_process_cpu_sets(99, [], reset_affinity_mask=True))

        self.assertEqual([(99, [])], cpu_set_calls)
        set_affinity.assert_not_called()


class CpuPartitionPolicyTests(unittest.TestCase):
    def test_four_core_homogeneous_keeps_three_game_cores_and_no_housekeeping(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.housekeeping_core_count = 1
        isolator._topology = {
            "cpu_sets": [],
            "llc_groups": [],
            "heterogeneous_efficiency": False,
            "multi_llc": False,
            "core_groups": [
                {"key": (0, index), "group": 0, "core_index": index, "llc_key": (0, 0), "cpu_set_ids": [index]}
                for index in range(4)
            ],
        }

        partitions = isolator._select_cpu_partitions()

        self.assertEqual([0, 1, 2], partitions["game"])
        self.assertEqual([3], partitions["background"])
        self.assertEqual([], partitions["housekeeping"])

    def test_equal_size_llc_groups_use_deterministic_low_group_tiebreak_and_log_selection(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._enumerate_cpu_sets = lambda: [
            {"id": 10, "group": 1, "logical_index": 0, "core_index": 0, "llc_index": 0, "efficiency_class": 0, "parked": False, "allocated": False, "allocated_to_target_process": False, "realtime": False},
            {"id": 11, "group": 1, "logical_index": 1, "core_index": 1, "llc_index": 0, "efficiency_class": 0, "parked": False, "allocated": False, "allocated_to_target_process": False, "realtime": False},
            {"id": 1, "group": 0, "logical_index": 0, "core_index": 0, "llc_index": 0, "efficiency_class": 0, "parked": False, "allocated": False, "allocated_to_target_process": False, "realtime": False},
            {"id": 2, "group": 0, "logical_index": 1, "core_index": 1, "llc_index": 0, "efficiency_class": 0, "parked": False, "allocated": False, "allocated_to_target_process": False, "realtime": False},
        ]
        isolator._enumerate_cache_relationships = lambda: [
            {"cache_size": 32 * 1024 * 1024, "group_masks": [{"group": 1, "mask": 0b11}]},
            {"cache_size": 32 * 1024 * 1024, "group_masks": [{"group": 0, "mask": 0b11}]},
        ]
        messages = []
        isolator._log_once = lambda key, message: messages.append((key, message))

        topology = isolator._build_topology_map()
        partitions = isolator._select_cpu_partitions()

        self.assertEqual((0, 0), topology["llc_groups"][0]["key"])
        self.assertEqual([1, 2], partitions["game"])
        self.assertTrue(any("group=0" in message and "llc=0" in message for _, message in messages))


class RuntimeTopologyRefreshTests(unittest.TestCase):
    def test_monitor_refreshes_topology_on_game_entry_and_after_power_switch(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )

        class OneLoopStop:
            def __init__(self):
                self.waited = False

            def is_set(self):
                return self.waited

            def wait(self, _interval):
                self.waited = True
                return True

        events = []
        isolator._stop_event = OneLoopStop()
        isolator._last_topology_refresh = 10**12
        isolator.games = {"cs2.exe"}
        isolator._get_processes = lambda: [(10, "cs2.exe")]
        isolator._find_game_processes = lambda processes: [10]
        isolator._optimize_game = lambda pid: events.append(("optimize", pid))
        isolator._refresh_topology = lambda reason: events.append(("refresh", reason))
        isolator._run_background_jail = lambda initial, processes: events.append(("jail", initial)) or {}
        isolator._set_preferred_power_scheme = lambda: events.append(("power", None)) or setattr(isolator, "_power_plan_active", True) or True
        isolator._cleanup_dead_processes = lambda *args, **kwargs: None

        with mock.patch("isolator.runtime.user32.GetForegroundWindow", return_value=0), \
                mock.patch("isolator.runtime.gc.disable"), \
                mock.patch("isolator.runtime.gc.collect"):
            isolator._monitor_loop()

        self.assertLess(events.index(("refresh", "game_mode_entry")), events.index(("jail", True)))
        self.assertLess(events.index(("power", None)), events.index(("refresh", "power_scheme_switch")))


class InitDataclassTests(unittest.TestCase):
    def test_init_exposes_grouped_config_state_and_win32_scratch_with_legacy_aliases(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )

        self.assertIs(isolator.games, isolator._parsed_config.games)
        self.assertIs(isolator._touched, isolator._runtime_state.touched)
        self.assertIs(isolator._ifeo_original, isolator._runtime_state.ifeo_original)
        self.assertIs(isolator._fg_pid_dword, isolator._win32_scratch.fg_pid_dword)
        self.assertIs(isolator._spi_struct_ptr, isolator._win32_scratch.spi_struct_ptr)


if __name__ == "__main__":
    unittest.main()
