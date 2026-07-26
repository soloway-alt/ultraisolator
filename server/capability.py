"""Shared capability-warning extraction for status-derived payloads."""


def capability_warnings(status):
    structured = status.get("capability_issues")
    if isinstance(structured, (list, tuple)) and structured:
        return [
            issue
            for issue in structured
            if isinstance(issue, dict)
            and str(issue.get("severity", "")).lower() in {"warning", "error"}
        ]
    return [
        {
            "code": "legacy_capability_note",
            "severity": "warning",
            "message": str(note),
            "data": {},
        }
        for note in status.get("capability_notes", []) or []
    ]
