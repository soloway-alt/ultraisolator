import unittest
from unittest import mock
from unittest.mock import MagicMock

from isolator.app import EsportsIsolatorPro
from isolator.discovery import GAME_SUGGESTION_LIMIT
from isolator.runtime import MonitorCycle

_PROCESSES = [
    (10, "cs2.exe"),
    (200, "newgame.exe"),
    (300, "steam.exe"),
    (400, "svchost.exe"),
]


def _make_isolator():
    isolator = EsportsIsolatorPro(
        config_path="__no_local_config__.json",
        scan_game_libraries=False,
    )
    isolator.messages = []
    isolator._log = isolator.messages.append
    return isolator


def _make_suggestion_isolator(fullscreen=True):
    isolator = _make_isolator()
    isolator.enable_game_suggestions = True
    isolator._is_window_fullscreen = MagicMock(return_value=fullscreen)
    # SAFETY ORACLE: the suggestion path must never reach any tuning method.
    isolator._jail_process = MagicMock()
    isolator._optimize_game_with_state = MagicMock()
    isolator._boost_foreground = MagicMock()
    return isolator


def _idle_cycle(fg_pid=200, now=100.0):
    cycle = MonitorCycle.create(now)
    cycle.last_fg_pid = fg_pid
    return cycle


def _run_sustained(isolator, cycle, processes=_PROCESSES, cpu_samples=None, start=100.0):
    """Drive the step through candidate seeding and past the 15s hold."""
    isolator._advance_game_suggestions(cycle, start, processes, cpu_samples or {})
    isolator._advance_game_suggestions(cycle, start + 16.0, processes, cpu_samples or {})


def _patched_foreground(pid, hwnd=555):
    def set_pid(_hwnd, byref_arg):
        byref_arg._obj.value = pid
        return True

    return (
        mock.patch("isolator.runtime.user32.GetForegroundWindow", return_value=hwnd),
        mock.patch("isolator.runtime.user32.GetWindowThreadProcessId", side_effect=set_pid),
    )


class RecordGameSuggestionTests(unittest.TestCase):
    def test_records_normalized_suggestion_with_signals(self):
        isolator = _make_isolator()

        isolator._record_game_suggestion("NewGame.exe", 200, ["fullscreen", "sustained_foreground"])

        with isolator._state_lock:
            suggestions = list(isolator._game_suggestions)
        self.assertEqual(1, len(suggestions))
        self.assertEqual("newgame.exe", suggestions[0]["name"])
        self.assertEqual(200, suggestions[0]["pid"])
        self.assertEqual(["fullscreen", "sustained_foreground"], suggestions[0]["signals"])
        self.assertGreater(suggestions[0]["first_seen"], 0)

    def test_dedupes_by_name(self):
        isolator = _make_isolator()

        isolator._record_game_suggestion("newgame.exe", 200, ["fullscreen"])
        isolator._record_game_suggestion("newgame.exe", 201, ["fullscreen"])

        with isolator._state_lock:
            self.assertEqual(1, len(isolator._game_suggestions))

    def test_skips_known_games_and_empty_names(self):
        isolator = _make_isolator()
        isolator.games.add("knowngame.exe")
        isolator._steam_games_cache.add("steamgame.exe")

        isolator._record_game_suggestion("knowngame.exe", 200, ["fullscreen"])
        isolator._record_game_suggestion("steamgame.exe", 201, ["fullscreen"])
        isolator._record_game_suggestion("", 202, ["fullscreen"])

        with isolator._state_lock:
            self.assertEqual([], isolator._game_suggestions)

    def test_store_is_capped_keeping_the_newest(self):
        isolator = _make_isolator()

        for index in range(GAME_SUGGESTION_LIMIT + 3):
            isolator._record_game_suggestion(f"game{index}.exe", 1000 + index, ["fullscreen"])

        with isolator._state_lock:
            names = [entry["name"] for entry in isolator._game_suggestions]
        self.assertEqual(GAME_SUGGESTION_LIMIT, len(names))
        self.assertEqual(f"game{GAME_SUGGESTION_LIMIT + 2}.exe", names[-1])
        self.assertNotIn("game0.exe", names)


