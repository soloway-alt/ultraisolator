"""Typed shapes for the engine's load-bearing dict contracts.

These dicts are written in one or two places and read across many modules;
naming them here turns the implicit contracts into something a reader (and a
test) can point at. Upcoming features extend these shapes — e.g. ProBalance
adds a ``"probalance"`` source and per-process CPU accounting — so the shapes
are named before they grow.

The engine package is not mypy-checked (Windows-only ctypes), so these serve as
documentation plus a drift guard: ``tests/test_types_shapes.py`` pins the key
sets, and ``_sanitize_jail_entry_state`` derives its accepted-key set from
``PROCESS_STATE_KEYS`` so the validator and the shape cannot diverge.
"""

from typing import TypedDict


class ProcessState(TypedDict, total=False):
    """Reversible per-process tuning snapshot captured by ``_query_process_state``.

    Every field is optional because each Win32 read can be denied; restore
    applies only the fields that were successfully captured.
    """

    priority_class: int
    cpu_set_ids: list[int]
    affinity_mask: int
    priority_boost_disabled: bool
    power_control_mask: int
    power_state_mask: int
    page_priority: int
    io_priority: int


class TouchedEntry(TypedDict):
    """A live entry in the ``_touched`` ledger of processes the engine mutated.

    ``source`` is the reason the process was touched — ``"jail"``,
    ``"foreground"``, ``"optimize_game"`` (and ``"probalance"`` once that
    feature lands); ``gen`` is the generation stamp used to guard against
    PID-reuse races during restore.
    """

    name: str
    create_time: int
    state: ProcessState
    threads: dict
    source: str
    gen: int


class JailStateEntry(TypedDict):
    """One process record persisted to the crash-recovery jail-state file."""

    name: str
    create_time: int
    source: str
    updated_at: float
    state: ProcessState


# The accepted-key set for persisted process state. _sanitize_jail_entry_state
# uses this so the validator and the ProcessState shape stay in lockstep.
PROCESS_STATE_KEYS = frozenset(ProcessState.__annotations__)
