"""Shared capability-warning extraction for status-derived payloads."""

import time


class _TtlCache:
    """Tiny TTL cache for derived bridge payloads (readiness, MSI devices).

    get() returns the cached value while it is fresh, or None when the cache
    is empty, expired, or bypassed with refresh=True. set() stores a value
    and stamps the clock; clear() empties the cache. The monotonic clock is
    injectable so tests can drive expiry without sleeping.
    """

    def __init__(self, ttl_s, monotonic=time.monotonic):
        self.ttl_s = ttl_s
        self._monotonic = monotonic
        self._value = None
        self._stored_at = 0.0

    def get(self, refresh=False):
        if refresh or self._value is None:
            return None
        if self._monotonic() - self._stored_at >= self.ttl_s:
            return None
        return self._value

    def set(self, value):
        self._value = value
        self._stored_at = self._monotonic()

    def clear(self):
        self._value = None
        self._stored_at = 0.0


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