class AdvanceGameSuggestionsTests(unittest.TestCase):
    def test_sustained_fullscreen_foreground_is_suggested(self):
        isolator = _make_suggestion_isolator()
        cycle = _idle_cycle(fg_pid=200)

        fg_patches = _patched_foreground(200)
        with fg_patches[0], fg_patches[1]:
            _run_sustained(isolator, cycle)

        with isolator._state_lock:
            suggestions = list(isolator._game_suggestions)
        self.assertEqual(1, len(suggestions))
        self.assertEqual("newgame.exe", suggestions[0]["name"])
        self.assertEqual(["fullscreen", "sustained_foreground"], suggestions[0]["signals"])
        isolator._jail_process.assert_not_called()
        isolator._optimize_game_with_state.assert_not_called()
        isolator._boost_foreground.assert_not_called()

    def test_cpu_signal_is_appended_when_the_sample_clears_the_floor(self):
        isolator = _make_suggestion_isolator()
        cycle = _idle_cycle(fg_pid=200)

        fg_patches = _patched_foreground(200)
        with fg_patches[0], fg_patches[1]:
            _run_sustained(isolator, cycle, cpu_samples={200: 12.5})

        with isolator._state_lock:
            self.assertEqual(
                ["fullscreen", "sustained_foreground", "cpu_load"],
                isolator._game_suggestions[0]["signals"],
            )

    def test_low_or_missing_cpu_sample_still_suggests_without_the_signal(self):
        isolator = _make_suggestion_isolator()
        cycle = _idle_cycle(fg_pid=200)

        fg_patches = _patched_foreground(200)
        with fg_patches[0], fg_patches[1]:
            _run_sustained(isolator, cycle, cpu_samples={200: 1.0})

        with isolator._state_lock:
            self.assertEqual(
                ["fullscreen", "sustained_foreground"],
                isolator._game_suggestions[0]["signals"],
            )

    def test_disabled_flag_is_a_complete_noop(self):
        isolator = _make_suggestion_isolator()
        isolator.enable_game_suggestions = False
        cycle = _idle_cycle(fg_pid=200)

        fg_patches = _patched_foreground(200)
        with fg_patches[0], fg_patches[1]:
            _run_sustained(isolator, cycle)

        with isolator._state_lock:
            self.assertEqual([], isolator._game_suggestions)

    def test_never_suggests_in_game_mode_and_resets_the_candidate(self):
        isolator = _make_suggestion_isolator()
        cycle = _idle_cycle(fg_pid=200)
        cycle.fg_candidate_pid = 200
        cycle.fg_candidate_since = 50.0
        cycle.current_game_pids = {10}

        fg_patches = _patched_foreground(200)
        with fg_patches[0], fg_patches[1]:
            isolator._advance_game_suggestions(cycle, 100.0, _PROCESSES, {})

        with isolator._state_lock:
            self.assertEqual([], isolator._game_suggestions)
        self.assertEqual(0, cycle.fg_candidate_pid)
        self.assertEqual(0.0, cycle.fg_candidate_since)
        isolator._jail_process.assert_not_called()
        isolator._optimize_game_with_state.assert_not_called()
        isolator._boost_foreground.assert_not_called()

    def test_requires_sustained_foreground_before_probing(self):
        isolator = _make_suggestion_isolator()
        cycle = _idle_cycle(fg_pid=200)

        fg_patches = _patched_foreground(200)
        with fg_patches[0], fg_patches[1]:
            isolator._advance_game_suggestions(cycle, 100.0, _PROCESSES, {})
            isolator._advance_game_suggestions(cycle, 110.0, _PROCESSES, {})

        isolator._is_window_fullscreen.assert_not_called()
        with isolator._state_lock:
            self.assertEqual([], isolator._game_suggestions)

    def test_foreground_change_restarts_the_hold_timer(self):
        isolator = _make_suggestion_isolator()
        cycle = _idle_cycle(fg_pid=200)

        fg_patches = _patched_foreground(200)
        with fg_patches[0], fg_patches[1]:
            isolator._advance_game_suggestions(cycle, 100.0, _PROCESSES, {})
            cycle.last_fg_pid = 400
            isolator._advance_game_suggestions(cycle, 116.0, _PROCESSES, {})

        self.assertEqual(400, cycle.fg_candidate_pid)
        self.assertEqual(116.0, cycle.fg_candidate_since)
        with isolator._state_lock:
            self.assertEqual([], isolator._game_suggestions)

    def test_windowed_foreground_is_not_suggested(self):
        isolator = _make_suggestion_isolator(fullscreen=False)
        cycle = _idle_cycle(fg_pid=200)

        fg_patches = _patched_foreground(200)
        with fg_patches[0], fg_patches[1]:
            _run_sustained(isolator, cycle)

        with isolator._state_lock:
            self.assertEqual([], isolator._game_suggestions)

    def test_known_game_protected_and_launcher_names_are_skipped(self):
        for fg_pid in (10, 300, 400):
            with self.subTest(fg_pid=fg_pid):
                isolator = _make_suggestion_isolator()
                # cs2.exe is a configured game, svchost.exe is protected,
                # steam.exe is both protected and a launcher exe.
                cycle = _idle_cycle(fg_pid=fg_pid)

                fg_patches = _patched_foreground(fg_pid)
                with fg_patches[0], fg_patches[1]:
                    _run_sustained(isolator, cycle)

                with isolator._state_lock:
                    self.assertEqual([], isolator._game_suggestions)
                isolator._jail_process.assert_not_called()
                isolator._optimize_game_with_state.assert_not_called()
                isolator._boost_foreground.assert_not_called()

    def test_foreground_moving_between_hold_and_probe_aborts(self):
        isolator = _make_suggestion_isolator()
        cycle = _idle_cycle(fg_pid=200)

        # The re-query sees a different pid than the tracked candidate.
        fg_patches = _patched_foreground(400)
        with fg_patches[0], fg_patches[1]:
            _run_sustained(isolator, cycle)

        isolator._is_window_fullscreen.assert_not_called()
        with isolator._state_lock:
            self.assertEqual([], isolator._game_suggestions)

    def test_already_suggested_name_is_not_probed_again(self):
        isolator = _make_suggestion_isolator()
        isolator._record_game_suggestion("newgame.exe", 199, ["fullscreen"])
        cycle = _idle_cycle(fg_pid=200)

        fg_patches = _patched_foreground(200)
        with fg_patches[0], fg_patches[1]:
            _run_sustained(isolator, cycle)

        isolator._is_window_fullscreen.assert_not_called()
        with isolator._state_lock:
            self.assertEqual(1, len(isolator._game_suggestions))


class SnapshotExposureTests(unittest.TestCase):
    def test_live_snapshot_includes_a_copy_of_the_suggestions(self):
        isolator = _make_isolator()
        isolator._record_game_suggestion("newgame.exe", 200, ["fullscreen", "sustained_foreground"])

        snapshot = isolator.get_live_snapshot()

        self.assertEqual(1, len(snapshot["game_suggestions"]))
        exposed = snapshot["game_suggestions"][0]
        self.assertEqual("newgame.exe", exposed["name"])
        # Mutating the exposed dict must not touch engine state.
        exposed["name"] = "tampered.exe"
        with isolator._state_lock:
            self.assertEqual("newgame.exe", isolator._game_suggestions[0]["name"])

    def test_live_snapshot_defaults_to_an_empty_list(self):
        isolator = _make_isolator()

        self.assertEqual([], isolator.get_live_snapshot()["game_suggestions"])


if __name__ == "__main__":
    unittest.main()
