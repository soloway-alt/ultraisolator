"""Typed outcome protocols for the tuning layer."""

import enum


class TuningState(str, enum.Enum):
    """Result of a game-optimization attempt.

    A str subclass so members compare equal to — and JSON-serialize exactly
    like — the raw strings they replaced; the runtime-status wire format
    (active_games[].tuning_state) is unchanged.
    """

    APPLIED = "applied"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    FAILED = "failed"


# _touched sources that throttle a process the way the jail does (idle
# priority, EcoQoS, background CPU sets). Their entries are persisted to the
# crash-recovery jail-state file and their restores are held to the same
# fail-closed standard in _restore_process.
JAIL_LIKE_SOURCES = frozenset({"jail", "probalance"})


class JailOutcome(enum.Enum):
    """Internal result of a jail attempt.

    _jail_process_impl returns these; the public _jail_process maps them to
    the legacy tri-state (True / None / False) that callers and tests pin.
    """

    JAILED = enum.auto()
    DENIED = enum.auto()
    SKIPPED = enum.auto()
