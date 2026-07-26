import contextlib
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from isolator.app import EsportsIsolatorPro


@contextlib.contextmanager
def _temp_jail_state_path():
    """Point jail-state I/O at a tempdir with the ACL layer stubbed out.

    Keeps the suite away from the machine's real recovery state and from the
    powershell/icacls subprocess chain behind the protected-state helpers.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "jail_state.json")
        with patch("isolator.recovery.JAIL_STATE_PATH", path), patch(
            "isolator.recovery.is_protected_state_path_safe", return_value=True
        ), patch(
            "isolator.protected_state.apply_protected_state_acl", return_value=True
        ), patch(
            "isolator.protected_state.is_protected_state_path_safe", return_value=True
        ):
            yield path


class ShutdownFlowTests(unittest.TestCase):
    def _make_isolator(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.messages = []
        isolator._log = isolator.messages.append
        isolator._monitor_thread = None
        isolator._mutex_handle = None
        isolator._close_log_file = MagicMock()
        return isolator

    def test_shutdown_runs_all_steps_once(self):
        isolator = self._make_isolator()
        isolator._restore_power_scheme = MagicMock()
        isolator._restore_timer_resolution = MagicMock()
        isolator._restore_ifeo_priorities = MagicMock()
        isolator._restore_all_processes = MagicMock()
        isolator._restore_system_critical = MagicMock()

        isolator.shutdown()
        isolator.shutdown()

        isolator._restore_power_scheme.assert_called_once()
        isolator._restore_timer_resolution.assert_called_once()
        isolator._restore_ifeo_priorities.assert_called_once()
        isolator._restore_all_processes.assert_called_once()
        isolator._restore_system_critical.assert_called_once()
        self.assertTrue(any("Step 8/8" in line for line in isolator.messages))
        self.assertTrue(any("All state restored" in line for line in isolator.messages))
        isolator._close_log_file.assert_called_once()

    def test_shutdown_closes_log_file_after_final_messages(self):
        isolator = self._make_isolator()
        isolator._restore_power_scheme = MagicMock()
        isolator._restore_timer_resolution = MagicMock()
        isolator._restore_ifeo_priorities = MagicMock()
        isolator._restore_all_processes = MagicMock()
        isolator._restore_system_critical = MagicMock()
        order = []

        def log(msg):
            order.append(("log", msg))

        def close_log():
            order.append(("close",))

        isolator._log = log
        isolator._close_log_file = close_log

        isolator.shutdown()

        close_index = next(i for i, item in enumerate(order) if item[0] == "close")
        restored_index = next(
            i for i, item in enumerate(order) if item[0] == "log" and "All state restored" in item[1]
        )
        self.assertLess(restored_index, close_index)

    def test_shutdown_waits_for_active_mutation_before_restore_steps(self):
        isolator = self._make_isolator()
        restore_started = threading.Event()
        finished = threading.Event()
        isolator._restore_power_scheme = MagicMock(side_effect=restore_started.set)
        isolator._restore_timer_resolution = MagicMock()
        isolator._restore_ifeo_priorities = MagicMock()
        isolator._restore_all_processes = MagicMock()
        isolator._restore_system_critical = MagicMock()

        with isolator._state_lock:
            isolator._active_mutations = 1

        thread = threading.Thread(
            target=lambda: (isolator.shutdown(fast=True), finished.set())
        )
        thread.start()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            with isolator._state_lock:
                if isolator._shutting_down:
                    break
            time.sleep(0.001)
        else:
            self.fail("shutdown did not enter shutting_down state")
        self.assertFalse(restore_started.wait(0.05))
        self.assertFalse(isolator._begin_process_mutation())

        isolator._end_process_mutation()
        self.assertTrue(finished.wait(1.0))
        thread.join(timeout=1.0)
        isolator._restore_power_scheme.assert_called_once()
        isolator._restore_all_processes.assert_called_once()

    def test_restore_all_keeps_jail_state_file_when_any_restore_fails(self):
        isolator = self._make_isolator()
        with isolator._state_lock:
            isolator._touched[101] = {"gen": 1, "source": "jail"}
            isolator._touched[102] = {"gen": 1, "source": "jail"}

        def restore_process(pid, deferred_jail_removals=None):
            with isolator._state_lock:
                isolator._touched.pop(pid, None)
            if pid == 101 and deferred_jail_removals is not None:
                deferred_jail_removals.append(pid)
            return pid == 101

        isolator._restore_process = restore_process
        isolator._remove_jail_state_file = MagicMock()
        isolator._remove_jail_states = MagicMock()

        isolator._restore_all_processes()

        isolator._remove_jail_state_file.assert_not_called()
        isolator._remove_jail_states.assert_called_once_with([101])

    def test_restore_all_removes_jail_state_file_when_every_restore_succeeds(self):
        isolator = self._make_isolator()
        with isolator._state_lock:
            isolator._touched[101] = {"gen": 1, "source": "jail"}
            isolator._touched[102] = {"gen": 1, "source": "jail"}

        def restore_process(pid, deferred_jail_removals=None):
            with isolator._state_lock:
                isolator._touched.pop(pid, None)
            if deferred_jail_removals is not None:
                deferred_jail_removals.append(pid)
            return True

        isolator._restore_process = restore_process
        isolator._remove_jail_state_file = MagicMock()
        isolator._remove_jail_states = MagicMock()

        isolator._restore_all_processes()

        isolator._remove_jail_state_file.assert_called_once()
        isolator._remove_jail_states.assert_not_called()

    def test_restore_all_exception_pop_respects_generation_guard(self):
        isolator = self._make_isolator()
        with isolator._state_lock:
            isolator._touched[4242] = {"gen": 1, "source": "jail"}

        def restore_process(pid, deferred_jail_removals=None):
            with isolator._state_lock:
                isolator._touched[pid] = {"gen": 2, "source": "jail"}
            raise RuntimeError("restore failed")

        isolator._restore_process = restore_process
        isolator._remove_jail_state_file = MagicMock()

        isolator._restore_all_processes()

        self.assertEqual(2, isolator._touched[4242]["gen"])

    def test_restore_process_removes_jail_state_after_releasing_state_lock(self):
        isolator = self._make_isolator()
        with isolator._state_lock:
            isolator._touched[4242] = {
                "name": "discord.exe",
                "create_time": 123,
                "state": {},
                "threads": {},
                "source": "jail",
                "gen": 7,
            }

        removed = []

        def remove_jail_state(pid):
            acquired = isolator._state_lock.acquire(blocking=False)
            try:
                self.assertTrue(acquired)
                removed.append(pid)
            finally:
                if acquired:
                    isolator._state_lock.release()

        isolator._open_process = lambda *args, **kwargs: 99
        isolator._get_process_create_time = lambda handle: 123
        isolator._restore_threads_for_process = MagicMock()
        isolator._apply_process_cpu_sets = MagicMock()
        isolator._remove_jail_state = remove_jail_state

        with patch("isolator.tuning.kernel32.SetProcessInformation", return_value=1):
            with patch("isolator.tuning.kernel32.CloseHandle"):
                self.assertTrue(isolator._restore_process(4242))

        self.assertEqual([4242], removed)
        self.assertNotIn(4242, isolator._touched)

    def test_restore_process_retains_jail_state_when_priority_restore_fails(self):
        isolator = self._make_isolator()
        with isolator._state_lock:
            isolator._touched[4242] = {
                "name": "discord.exe",
                "create_time": 123,
                "state": {"priority_class": 64},
                "threads": {},
                "source": "jail",
                "gen": 7,
            }

        isolator._open_process = lambda *args, **kwargs: 99
        isolator._get_process_create_time = lambda handle: 123
        isolator._restore_threads_for_process = MagicMock()
        isolator._apply_process_cpu_sets = MagicMock()
        isolator._remove_jail_state = MagicMock()

        with patch("isolator.tuning.kernel32.SetPriorityClass", return_value=0):
            with patch("isolator.tuning.kernel32.SetProcessInformation", return_value=1):
                with patch("isolator.tuning.kernel32.CloseHandle"):
                    self.assertFalse(isolator._restore_process(4242))

        self.assertIn(4242, isolator._touched)
        isolator._remove_jail_state.assert_not_called()


class JailStateRecoveryTests(unittest.TestCase):
    def test_record_and_remove_jail_state_round_trip(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        with _temp_jail_state_path():
            with isolator._state_lock:
                isolator._touched[4242] = {
                    "name": "discord.exe",
                    "create_time": 123,
                    "state": {"priority_class": 32},
                    "threads": {},
                    "source": "jail",
                    "gen": 1,
                }
            isolator._record_jail_state(4242)
            state = isolator._load_jail_state()
            self.assertIn("4242", state.get("pids", {}))
            isolator._remove_jail_state(4242)
            state = isolator._load_jail_state()
            self.assertNotIn("4242", (state or {}).get("pids", {}))

    def test_remove_jail_states_batches_json_io(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        load_calls = []
        save_calls = []
        isolator._load_jail_state = lambda: load_calls.append(True) or {
            "pids": {"101": {}, "102": {}, "103": {}}
        }
        isolator._save_jail_state = lambda state: save_calls.append(state) or True
        isolator._remove_jail_state_file = MagicMock()

        isolator._remove_jail_states([101, 102])

        self.assertEqual([True], load_calls)
        self.assertEqual(1, len(save_calls))
        self.assertEqual({"103"}, set(save_calls[0]["pids"]))
        isolator._remove_jail_state_file.assert_not_called()

    def test_remove_jail_states_deletes_file_when_last_entry_removed(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._load_jail_state = lambda: {"pids": {"101": {}}}
        isolator._save_jail_state = MagicMock()
        isolator._remove_jail_state_file = MagicMock()

        isolator._remove_jail_states([101])

        isolator._remove_jail_state_file.assert_called_once()
        isolator._save_jail_state.assert_not_called()

    def test_record_jail_states_batches_json_io(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        with isolator._state_lock:
            for pid in (101, 102, 103):
                isolator._touched[pid] = {
                    "name": f"app{pid}.exe",
                    "create_time": pid,
                    "state": {"priority_class": 64},
                    "threads": {},
                    "source": "jail",
                    "gen": pid,
                }
        load_calls = []
        save_calls = []
        isolator._load_jail_state = lambda: load_calls.append(True) or {"pids": {}}
        isolator._save_jail_state = lambda state: save_calls.append(state) or True

        isolator._record_jail_states([101, 102, 103])

        self.assertEqual([True], load_calls)
        self.assertEqual(1, len(save_calls))
        self.assertEqual({"101", "102", "103"}, set(save_calls[0]["pids"]))


if __name__ == "__main__":
    unittest.main()
