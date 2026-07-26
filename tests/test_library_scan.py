import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from isolator.app import EsportsIsolatorPro


def _make_isolator():
    return EsportsIsolatorPro(
        config_path="__no_local_config__.json",
        scan_game_libraries=False,
    )


class LibraryScanWorkerTests(unittest.TestCase):
    def test_constructor_scan_runs_on_worker_thread_and_sets_ready(self):
        scan_threads = []

        def record_scan(self, force=False):
            scan_threads.append(threading.current_thread().name)

        with patch.object(EsportsIsolatorPro, "_scan_steam_games", record_scan), patch.object(
            EsportsIsolatorPro, "_scan_epic_games", record_scan
        ):
            isolator = EsportsIsolatorPro(
                config_path="__no_local_config__.json",
                scan_game_libraries=True,
            )
            self.assertTrue(isolator._library_scan_ready.wait(5))
            isolator._library_scan_thread.join(timeout=5)

        self.assertEqual(["IsolatorLibraryScan", "IsolatorLibraryScan"], scan_threads)

    def test_constructor_without_scan_marks_ready_immediately(self):
        isolator = _make_isolator()

        self.assertTrue(isolator._library_scan_ready.is_set())
        self.assertIsNone(isolator._library_scan_thread)

    def test_request_library_scan_drops_request_while_scan_in_flight(self):
        isolator = _make_isolator()
        release = threading.Event()
        started = threading.Event()
        runs = []

        def slow_scan(force=False):
            runs.append(force)
            started.set()
            release.wait(5)

        isolator._run_library_scans = slow_scan
        isolator._request_library_scan(force=True)
        self.assertTrue(started.wait(5))
        isolator._request_library_scan()
        release.set()
        isolator._library_scan_thread.join(timeout=5)

        self.assertEqual([True], runs)

    def test_background_jail_waits_for_initial_scan(self):
        isolator = _make_isolator()
        isolator.enable_background_jailing = True
        isolator._isolate_background = MagicMock(return_value={"touched": 1})
        isolator._library_scan_ready.clear()

        blocked = isolator._run_background_jail(initial=True, processes=[])

        self.assertEqual(0, blocked["touched"])
        isolator._isolate_background.assert_not_called()

        isolator._library_scan_ready.set()
        isolator._run_background_jail(initial=False, processes=[])

        isolator._isolate_background.assert_called_once()

    def test_scan_for_game_exes_stops_at_deadline(self):
        isolator = _make_isolator()
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "somegame.exe"), "w", encoding="utf-8") as handle:
                handle.write("")
            found = set()

            completed = isolator._scan_for_game_exes(
                tmpdir, found, max_depth=4, deadline=time.monotonic() - 1.0
            )

            self.assertFalse(completed)
            self.assertEqual(set(), found)

            found.clear()
            completed = isolator._scan_for_game_exes(
                tmpdir, found, max_depth=4, deadline=time.monotonic() + 30.0
            )

            self.assertTrue(completed)
            self.assertEqual({"somegame.exe"}, found)

    def test_scan_launcher_library_budget_overrun_records_provider_issue(self):
        isolator = _make_isolator()
        with tempfile.TemporaryDirectory() as tmpdir:
            isolator._scan_for_game_exes = lambda *args, **kwargs: False

            result = isolator._scan_launcher_library("fake", [tmpdir], set())

        self.assertEqual(set(), result)
        with isolator._state_lock:
            codes = [issue["code"] for issue in isolator._discovery_issues]
        self.assertIn("fake_scan_budget_exceeded", codes)

    def test_scan_launcher_library_stop_event_abort_records_nothing(self):
        isolator = _make_isolator()
        with tempfile.TemporaryDirectory() as tmpdir:
            isolator._scan_for_game_exes = lambda *args, **kwargs: False
            isolator._stop_event.set()

            isolator._scan_launcher_library("fake", [tmpdir], set())

        with isolator._state_lock:
            issues = list(isolator._discovery_issues)
        self.assertEqual([], issues)

    def test_steam_budget_overrun_records_discovery_issue(self):
        isolator = _make_isolator()
        with tempfile.TemporaryDirectory() as tmpdir:
            common = os.path.join(tmpdir, "steamapps", "common")
            os.makedirs(common)
            isolator._get_steam_path = lambda: tmpdir
            isolator._scan_for_game_exes = lambda *args, **kwargs: False

            isolator._scan_steam_games(force=True)

        with isolator._state_lock:
            codes = [issue["code"] for issue in isolator._discovery_issues]
        self.assertIn("steam_scan_budget_exceeded", codes)


if __name__ == "__main__":
    unittest.main()
