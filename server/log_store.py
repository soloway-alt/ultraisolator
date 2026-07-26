"""Read-only log file tailing and parsing for the localhost API."""

import os
import re
from pathlib import Path

DEFAULT_LOG_LIMIT = 500
MAX_LOG_LIMIT = 1000
_READ_CHUNK_BYTES = 8192
_MAX_LINE_COUNT_BYTES = 256 * 1024
_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(.*)$")
_TAG_RE = re.compile(r"^\[([A-Z][A-Z0-9_-]*)\]\s*(.*)$")
_WINDOWS_USER_PATH_RE = re.compile(r"([A-Za-z]:\\Users\\)[^\\\s]+(\\[^\s]*)?", re.IGNORECASE)
_TOKEN_VALUE_RE = re.compile(
    r"\b(api[-_ ]?key|token|secret|password|authorization|bearer)\b\s*[:=]\s*([A-Za-z0-9._~+/=-]{8,})",
    re.IGNORECASE,
)
_LONG_SECRET_RE = re.compile(r"\b[A-Za-z0-9._~+/=-]{32,}\b")
_NEUTRAL_TAGS = {"INFO", "WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"}
_CATEGORY_KEYWORDS = (
    ("jail", ("jail", "jailed", "jailing")),
    ("boost", ("boost", "priority", "foreground")),
    ("power", ("power scheme", "power plan", "ultimate performance", "high performance")),
    ("ifeo", ("ifeo", "registry")),
    ("topology", ("topology", "cpu set", "cpu partition", "partition")),
    ("timer", ("timer resolution",)),
    ("game", ("game mode", "game detected", "game closed")),
    ("shutdown", ("shutdown", "safe to close")),
)


def coerce_log_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_LOG_LIMIT
    return max(1, min(MAX_LOG_LIMIT, limit))


def parse_log_line(raw_line, line_number):
    raw = _redact_log_text(str(raw_line).rstrip("\r\n"))
    timestamp = None
    text = raw
    timestamp_match = _TIMESTAMP_RE.match(raw)
    if timestamp_match:
        timestamp = timestamp_match.group(1)
        text = timestamp_match.group(2)

    tag = None
    message = text
    tag_match = _TAG_RE.match(text)
    if tag_match:
        tag = tag_match.group(1)
        message = tag_match.group(2)

    return {
        "line": int(line_number),
        "timestamp": timestamp,
        "severity": _severity_for(tag, message),
        "category": _category_for(tag, message),
        "tag": tag,
        "message": message,
        "raw": raw,
    }


def read_log_payload(log_file, limit=DEFAULT_LOG_LIMIT):
    limit = coerce_log_limit(limit)
    if not isinstance(log_file, str) or not log_file.strip():
        return _unavailable(limit, None, "log_file_not_configured")

    path = _resolve_log_path(log_file)
    if not path.exists() or not path.is_file():
        return _unavailable(limit, _display_log_path(path), "log_file_missing")

    stat = path.stat()
    lines, total_lines = _tail_lines(path, limit)
    start_line = max(1, total_lines - len(lines) + 1)
    entries = [
        parse_log_line(line, start_line + index)
        for index, line in enumerate(lines)
    ]
    return {
        "ok": True,
        "available": True,
        "path": _display_log_path(path),
        "reason": None,
        "limit": limit,
        "size": stat.st_size,
        "modified_time": stat.st_mtime,
        "entries": entries,
    }


def _unavailable(limit, path, reason):
    return {
        "ok": True,
        "available": False,
        "path": path,
        "reason": reason,
        "limit": limit,
        "size": 0,
        "modified_time": None,
        "entries": [],
    }


def _resolve_log_path(log_file):
    path = Path(log_file).expanduser()
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _display_log_path(path):
    return Path(path).name if path else None


def _tail_lines(path, limit):
    size = path.stat().st_size

    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        chunks = []
        newline_count = 0
        while position > 0 and newline_count <= limit:
            read_size = min(_READ_CHUNK_BYTES, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.insert(0, chunk)
            newline_count += chunk.count(b"\n")

    text = b"".join(chunks).decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > limit:
        lines = lines[-limit:]
    if not lines:
        return [], 0
    total_lines = _count_lines(path) if size <= _MAX_LINE_COUNT_BYTES else len(lines)
    return lines, total_lines


def _count_lines(path):
    count = 0
    last_byte = b""
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            count += chunk.count(b"\n")
            last_byte = chunk[-1:]
    if last_byte and last_byte != b"\n":
        count += 1
    return count


def _redact_log_text(text):
    redacted = _WINDOWS_USER_PATH_RE.sub(r"\1<user>\\<redacted>", str(text))
    redacted = _TOKEN_VALUE_RE.sub(lambda match: f"{match.group(1)}=<redacted>", redacted)
    return _LONG_SECRET_RE.sub("<redacted>", redacted)


def _severity_for(tag, message):
    if tag in {"ERROR", "CRITICAL", "FATAL"}:
        return "error"
    if tag in {"WARN", "WARNING"}:
        return "warning"
    text = str(message).lower()
    if "[error]" in text:
        return "error"
    if "[warn]" in text or "[warning]" in text:
        return "warning"
    return "info"


def _category_for(tag, message):
    if tag and tag not in _NEUTRAL_TAGS:
        return tag.lower()
    text = str(message).lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return "general"
