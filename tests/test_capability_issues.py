import unittest
from pathlib import Path

from isolator.base import _CAPABILITY_METADATA, BaseMixin


class _CapabilityRecorder(BaseMixin):
    def __init__(self):
        self._capability_notes = []
        self._capability_notes_seen = set()
        self._capability_issues = []
        self._capability_issues_seen = set()


class CapabilityIssueTests(unittest.TestCase):
    def test_all_stable_capability_codes_have_english_and_russian_copy(self):
        root = Path(__file__).resolve().parents[1]
        catalogs = [
            (root / "ui" / "src" / "locales" / name).read_text(encoding="utf-8")
            for name in ("en.mjs", "ru.mjs")
        ]

        for code, _severity in _CAPABILITY_METADATA.values():
            for catalog in catalogs:
                self.assertIn(f"'capability.{code}'", catalog)

    def test_known_capability_has_stable_code_and_diagnostic_fallback(self):
        recorder = _CapabilityRecorder()

        recorder._note_capability(
            "Steam auto-detection enabled."
        )

        self.assertEqual(
            [{
                "code": "steam_auto_detection_enabled",
                "data": {},
                "severity": "info",
                "message": "Steam auto-detection enabled.",
            }],
            recorder._capability_issues,
        )
        self.assertEqual(["Steam auto-detection enabled."], recorder._capability_notes)

    def test_explicit_code_data_and_severity_are_deduplicated(self):
        recorder = _CapabilityRecorder()

        recorder._note_capability(
            "CPU partition is limited.",
            code="processor_groups_unavailable",
            data={"group_count": 2},
            severity="warning",
        )
        recorder._note_capability(
            "CPU partition is limited.",
            code="processor_groups_unavailable",
            data={"group_count": 2},
            severity="warning",
        )

        self.assertEqual(1, len(recorder._capability_issues))
        self.assertEqual({"group_count": 2}, recorder._capability_issues[0]["data"])

    def test_unknown_message_is_available_only_as_diagnostic_fallback(self):
        recorder = _CapabilityRecorder()

        recorder._note_capability("A future diagnostic message.")

        issue = recorder._capability_issues[0]
        self.assertEqual("diagnostic_fallback", issue["code"])
        self.assertEqual("warning", issue["severity"])
        self.assertEqual("A future diagnostic message.", issue["data"]["message"])


if __name__ == "__main__":
    unittest.main()
