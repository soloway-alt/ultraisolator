import re
import unittest
from pathlib import Path
from unittest.mock import patch

from isolator.app import EsportsIsolatorPro
from server.log_store import _TAG_RE


class FakeLogHandle:
    def __init__(self):
        self.writes = []
        self.flushes = 0
        self.closed = False

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        self.flushes += 1

    def close(self):
        self.closed = True


class LoggingTests(unittest.TestCase):
    def _make_isolator(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.messages = []
        isolator._log = isolator.messages.append
        return isolator

    def test_file_log_does_not_flush_every_line(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        handle = FakeLogHandle()
        isolator._log_file_handle = handle

        with patch("builtins.print"):
            isolator._log("one")
            isolator._log("two")

        self.assertEqual(["one\n", "two\n"], handle.writes)
        self.assertEqual(0, handle.flushes)

    def test_close_log_file_flushes_once(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        handle = FakeLogHandle()
        isolator._log_file_handle = handle
        isolator._log_file_path = "session.log"
        isolator._log_use_timestamp = True

        isolator._close_log_file()

        self.assertEqual(1, handle.flushes)
        self.assertTrue(handle.closed)
        self.assertIsNone(isolator._log_file_handle)

    def test_monitor_exception_log_once_distinguishes_message_fingerprint(self):
        isolator = self._make_isolator()

        isolator._log_once(("monitor_exception", "ValueError"), "[WARN] Monitor loop error: phase=scan failed")
        isolator._log_once(("monitor_exception", "ValueError"), "[WARN] Monitor loop error: phase=restore failed")

        self.assertEqual(2, len(isolator.messages))

    def test_monitor_exception_log_once_scrubs_volatile_pid_and_paths(self):
        isolator = self._make_isolator()

        isolator._log_once(
            ("monitor_exception", "OSError"),
            r"[WARN] Monitor loop error: pid=1234 path=C:\Games\One\game.exe denied",
        )
        isolator._log_once(
            ("monitor_exception", "OSError"),
            r"[WARN] Monitor loop error: pid=5678 path=D:\Steam\Two\game.exe denied",
        )

        self.assertEqual(1, len(isolator.messages))

    def test_log_once_lru_evicts_oldest_without_clearing_all_entries(self):
        isolator = self._make_isolator()
        isolator._reported_failure_limit = 2

        isolator._log_once(("a",), "a")
        isolator._log_once(("b",), "b")
        isolator._log_once(("c",), "c")
        isolator._log_once(("b",), "b again")
        isolator._log_once(("a",), "a again")

        self.assertEqual(["a", "b", "c", "a again"], isolator.messages)

    def test_log_once_ttl_allows_relogging_after_expiry(self):
        isolator = self._make_isolator()
        isolator._reported_failure_ttl_s = 1.0

        with patch("isolator.base.time.monotonic", side_effect=[0.0, 2.0]):
            isolator._log_once(("ttl",), "first")
            isolator._log_once(("ttl",), "second")

        self.assertEqual(["first", "second"], isolator.messages)

    def test_log_once_amortizes_full_prune_to_the_interval(self):
        isolator = self._make_isolator()
        prune_calls = []
        original_prune = isolator._prune_reported_failures_locked
        isolator._prune_reported_failures_locked = lambda now=None: prune_calls.append(now) or original_prune(now)

        clock = iter(float(i) for i in range(200))
        with patch("isolator.base.time.monotonic", side_effect=lambda: next(clock)):
            for index in range(100):
                isolator._log_once(("spam", index), f"message {index}")

        # One sweep when the interval first elapses (monotonic starts at 0 and
        # _last_reported_failure_prune starts at 0), then one per 60s window.
        self.assertLessEqual(len(prune_calls), 2)
        self.assertEqual(100, len(isolator.messages))


class LogTagFormatTests(unittest.TestCase):
    def test_every_bracket_log_prefix_in_isolator_matches_log_store_tag_re(self):
        # Every "[TAG] ..." literal the engine can emit must parse into a tag
        # by server.log_store._TAG_RE — otherwise the line reaches the UI with
        # tag=None and the raw bracket prefix leaks into the message text
        # (regression: "[RECOVERY:jail:auto]" was unparseable).
        isolator_dir = Path(__file__).resolve().parent.parent / "isolator"
        literal_prefix = re.compile(r"""(?:[rf]{1,2})?["'](\[[^\]"']*\])""")
        brackets_seen = set()
        offenders = []
        for source_path in sorted(isolator_dir.glob("*.py")):
            text = source_path.read_text(encoding="utf-8")
            for match in literal_prefix.finditer(text):
                bracket = match.group(1)
                brackets_seen.add(bracket)
                if not _TAG_RE.match(f"{bracket} x"):
                    offenders.append(f"{source_path.name}: {bracket}")
        # Sanity: the scan must keep finding the common tags, or the literal
        # regex itself has regressed and the assertion below proves nothing.
        self.assertIn("[WARN]", brackets_seen)
        self.assertIn("[INFO]", brackets_seen)
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
