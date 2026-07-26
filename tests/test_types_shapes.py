import unittest

from isolator.recovery import RecoveryMixin
from isolator.types import (
    PROCESS_STATE_KEYS,
    JailStateEntry,
    ProcessState,
    TouchedEntry,
)


class _Sanitizer(RecoveryMixin):
    """Minimal host exposing _sanitize_jail_entry_state without the full engine."""

    def __init__(self):
        self._cpu_sets_by_id = {}


class TypedShapeTests(unittest.TestCase):
    def test_process_state_keys_match_the_typeddict(self):
        self.assertEqual(
            {
                "priority_class",
                "cpu_set_ids",
                "affinity_mask",
                "priority_boost_disabled",
                "power_control_mask",
                "power_state_mask",
                "page_priority",
                "io_priority",
            },
            set(ProcessState.__annotations__),
        )
        self.assertEqual(set(ProcessState.__annotations__), set(PROCESS_STATE_KEYS))

    def test_touched_entry_shape(self):
        self.assertEqual(
            {"name", "create_time", "state", "threads", "source", "gen"},
            set(TouchedEntry.__annotations__),
        )

    def test_jail_state_entry_shape(self):
        self.assertEqual(
            {"name", "create_time", "source", "updated_at", "state"},
            set(JailStateEntry.__annotations__),
        )

    def test_sanitizer_accepts_every_process_state_key(self):
        sanitizer = _Sanitizer()
        valid = {
            "priority_class": 0x00000020,  # NORMAL_PRIORITY_CLASS
            "cpu_set_ids": [],
            "affinity_mask": 0b1111,
            "priority_boost_disabled": True,
            "power_control_mask": 1,
            "power_state_mask": 0,
            "page_priority": 5,
            "io_priority": 2,
        }
        self.assertEqual(set(valid), set(PROCESS_STATE_KEYS))
        cleaned = sanitizer._sanitize_jail_entry_state(valid)
        self.assertEqual(valid, cleaned)

    def test_sanitizer_drops_keys_outside_the_shape(self):
        sanitizer = _Sanitizer()
        cleaned = sanitizer._sanitize_jail_entry_state({"io_priority": 2, "unexpected": 1})
        self.assertEqual({"io_priority": 2}, cleaned)


if __name__ == "__main__":
    unittest.main()
