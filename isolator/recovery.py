"""Crash-recovery helpers for persistent system state."""

import re

from .protected_state import (
    ProtectedStateError,
    is_protected_state_path_safe,
    read_protected_state_file,
    remove_protected_state_file,
    write_protected_state_file,
)
from .winapi import *


GUID_STATE_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class RecoveryMixin:
    @staticmethod
    def _guid_to_state(guid):
        if guid is None:
            return None
        data4 = [int(value) for value in bytes(guid.Data4)]
        return (
            f"{int(guid.Data1):08x}-{int(guid.Data2):04x}-{int(guid.Data3):04x}-"
            f"{data4[0]:02x}{data4[1]:02x}-"
            f"{''.join(f'{value:02x}' for value in data4[2:])}"
        )

    @staticmethod
    def _guid_from_state(data):
        if not isinstance(data, str) or not GUID_STATE_PATTERN.fullmatch(data):
            return None
        try:
            first, second, third, fourth, fifth = data.split("-")
            data4_hex = fourth + fifth
            data4 = [int(data4_hex[index:index + 2], 16) for index in range(0, 16, 2)]
            return GUID(
                int(first, 16),
                int(second, 16),
                int(third, 16),
                (ctypes.c_ubyte * 8)(*data4),
            )
        except (TypeError, ValueError):
            return None

    def _is_recovery_state_acl_safe(self, path=RECOVERY_STATE_PATH):
        return is_protected_state_path_safe(path)

    def _load_recovery_state(self):
        try:
            if not os.path.exists(RECOVERY_STATE_PATH):
                return {}
            if not self._is_recovery_state_acl_safe(RECOVERY_STATE_PATH):
                self._log_once(
                    ("recovery_state_acl_unsafe",),
                    "[WARN] Recovery state ACL is unsafe; rejecting recovery state.",
                )
                return None
            loaded = read_protected_state_file(RECOVERY_STATE_PATH)
            if isinstance(loaded, dict) and loaded.get("version") == RECOVERY_STATE_VERSION:
                return loaded
            self._log_once(
                ("recovery_state_invalid_type", type(loaded).__name__),
                "[WARN] Recovery state file is invalid or downgraded; leaving it in place for manual inspection.",
            )
            return None
        except ProtectedStateError as exc:
            self._log_once(
                ("recovery_state_protected", str(exc)),
                f"[WARN] Recovery state rejected as invalid or tampered: {exc}.",
            )
            return None
        except Exception as exc:
            self._log_once(("recovery_state_load", type(exc).__name__), f"[WARN] Failed to load recovery state: {exc}")
            return None

    def _save_recovery_state(self, state):
        try:
            state = dict(state or {})
            state["version"] = RECOVERY_STATE_VERSION
            state["updated_at"] = time.time()
            return write_protected_state_file(RECOVERY_STATE_PATH, state)
        except Exception as exc:
            self._log_once(("recovery_state_save", type(exc).__name__), f"[WARN] Failed to save recovery state: {exc}")
            return False

    def _remove_recovery_state_file(self):
        try:
            remove_protected_state_file(RECOVERY_STATE_PATH)
        except OSError as exc:
            self._log_once(("recovery_state_remove", type(exc).__name__), f"[WARN] Failed to remove recovery state: {exc}")

    def _write_power_recovery_state(self, original_scheme=None, switched=None, scheme_in_use=None):
        state = self._load_recovery_state()
        if not isinstance(state, dict):
            state = {}
        if "created_at" not in state:
            state["created_at"] = time.time()
        power = state.get("power")
        if not isinstance(power, dict):
            power = {}
        if original_scheme is not None:
            power["original_scheme"] = self._guid_to_state(original_scheme)
        if switched is not None:
            power["switched"] = bool(switched)
        if scheme_in_use is not None:
            power["scheme_in_use"] = scheme_in_use
        state["power"] = power
        return self._save_recovery_state(state)

    def _clear_power_recovery_state(self):
        state = self._load_recovery_state()
        if not isinstance(state, dict) or not state:
            return
        state.pop("power", None)
        if len([key for key in state if key not in {"version", "created_at", "updated_at"}]) == 0:
            self._remove_recovery_state_file()
        else:
            self._save_recovery_state(state)

    def _has_persistent_recovery_state(self):
        return os.path.exists(RECOVERY_STATE_PATH) or os.path.exists(IFEO_BACKUP_PATH)

    def _recover_persistent_state(self, auto=False):
        self._persistent_recovery_incomplete = False
        if not self._has_persistent_recovery_state():
            if not auto:
                self._log("[RECOVERY] No persistent recovery state found.")
            return True

        ok = True
        prefix = "[RECOVERY:auto]" if auto else "[RECOVERY]"
        self._log(f"{prefix} Persistent recovery state found. Attempting restore before continuing.")

        self._load_ifeo_backups()
        if self._ifeo_original:
            self._log(f"{prefix} Restoring IFEO registry state from backup.")
            self._restore_ifeo_priorities()
            if self._ifeo_original:
                ok = False
                self._log(f"{prefix} IFEO restore incomplete; run again as administrator.")

        recovery_file_exists = os.path.exists(RECOVERY_STATE_PATH)
        state = self._load_recovery_state()
        if recovery_file_exists and state is None:
            ok = False
            self._log_once(
                ("recovery_state_invalid_dirty",),
                f"{prefix} Recovery state file is invalid or tampered; power recovery state is invalid if present.",
            )
            state = {}
        power = state.get("power") if isinstance(state, dict) else None
        if isinstance(state, dict) and "power" in state and not isinstance(power, dict):
            ok = False
            self._log_once(
                ("recovery_power_invalid_type", type(power).__name__),
                f"{prefix} Power recovery state is invalid; leaving it in place for manual inspection.",
            )
        if isinstance(power, dict):
            original = self._guid_from_state(power.get("original_scheme"))
            switched = power.get("switched")
            if not isinstance(switched, bool):
                ok = False
                self._log_once(
                    ("recovery_power_invalid_switched_type", type(switched).__name__),
                    f"{prefix} Power recovery state is invalid; leaving it in place for manual inspection.",
                )
            elif switched and original is not None:
                if self._set_power_scheme(original):
                    self._log(f"{prefix} Restored original power scheme from recovery state.")
                    state.pop("power", None)
                else:
                    ok = False
                    self._log_once(("recovery_power_restore",), f"{prefix} Failed to restore original power scheme.")
            elif switched:
                ok = False
                self._log_once(
                    ("recovery_power_invalid",),
                    f"{prefix} Power recovery state is invalid; leaving it in place for manual inspection.",
                )
            else:
                state.pop("power", None)

            if "power" in state:
                self._save_recovery_state(state)
            elif len([key for key in state if key not in {"version", "created_at", "updated_at"}]) == 0:
                self._remove_recovery_state_file()
            else:
                self._save_recovery_state(state)

        if ok and not self._has_persistent_recovery_state():
            self._log(f"{prefix} Persistent recovery complete.")
        elif not ok:
            self._persistent_recovery_incomplete = True
            self._log(f"{prefix} Persistent recovery incomplete; refusing to apply new system changes.")
        return ok

    def recover(self):
        if not self._check_admin():
            self._log("[ERROR] administrator_required")
            return False
        if not self._ensure_single_instance():
            return False
        try:
            ok = self._recover_persistent_state(auto=False)
            if ok:
                ok = self._recover_jail_state_from_crash(auto=False)
            return ok
        finally:
            self._release_single_instance()

    def _discard_legacy_jail_state(self, legacy_path=None):
        # WHY: The pre-hardening jail_state.json lived unauthenticated in the
        # writable install/repo root. Its contents are untrusted by definition,
        # so never read or migrate it — just remove the stale file.
        if legacy_path is None:
            legacy_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jail_state.json")
        if not os.path.exists(legacy_path):
            return
        try:
            os.remove(legacy_path)
            self._log_once(
                ("jail_state_legacy_discarded",),
                "[WARN] Discarded legacy unauthenticated jail_state.json from the install directory.",
            )
        except OSError as exc:
            self._log_once(
                ("jail_state_legacy_remove", type(exc).__name__),
                f"[WARN] Failed to remove legacy jail state file: {exc}",
            )

    def _load_jail_state(self):
        try:
            if not os.path.exists(JAIL_STATE_PATH):
                return {}
            if not is_protected_state_path_safe(JAIL_STATE_PATH):
                self._log_once(
                    ("jail_state_acl_unsafe",),
                    "[WARN] Jail state rejected: ACL is unsafe, so path validation was not attempted.",
                )
                return None
            try:
                loaded = read_protected_state_file(JAIL_STATE_PATH)
            except ProtectedStateError as exc:
                self._log_once(
                    ("jail_state_protected", str(exc)),
                    f"[WARN] Jail state rejected: tampered or path validation failed ({exc}).",
                )
                return None
            if isinstance(loaded, dict):
                pids = loaded.get("pids")
                if isinstance(pids, dict):
                    return loaded
            self._log_once(
                ("jail_state_invalid_type", type(loaded).__name__),
                "[WARN] Jail state file is invalid; leaving it in place for manual inspection.",
            )
            return None
        except Exception as exc:
            self._log_once(("jail_state_load", type(exc).__name__), f"[WARN] Failed to load jail state: {exc}")
            return None

    def _save_jail_state(self, state):
        try:
            state["version"] = JAIL_STATE_VERSION
            state["updated_at"] = time.time()
            return bool(write_protected_state_file(JAIL_STATE_PATH, state))
        except Exception as exc:
            self._log_once(("jail_state_save", type(exc).__name__), f"[WARN] Failed to save jail state: {exc}")
            return False

    def _remove_jail_state_file(self):
        try:
            remove_protected_state_file(JAIL_STATE_PATH)
        except OSError as exc:
            self._log_once(("jail_state_remove", type(exc).__name__), f"[WARN] Failed to remove jail state: {exc}")

    def _serialize_jail_entry(self, entry):
        if not isinstance(entry, dict):
            return None
        state = entry.get("state")
        if not isinstance(state, dict):
            state = {}
        return {
            "name": entry.get("name", ""),
            "create_time": int(entry.get("create_time", 0) or 0),
            "source": entry.get("source", "jail"),
            "updated_at": time.time(),
            "state": {
                key: value
                for key, value in state.items()
                if isinstance(value, (int, float, bool, list))
            },
        }

    def _record_jail_state(self, pid):
        self._record_jail_states([pid])

    def _record_jail_states(self, pids):
        normalized_pids = []
        for pid in pids:
            try:
                normalized_pids.append(int(pid))
            except (TypeError, ValueError):
                continue
        if not normalized_pids:
            return
        with self._state_lock:
            entries = {
                pid: self._serialize_jail_entry(self._touched.get(pid))
                for pid in normalized_pids
            }
        entries = {
            pid: serialized
            for pid, serialized in entries.items()
            if serialized and serialized.get("source") == "jail"
        }
        if not entries:
            return
        state = self._load_jail_state()
        if state is None:
            return
        pids = state.setdefault("pids", {})
        for pid, serialized in entries.items():
            pids[str(pid)] = serialized
        self._save_jail_state(state)

    def _remove_jail_state(self, pid):
        self._remove_jail_states([pid])

    def _remove_jail_states(self, pids):
        # Symmetric with _record_jail_states: one load-modify-save for the
        # whole batch instead of a read+fsync-rewrite cycle per PID (the bulk
        # restore path runs inside the ~5s Windows shutdown budget).
        normalized_pids = []
        for pid in pids:
            try:
                normalized_pids.append(int(pid))
            except (TypeError, ValueError):
                continue
        if not normalized_pids:
            return
        state = self._load_jail_state()
        if not isinstance(state, dict):
            return
        pids_map = state.get("pids")
        if not isinstance(pids_map, dict):
            return
        removed_any = False
        for pid in normalized_pids:
            if str(pid) in pids_map:
                pids_map.pop(str(pid), None)
                removed_any = True
        if not removed_any:
            return
        if not pids_map:
            self._remove_jail_state_file()
        else:
            self._save_jail_state(state)

    _RESTORABLE_PRIORITY_CLASSES = frozenset({
        IDLE_PRIORITY_CLASS,
        BELOW_NORMAL_PRIORITY_CLASS,
        NORMAL_PRIORITY_CLASS,
        ABOVE_NORMAL_PRIORITY_CLASS,
        HIGH_PRIORITY_CLASS,
    })

    def _sanitize_jail_entry_state(self, state):
        """Validate a persisted jail-state dict before it reaches _restore_process.

        Returns a cleaned copy containing only known fields with in-range
        values, or None when any present field is malformed. The file is
        HMAC-signed, but restore feeds these values into privileged process
        mutations, so defense-in-depth field validation stays cheap insurance.
        """
        if not isinstance(state, dict):
            return None
        cleaned = {}
        for key, value in state.items():
            if key == "priority_class":
                if value not in self._RESTORABLE_PRIORITY_CLASSES:
                    return None
            elif key in ("affinity_mask", "power_control_mask", "power_state_mask"):
                if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value >= (1 << 64):
                    return None
            elif key == "cpu_set_ids":
                if not isinstance(value, list):
                    return None
                ids = []
                for cpu_set_id in value:
                    if not isinstance(cpu_set_id, int) or isinstance(cpu_set_id, bool) or cpu_set_id < 0:
                        return None
                    ids.append(cpu_set_id)
                known = getattr(self, "_cpu_sets_by_id", None)
                if known and any(cpu_set_id not in known for cpu_set_id in ids):
                    return None
                value = ids
            elif key == "page_priority":
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 7:
                    return None
            elif key == "io_priority":
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 3:
                    return None
            elif key == "priority_boost_disabled":
                value = bool(value)
            else:
                # Unknown keys are dropped rather than fed to restore.
                continue
            cleaned[key] = value
        return cleaned

    def _recover_jail_state_from_crash(self, auto=False):
        prefix = "[RECOVERY:jail:auto]" if auto else "[RECOVERY:jail]"
        self._discard_legacy_jail_state()
        if not os.path.exists(JAIL_STATE_PATH):
            return True
        state = self._load_jail_state()
        if state is None:
            return False
        pids = state.get("pids", {})
        if not isinstance(pids, dict) or not pids:
            self._remove_jail_state_file()
            return True
        self._log(f"{prefix} Restoring {len(pids)} process(es) from crash jail state.")
        restored = 0
        dirty = False
        unresolved = False
        now = time.time()
        for pid_str, saved_entry in list(pids.items()):
            try:
                pid = int(pid_str)
            except (TypeError, ValueError):
                pids.pop(pid_str, None)
                dirty = True
                continue
            if not isinstance(saved_entry, dict):
                pids.pop(pid_str, None)
                dirty = True
                continue
            try:
                updated_at = float(saved_entry.get("updated_at", state.get("updated_at", 0)) or 0)
            except (TypeError, ValueError):
                updated_at = 0.0
            if not updated_at or now - updated_at >= JAIL_STATE_ENTRY_TTL_SECONDS:
                pids.pop(pid_str, None)
                dirty = True
                self._log_once(
                    ("jail_recovery_stale", pid),
                    f"{prefix} Skipping stale jail entry for pid={pid}; recovery state is too old.",
                )
                continue
            handle = self._open_process(
                pid,
                PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_INFORMATION | PROCESS_SET_LIMITED_INFORMATION,
                quiet=True,
            )
            if not handle:
                unresolved = True
                self._log_once(
                    ("jail_recovery_open_failed", pid),
                    f"{prefix} Cannot open pid={pid}; leaving jail recovery state in place for retry.",
                )
                continue
            try:
                current_create_time = self._get_process_create_time(handle)
                saved_create_time = int(saved_entry.get("create_time", 0) or 0)
                if saved_create_time == 0 or current_create_time == 0:
                    pids.pop(pid_str, None)
                    dirty = True
                    self._log_once(
                        ("jail_recovery_create_time_unknown", pid),
                        f"{prefix} Skipping pid={pid}; create_time is unknown, so PID reuse cannot be excluded.",
                    )
                    continue
                if saved_create_time != current_create_time:
                    pids.pop(pid_str, None)
                    dirty = True
                    self._log_once(
                        ("jail_recovery_pid_reused", pid),
                        f"{prefix} Skipping pid={pid}; create_time mismatch indicates PID reuse.",
                    )
                    continue
                sanitized_state = self._sanitize_jail_entry_state(saved_entry.get("state", {}))
                if sanitized_state is None:
                    pids.pop(pid_str, None)
                    dirty = True
                    self._log_once(
                        ("jail_recovery_invalid_state", pid),
                        f"{prefix} Skipping pid={pid}; persisted restore values are malformed.",
                    )
                    continue
                with self._state_lock:
                    self._entry_gen += 1
                    self._touched[pid] = {
                        "name": saved_entry.get("name", ""),
                        "create_time": saved_create_time or current_create_time,
                        "state": sanitized_state,
                        "threads": {},
                        "source": "jail",
                        "gen": self._entry_gen,
                    }
            finally:
                kernel32.CloseHandle(handle)
            # The loop already pops restored entries from `state` and persists
            # once at the end, so route _restore_process's per-PID removal into
            # a throwaway collector instead of a redundant file rewrite.
            if self._restore_process(pid, deferred_jail_removals=[]):
                restored += 1
                pids.pop(pid_str, None)
                dirty = True
            else:
                unresolved = True
        if dirty:
            if pids:
                self._save_jail_state(state)
            else:
                self._remove_jail_state_file()
        remaining = self._load_jail_state()
        if isinstance(remaining, dict) and remaining.get("pids"):
            self._log(f"{prefix} {restored} restored; some jail entries remain for manual inspection.")
            unresolved = True
        else:
            self._log(f"{prefix} Crash jail recovery complete ({restored} restored).")
        return not unresolved
