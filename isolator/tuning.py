"""TuningMixin implementation slice."""

import ctypes
import threading
from ctypes import wintypes
from typing import Protocol

from .outcomes import JailOutcome, TuningState
from .types import ProcessState, TouchedEntry
from .winapi import (
    ABOVE_NORMAL_PRIORITY_CLASS,
    BELOW_NORMAL_PRIORITY_CLASS,
    GROUP_AFFINITY,
    HIGH_PRIORITY_CLASS,
    IDLE_PRIORITY_CLASS,
    IO_PRIORITY_NORMAL,
    IO_PRIORITY_VERY_LOW,
    NORMAL_PRIORITY_CLASS,
    PAGE_PRIORITY_INFORMATION,
    PAGE_PRIORITY_MINIMUM,
    PAGE_PRIORITY_NORMAL,
    PROCESS_INFORMATION_CLASS_IO_PRIORITY,
    PROCESS_INFORMATION_CLASS_PAGE_PRIORITY,
    PROCESS_INFORMATION_CLASS_POWER_THROTTLING,
    PROCESS_POWER_THROTTLING_CURRENT_VERSION,
    PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
    PROCESS_POWER_THROTTLING_STATE,
    PROCESS_QUERY_INFORMATION,
    PROCESS_QUERY_LIMITED_INFORMATION,
    PROCESS_SET_INFORMATION,
    PROCESS_SET_LIMITED_INFORMATION,
    PROCESSOR_NUMBER,
    THREAD_QUERY_LIMITED_INFORMATION,
    THREAD_SET_INFORMATION,
    THREAD_SET_LIMITED_INFORMATION,
    kernel32,
    nt_success,
    ntdll,
)

_PROFILE_PRIORITY_CLASSES = {
    "idle": IDLE_PRIORITY_CLASS,
    "below_normal": BELOW_NORMAL_PRIORITY_CLASS,
    "normal": NORMAL_PRIORITY_CLASS,
    "above_normal": ABOVE_NORMAL_PRIORITY_CLASS,
    "high": HIGH_PRIORITY_CLASS,
}


class TuningHost(Protocol):
    """Typing-only host contract for TuningMixin.

    Enumerates every attribute and cross-mixin method TuningMixin reads but
    does not own. EsportsIsolatorPro.__init__ provides the attributes (from
    ParsedConfig / RuntimeState); the mixins named in the comments provide
    the methods. TuningMixin deliberately does NOT inherit from this
    Protocol — that would change the MRO for zero runtime benefit — it
    exists so the implicit host coupling is written down and reviewable in
    one place.
    """

    # -- config (ParsedConfig-backed) --
    auto_detect_steam: bool
    auto_detect_epic: bool
    anti_cheat_mode: str
    _disable_game_priority_boost: bool

    # -- identity --
    _self_pid: int
    _parent_pid: int

    # -- shared runtime state (RuntimeState-backed) --
    _state_lock: threading.Lock
    _touched: dict
    _entry_gen: int
    _cpu_partitions: dict
    _boosted_critical: dict
    _path_classification_cache: dict
    _process_create_times: dict  # published by DiscoveryMixin._get_processes

    # -- cross-mixin methods --
    # BaseMixin
    def _log(self, message): ...
    def _log_once(self, key, message): ...
    def _normalize_name(self, name): ...
    def _last_error_text(self): ...
    def _open_process(self, pid, access, quiet=False): ...
    def _open_thread(self, thread_id, access, quiet=False): ...
    # DiscoveryMixin
    def _get_processes(self): ...
    def _get_process_name(self, pid): ...
    def _get_process_full_path(self, pid): ...
    def _get_process_create_time(self, handle): ...
    def _is_game_name(self, name): ...
    def _is_game_name_normalized(self, normalized): ...
    def _is_protected_process_name(self, name): ...
    def _is_steam_game(self, exe_path): ...
    def _is_epic_game(self, exe_path): ...
    def _detect_protected_title(self, name): ...
    def _profile_priority_class(self, normalized): ...
    def _profile_never_jail(self, normalized): ...
    def _profile_always_jail(self, normalized): ...
    # TopologyMixin
    def _get_process_default_cpu_sets(self, handle): ...
    def _set_thread_selected_cpu_sets(self, handle, cpu_set_ids): ...
    def _apply_process_cpu_sets(self, handle, cpu_set_ids, reset_affinity_mask=True): ...
    # IfeoPowerMixin
    def _apply_ifeo_priority_fallback(self, name): ...
    # RecoveryMixin
    def _record_jail_state(self, pid): ...
    def _record_jail_states(self, pids): ...
    def _remove_jail_state(self, pid): ...
    def _remove_jail_states(self, pids): ...
    def _remove_jail_state_file(self): ...
    # RuntimeMixin
    def _begin_process_mutation(self): ...
    def _end_process_mutation(self): ...


class TuningMixin:
    """Per-process jail/boost/optimize mutations and their restore paths.

    Host contract: TuningHost (above) documents every attribute and
    cross-mixin method this mixin consumes but does not assign.
    """

    def _profile_priority_class_value(self, name):
        return _PROFILE_PRIORITY_CLASSES.get(self._profile_priority_class(self._normalize_name(name)))

    def _query_process_state(self, handle) -> ProcessState:
        state: ProcessState = {}
        priority_class = kernel32.GetPriorityClass(handle)
        if priority_class:
            state["priority_class"] = int(priority_class)

        state["cpu_set_ids"] = self._get_process_default_cpu_sets(handle)
        affinity_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        if kernel32.GetProcessAffinityMask(handle, ctypes.byref(affinity_mask), ctypes.byref(system_mask)):
            state["affinity_mask"] = int(affinity_mask.value)

        priority_boost_disabled = wintypes.BOOL()
        if kernel32.GetProcessPriorityBoost(handle, ctypes.byref(priority_boost_disabled)):
            state["priority_boost_disabled"] = bool(priority_boost_disabled.value)

        power_state = PROCESS_POWER_THROTTLING_STATE(PROCESS_POWER_THROTTLING_CURRENT_VERSION, 0, 0)
        if kernel32.GetProcessInformation(handle, PROCESS_INFORMATION_CLASS_POWER_THROTTLING, ctypes.byref(power_state), ctypes.sizeof(power_state)):
            state["power_control_mask"] = int(power_state.ControlMask)
            state["power_state_mask"] = int(power_state.StateMask)

        page_info = PAGE_PRIORITY_INFORMATION()
        return_length = wintypes.ULONG()
        status = ntdll.NtQueryInformationProcess(handle, PROCESS_INFORMATION_CLASS_PAGE_PRIORITY, ctypes.byref(page_info), ctypes.sizeof(page_info), ctypes.byref(return_length))
        if nt_success(status):
            state["page_priority"] = int(page_info.PagePriority)

        io_priority = wintypes.ULONG()
        status = ntdll.NtQueryInformationProcess(handle, PROCESS_INFORMATION_CLASS_IO_PRIORITY, ctypes.byref(io_priority), ctypes.sizeof(io_priority), ctypes.byref(return_length))
        if nt_success(status):
            state["io_priority"] = int(io_priority.value)
        return state

    def _remember_process_state(self, pid, handle, name, source="unknown"):
        pid = int(pid)
        create_time = self._get_process_create_time(handle)
        new_name = self._normalize_name(name)
        # WHY: Query process state OUTSIDE the lock. _query_process_state performs
        # 6+ Win32/NT API calls (GetPriorityClass, GetProcessAffinityMask, etc.)
        # that can take 50-1200ms total when anti-cheat minifilters (Vanguard, EAC)
        # are hooked into the kernel callback chain. Holding _state_lock during
        # those calls blocks the entire monitor thread and any concurrent restore.
        needs_snapshot = False
        with self._state_lock:
            entry = self._touched.get(pid)
            if entry:
                saved_ct = entry.get("create_time", 0)
                saved_name = entry.get("name", "")
                ct_known = saved_ct != 0 and create_time != 0
                # WHY: PID-reuse detection has TWO complementary guards:
                # 1. Strict guard: both create_times known AND different.
                # 2. Fallback guard: at least one create_time unknown
                #    (GetProcessTimes denied) AND both names are known AND
                #    differ. Without this fallback the entry sticks across
                #    PID reuse whenever the kernel denies the time read,
                #    and stale state from the old process gets applied to
                #    the new occupant of the PID slot.
                if ct_known and saved_ct != create_time:
                    self._touched.pop(pid, None)
                elif (not ct_known) and saved_name and new_name and saved_name != new_name:
                    self._touched.pop(pid, None)
            if pid not in self._touched:
                needs_snapshot = True
        # WHY: Perform the expensive Win32 queries with no lock held.
        if needs_snapshot:
            state = self._query_process_state(handle)
            with self._state_lock:
                # WHY: Re-check after releasing and re-acquiring the lock. Another
                # thread may have created an entry for this PID in the meantime.
                if pid not in self._touched:
                    self._entry_gen += 1
                    entry: TouchedEntry = {
                        "name": new_name,
                        "create_time": create_time,
                        "state": state,
                        "threads": {},
                        "source": source,
                        "gen": self._entry_gen,
                    }
                    self._touched[pid] = entry

    def _restore_thread_state(self, pid, thread_id):
        pid = int(pid)
        thread_id = int(thread_id)
        with self._state_lock:
            entry = self._touched.get(pid)
            thread_state = dict(entry.get("threads", {}).get(thread_id, {})) if entry else {}
        if not thread_state:
            return False

        handle = self._open_thread(thread_id, THREAD_QUERY_LIMITED_INFORMATION | THREAD_SET_LIMITED_INFORMATION | THREAD_SET_INFORMATION, quiet=True)
        if not handle:
            with self._state_lock:
                entry = self._touched.get(pid)
                if entry:
                    entry.get("threads", {}).pop(thread_id, None)
            return False

        # WHY: Track whether ALL restore steps succeeded. Several win32 calls
        # below (SetThreadGroupAffinity, SetThreadIdealProcessorEx, etc.)
        # silently return False on failure rather than raising. The previous
        # finally block always popped the saved state, so a partial-failure
        # left us with NO recovery info on the next attempt. Now we only pop
        # on full success; on partial failure we keep the snapshot so a later
        # _restore_thread_state retry can try again.
        all_ok = True
        try:
            if not self._set_thread_selected_cpu_sets(handle, thread_state.get("cpu_set_ids", [])):
                all_ok = False
            if thread_state.get("priority") is not None:
                if not kernel32.SetThreadPriority(handle, int(thread_state["priority"])):
                    all_ok = False
            if thread_state.get("ideal_processor"):
                processor = thread_state["ideal_processor"]
                processor_number = PROCESSOR_NUMBER(int(processor["group"]), int(processor["number"]), 0)
                if not kernel32.SetThreadIdealProcessorEx(handle, ctypes.byref(processor_number), None):
                    all_ok = False
            if thread_state.get("group_affinity"):
                affinity = thread_state["group_affinity"]
                group_affinity = GROUP_AFFINITY(ctypes.c_size_t(int(affinity["mask"])), wintypes.WORD(int(affinity["group"])), (wintypes.WORD * 3)(0, 0, 0))
                if not kernel32.SetThreadGroupAffinity(handle, ctypes.byref(group_affinity), None):
                    all_ok = False
            return all_ok
        finally:
            kernel32.CloseHandle(handle)
            if all_ok:
                with self._state_lock:
                    entry = self._touched.get(pid)
                    if entry:
                        entry.get("threads", {}).pop(thread_id, None)

    def _restore_threads_for_process(self, pid):
        with self._state_lock:
            entry = self._touched.get(int(pid))
            thread_ids = list(entry.get("threads", {}).keys()) if entry else []
        for thread_id in thread_ids:
            self._restore_thread_state(pid, thread_id)

    def _set_process_power_throttling(self, handle, enabled):
        state_mask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED if enabled else 0
        state = PROCESS_POWER_THROTTLING_STATE(PROCESS_POWER_THROTTLING_CURRENT_VERSION, PROCESS_POWER_THROTTLING_EXECUTION_SPEED, state_mask)
        if not kernel32.SetProcessInformation(handle, PROCESS_INFORMATION_CLASS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)):
            raise OSError(f"SetProcessInformation failed: {self._last_error_text()}")

    def _set_process_page_priority(self, handle, page_priority, exact=False):
        # WHY (item 7): When APPLYING the jail's reduced page priority we clamp
        # into [MINIMUM, NORMAL] so we never accidentally RAISE a process's page
        # priority. But when RESTORING a captured original value we must write
        # it back EXACTLY — Windows page priorities range 0-7 and a process that
        # was originally at 6 or 7 would otherwise be permanently demoted to 5.
        # exact=True is used only on the restore path.
        if exact:
            page_value = max(0, min(7, int(page_priority)))
        else:
            page_value = max(PAGE_PRIORITY_MINIMUM, min(PAGE_PRIORITY_NORMAL, int(page_priority)))
        page_info = PAGE_PRIORITY_INFORMATION(page_value)
        status = ntdll.NtSetInformationProcess(handle, PROCESS_INFORMATION_CLASS_PAGE_PRIORITY, ctypes.byref(page_info), ctypes.sizeof(page_info))
        if not nt_success(status):
            if ctypes.c_ulong(status).value == 0xC0000022:
                # WHY: STATUS_ACCESS_DENIED is silently absorbed because some
                # protected processes (anti-cheat workers, MSI installer
                # services) deny page-priority writes by design. We log ONCE
                # so the operator can see the diagnostic without flooding.
                self._log_once(("page_priority_denied", int(page_priority)),
                               f"[INFO] PagePriority write returned STATUS_ACCESS_DENIED for at least one process (page_priority={int(page_priority)}).")
                return
            raise OSError(f"NtSetInformationProcess(PagePriority) failed: 0x{ctypes.c_ulong(status).value:08X}")

    def _set_process_io_priority(self, handle, io_priority):
        priority = wintypes.ULONG(int(io_priority))
        status = ntdll.NtSetInformationProcess(handle, PROCESS_INFORMATION_CLASS_IO_PRIORITY, ctypes.byref(priority), ctypes.sizeof(priority))
        if not nt_success(status):
            if ctypes.c_ulong(status).value == 0xC0000022:
                self._log_once(("io_priority_denied", int(io_priority)),
                               f"[INFO] IoPriority write returned STATUS_ACCESS_DENIED for at least one process (io_priority={int(io_priority)}).")
                return
            raise OSError(f"NtSetInformationProcess(IoPriority) failed: 0x{ctypes.c_ulong(status).value:08X}")

    def _log_restore_access_issue(self, pid, entry_name, entry_source, operation):
        winerror = ctypes.get_last_error()
        if entry_source == "optimize_game" and winerror == 5:
            self._log_once(
                ("restore_game_blocked", operation, entry_name),
                f"[INFO] VAC/anti-cheat blocked {operation} restore for {entry_name} (pid={pid}).",
            )
            return
        self._log_once(
            (f"restore_{operation}", pid),
            f"[WARN] {operation} failed for pid={pid} ({entry_name}): {self._last_error_text()}",
        )

    def _restore_process(self, pid, deferred_jail_removals=None):
        pid = int(pid)

        with self._state_lock:
            entry = self._touched.get(pid)
            if not entry:
                return False
            state = dict(entry.get("state", {}))
            saved_create_time = entry.get("create_time", 0)
            entry_name = entry.get("name", "unknown")
            entry_source = entry.get("source", "")
            # WHY: Capture the identity of the entry we are restoring so the
            # finally block can verify it hasn't been replaced by a concurrent
            # _jail_process call between now and the cleanup below.
            original_entry_gen = entry.get("gen", 0)

        handle = self._open_process(pid, PROCESS_SET_INFORMATION | PROCESS_SET_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION, quiet=True)
        if not handle:
            self._log(f"[RESTORE] Cannot open pid={pid} ({entry_name}) for restoration — process may have exited.")
            with self._state_lock:
                # WHY: Only remove if the entry is still the same object we read.
                # A concurrent _jail_process may have replaced it with a new entry.
                current = self._touched.get(pid)
                if current is not None and current.get("gen", 0) == original_entry_gen:
                    self._touched.pop(pid, None)
            return False

        restore_failed = False
        try:
            current_create_time = self._get_process_create_time(handle)
            # WHY: Only skip restoration when BOTH create times are known
            # (non-zero) AND they differ — meaning PID reuse occurred. The old
            # logic used `saved == 0 OR current == 0 OR saved != current` which
            # incorrectly skipped restoration whenever GetProcessTimes failed
            # (returns 0 on access-denied), silently leaving processes stuck at
            # IDLE_PRIORITY_CLASS with EcoQoS permanently enabled.
            pid_reuse = False
            if saved_create_time != 0 and current_create_time != 0 and saved_create_time != current_create_time:
                pid_reuse = True
                self._log(f"[RESTORE] PID reuse detected for pid={pid} ({entry_name}): saved_ct={saved_create_time}, current_ct={current_create_time}. Skipping.")
            elif saved_create_time == 0 or current_create_time == 0:
                # WHY: Fallback PID-reuse check when GetProcessTimes is denied
                # for either snapshot. Compare process names: if both are
                # known and differ, this is almost certainly a different
                # process occupying the reused PID slot.
                current_name = self._normalize_name(self._get_process_name(pid))
                if current_name and entry_name and current_name != entry_name:
                    pid_reuse = True
                    self._log(f"[RESTORE] Likely PID reuse for pid={pid}: was '{entry_name}', now '{current_name}'. Skipping.")
            if pid_reuse:
                with self._state_lock:
                    # WHY: Same identity guard — don't delete a freshly-jailed entry.
                    current = self._touched.get(pid)
                    if current is not None and current.get("gen", 0) == original_entry_gen:
                        self._touched.pop(pid, None)
                return False

            self._restore_threads_for_process(pid)

            restored_attrs = []

            cpu_set_ids = state.get("cpu_set_ids", [])
            reset_affinity_mask = entry_source != "optimize_game" or bool(cpu_set_ids)
            if self._apply_process_cpu_sets(handle, cpu_set_ids, reset_affinity_mask=reset_affinity_mask):
                restored_attrs.append("cpu_sets")
            elif entry_source == "jail":
                restore_failed = True
            if "affinity_mask" in state and reset_affinity_mask:
                if kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(state["affinity_mask"])):
                    restored_attrs.append("affinity")
                else:
                    if entry_source == "jail":
                        restore_failed = True
                    self._log_restore_access_issue(pid, entry_name, entry_source, "SetProcessAffinityMask")
            if "priority_boost_disabled" in state:
                if kernel32.SetProcessPriorityBoost(handle, bool(state["priority_boost_disabled"])):
                    restored_attrs.append("priority_boost")
                else:
                    if entry_source == "jail":
                        restore_failed = True
                    self._log_restore_access_issue(pid, entry_name, entry_source, "SetProcessPriorityBoost")
            if "priority_class" in state and state["priority_class"]:
                if kernel32.SetPriorityClass(handle, state["priority_class"]):
                    restored_attrs.append(f"priority=0x{state['priority_class']:X}")
                else:
                    if entry_source == "jail":
                        restore_failed = True
                    self._log_once(("restore_priority", pid), f"[WARN] SetPriorityClass failed for pid={pid} ({entry_name}): {self._last_error_text()}")

            # WHY: Restore the original EcoQoS / power throttling state. When
            # _jail_process enables EcoQoS it sets ControlMask=EXECUTION_SPEED,
            # StateMask=EXECUTION_SPEED. To UNDO that, we must explicitly call
            # SetProcessInformation with ControlMask=EXECUTION_SPEED and
            # StateMask=0 — which means "I am managing the EXECUTION_SPEED
            # flag and I want it OFF." Setting ControlMask=0 would only mean
            # "let the system decide" and does NOT reliably clear a previously-
            # enabled throttle. If the original snapshot had ControlMask=0
            # (process never explicitly set throttling), we still must use
            # EXECUTION_SPEED as the ControlMask to force-disable it.
            original_control = state.get("power_control_mask", 0)
            original_state = state.get("power_state_mask", 0)
            if original_control & PROCESS_POWER_THROTTLING_EXECUTION_SPEED:
                # Original process explicitly managed throttling — restore exactly
                restore_control = original_control
                restore_state = original_state
            else:
                # Original process never set throttling — explicitly disable it
                restore_control = PROCESS_POWER_THROTTLING_EXECUTION_SPEED
                restore_state = 0
            power_state = PROCESS_POWER_THROTTLING_STATE(PROCESS_POWER_THROTTLING_CURRENT_VERSION, restore_control, restore_state)
            if kernel32.SetProcessInformation(handle, PROCESS_INFORMATION_CLASS_POWER_THROTTLING, ctypes.byref(power_state), ctypes.sizeof(power_state)):
                restored_attrs.append(f"ecoqos(ctrl=0x{restore_control:X},state=0x{restore_state:X})")
            else:
                if entry_source == "jail":
                    restore_failed = True
                self._log_once(("restore_ecoqos", pid), f"[WARN] Failed to restore EcoQoS for pid={pid} ({entry_name}): {self._last_error_text()}")

            if "page_priority" in state:
                try:
                    # WHY (item 7): exact=True so an original page priority of
                    # 6 or 7 is restored verbatim instead of being clamped to 5.
                    self._set_process_page_priority(handle, state["page_priority"], exact=True)
                    restored_attrs.append("page_priority")
                except OSError:
                    pass
            if "io_priority" in state:
                try:
                    self._set_process_io_priority(handle, state["io_priority"])
                    restored_attrs.append("io_priority")
                except OSError:
                    pass
            self._log(f"[RESTORE] pid={pid} ({entry_name}): {', '.join(restored_attrs)}")
            return not restore_failed
        finally:
            kernel32.CloseHandle(handle)
            remove_jail_state = False
            with self._state_lock:
                # WHY: Only pop if the entry hasn't been replaced by a concurrent
                # _jail_process call. If a new entry was created for this PID while
                # we were restoring, we must NOT delete it — that would leave the
                # process permanently stuck at IDLE_PRIORITY_CLASS with throttling
                # enabled and no record to restore from.
                current = self._touched.get(pid)
                if current is not None and current.get("gen", 0) == original_entry_gen:
                    if not restore_failed:
                        remove_jail_state = current.get("source") == "jail"
                        self._touched.pop(pid, None)
            if remove_jail_state:
                # Bulk callers pass a collector so N restores cost one batched
                # file rewrite (_remove_jail_states) instead of N fsync cycles.
                if deferred_jail_removals is not None:
                    deferred_jail_removals.append(pid)
                else:
                    self._remove_jail_state(pid)

    def _restore_all_processes(self):
        with self._state_lock:
            total_tracked = len(self._touched)
        if total_tracked > 0:
            self._log(f"[RESTORE] Beginning restoration of {total_tracked} tracked processes...")
        restored_pids = set()
        failed_pids = set()
        # WHY: _restore_process pops the entry from _touched on both success
        # and most failures (via its finally block). A naive retry loop that
        # re-reads _touched would never see the failed PIDs again. Instead,
        # we do a single pass: attempt each PID once and track outcomes.
        # Entries that survive in _touched after our pass were re-created by
        # a concurrent _jail_process (different gen) — those are legitimate
        # new entries, not restore failures.
        with self._state_lock:
            entries = [
                (pid, entry.get("gen", 0))
                for pid, entry in self._touched.items()
            ]
        deferred_jail_removals = []
        for pid, entry_gen in entries:
            try:
                if self._restore_process(pid, deferred_jail_removals=deferred_jail_removals):
                    restored_pids.add(pid)
                else:
                    failed_pids.add(pid)
            except Exception as exc:
                self._log(f"[ERROR] Failed to restore pid={pid}: {exc}")
                failed_pids.add(pid)
                # WHY: _restore_process.finally already pops the entry when
                # it can. Only force-pop here if the entry somehow survived
                # (e.g. exception before _restore_process was entered).
                with self._state_lock:
                    current = self._touched.get(pid)
                    if current is not None and current.get("gen", 0) == entry_gen:
                        self._touched.pop(pid, None)
        with self._state_lock:
            remaining = len(self._touched)
        if remaining > 0:
            self._log(f"[WARN] {remaining} entries remain in _touched (likely re-jailed by concurrent activity).")
        if total_tracked > 0:
            self._log(f"[RESTORE] Complete: {len(restored_pids)} restored, {len(failed_pids - restored_pids)} failed/skipped.")
        # WHY: Only delete the crash-recovery file when every restore succeeded.
        # _restore_process deliberately keeps the on-disk record for a failed
        # PID so the next elevated launch can retry; an unconditional delete
        # here would wipe that record (same bug class as the IFEO backup fix
        # in _restore_ifeo_priorities). With failures present, drop only the
        # successfully-restored PIDs in one batched rewrite.
        if not (failed_pids - restored_pids):
            self._remove_jail_state_file()
        elif deferred_jail_removals:
            self._remove_jail_states(deferred_jail_removals)

    def _jail_process(self, pid, name=None, force=False, record_state=True, expected_create_time=0):
        # Public contract (pinned by tests, _isolate_background, and the
        # foreground-transition path): the impl's JailOutcome maps to a
        # legacy tri-state:
        #   JailOutcome.JAILED  → True  (jailed successfully)
        #   JailOutcome.DENIED  → None  (OpenProcess / priority write denied)
        #   JailOutcome.SKIPPED → False (caller-side gate skip)
        if not self._begin_process_mutation():
            return False
        try:
            outcome = self._jail_process_impl(
                pid,
                name=name,
                force=force,
                record_state=record_state,
                expected_create_time=expected_create_time,
            )
        finally:
            self._end_process_mutation()
        if outcome is JailOutcome.JAILED:
            return True
        if outcome is JailOutcome.DENIED:
            return None
        return False

    def _jail_process_impl(self, pid, name=None, force=False, record_state=True, expected_create_time=0):
        pid = int(pid)
        if pid in (0, 4, self._self_pid, self._parent_pid):
            return JailOutcome.SKIPPED

        normalized_name = self._normalize_name(name) or self._get_process_name(pid)
        if not normalized_name:
            return JailOutcome.SKIPPED
        if self._is_protected_process_name(normalized_name) or self._profile_never_jail(normalized_name):
            return JailOutcome.SKIPPED
        if self._is_game_name(normalized_name) and not self._profile_always_jail(normalized_name):
            return JailOutcome.SKIPPED

        handle = self._open_process(pid, PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_INFORMATION | PROCESS_SET_LIMITED_INFORMATION, quiet=not force)
        if not handle:
            # WHY: OpenProcess failed (typically access denied for protected
            # / SYSTEM-owned processes). DENIED distinguishes this outcome
            # from the SKIPPED "gated" outcomes above.
            return JailOutcome.DENIED

        try:
            # WHY: PID-reuse guard, symmetric with _restore_process. The handle
            # is pinned to the process that actually occupies the PID right now;
            # its creation time identifies it. If the caller told us which
            # process it expected (expected_create_time) and the live process
            # has a different, known creation time, the PID was recycled — we
            # would be jailing the wrong (possibly game/anti-cheat) process
            # under a stale name. Skip without mutating.
            actual_create_time = self._get_process_create_time(handle)
            if (
                expected_create_time
                and actual_create_time
                and expected_create_time != actual_create_time
            ):
                self._log_once(
                    ("jail_pid_reuse", pid, normalized_name),
                    f"[INFO] Skipping jail for pid={pid} ({normalized_name}): PID reuse "
                    f"(expected_ct={expected_create_time}, current_ct={actual_create_time}).",
                )
                return JailOutcome.SKIPPED
            # WHY: Snapshot the original state INSIDE the try/finally so a
            # failure inside _remember_process_state (e.g., ctypes alloc
            # error during _query_process_state) cannot leak the handle.
            self._remember_process_state(pid, handle, normalized_name, source="jail")
            background_cores = self._cpu_partitions.get("background", [])
            if background_cores:
                self._apply_process_cpu_sets(handle, background_cores)
            try:
                self._set_process_power_throttling(handle, enabled=True)
            except OSError:
                pass
            if not kernel32.SetPriorityClass(handle, IDLE_PRIORITY_CLASS):
                self._log_once(
                    ("jail_priority_denied", pid, normalized_name),
                    f"[INFO] Access denied setting idle priority for pid={pid} ({normalized_name}).",
                )
                self._restore_process(pid)
                return JailOutcome.DENIED
            try:
                self._set_process_page_priority(handle, PAGE_PRIORITY_MINIMUM)
            except OSError:
                pass
            try:
                self._set_process_io_priority(handle, IO_PRIORITY_VERY_LOW)
            except OSError:
                pass
            if record_state:
                self._record_jail_state(pid)
            return JailOutcome.JAILED
        except OSError as exc:
            if getattr(exc, 'winerror', None) != 5 and "Access is denied" not in str(exc) and "Отказано в доступе" not in str(exc):
                self._log_once(("jail", pid), f"[WARN] Failed to jail pid={pid} ({normalized_name}): {exc}")
            # WHY: DENIED signals a true failure to callers (vs. SKIPPED,
            # which means "skipped at the gate"). _isolate_background uses
            # this distinction to count failures separately from gates.
            return JailOutcome.DENIED
        finally:
            kernel32.CloseHandle(handle)

    def _boost_foreground(self, pid):
        if not self._begin_process_mutation():
            return False
        try:
            return self._boost_foreground_impl(pid)
        finally:
            self._end_process_mutation()

    def _boost_foreground_impl(self, pid):
        pid = int(pid)
        if pid in (0, 4, self._self_pid, self._parent_pid):
            return False

        name = self._get_process_name(pid)
        if not name:
            return False
        if self._is_protected_process_name(name) and not self._is_game_name(name):
            return False
        protected_title = self._detect_protected_title(name)
        if protected_title and self.anti_cheat_mode == "conservative":
            self._log_once(("protected_foreground_skip", name), f"[INFO] Conservative anti-cheat policy skipped direct tuning for {name}.")
            return False

        handle = self._open_process(pid, PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_INFORMATION | PROCESS_SET_LIMITED_INFORMATION, quiet=True)
        if not handle:
            return False

        try:
            if not self._pid_identity_matches_snapshot(pid, handle, name, "foreground"):
                return False
            # WHY: Snapshot inside the try/finally so a failure during
            # state capture cannot leak the open handle.
            self._remember_process_state(pid, handle, name, source="foreground")
            is_game = self._is_game_name(name)
            # WHY: Games run with full default affinity. We intentionally
            # do NOT call _apply_process_cpu_sets for games.
            # WHY: Non-game foreground apps may have been jailed (pinned to
            # background CPU sets). Clear the CPU-set restriction so the
            # priority boost is effective on all cores while the app is in
            # the foreground. When it loses focus, _jail_process re-pins it.
            if not is_game:
                self._apply_process_cpu_sets(handle, [])
            try:
                self._set_process_power_throttling(handle, enabled=False)
            except OSError:
                pass
            priority_override = self._profile_priority_class_value(name)
            if priority_override is not None or not (is_game and self._disable_game_priority_boost):
                target_priority = priority_override or (HIGH_PRIORITY_CLASS if is_game else ABOVE_NORMAL_PRIORITY_CLASS)
                set_priority_ok = bool(kernel32.SetPriorityClass(handle, target_priority))
                kernel32.SetProcessPriorityBoost(handle, False)
                if is_game and not set_priority_ok and target_priority == HIGH_PRIORITY_CLASS:
                    self._apply_ifeo_priority_fallback(name)
            try:
                self._set_process_page_priority(handle, PAGE_PRIORITY_NORMAL)
            except OSError:
                pass
            try:
                self._set_process_io_priority(handle, IO_PRIORITY_NORMAL)
            except OSError:
                pass

            if is_game:
                self._log(f"[FOCUS] Boosted foreground game: {name}")
            return True
        except OSError as exc:
            self._log_once(("boost", pid), f"[WARN] Failed to boost pid={pid} ({name}): {exc}")
            return False
        finally:
            kernel32.CloseHandle(handle)

    def _boost_system_critical(self):
        critical_services = {
            "dwm.exe",
            "audiodg.exe",
            "nvcontainer.exe",
            "nvsphelper64.exe",
            "amdrsserv.exe"
        }
        current_critical_pids = set()
        for pid, name in self._get_processes():
            if name not in critical_services:
                continue
            current_critical_pids.add(pid)
            handle = self._open_process(pid, PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION, quiet=True)
            if not handle:
                continue
            try:
                original_priority = kernel32.GetPriorityClass(handle)
                if not kernel32.SetPriorityClass(handle, HIGH_PRIORITY_CLASS):
                    self._log_once(
                        ("boost_critical_priority_denied", pid, name),
                        f"[INFO] Access denied boosting priority for {name} (pid={pid}).",
                    )
                    continue
                if original_priority and original_priority != HIGH_PRIORITY_CLASS:
                    self._boosted_critical[pid] = int(original_priority)
            finally:
                kernel32.CloseHandle(handle)
        for stale_pid in list(self._boosted_critical.keys()):
            if stale_pid not in current_critical_pids:
                self._boosted_critical.pop(stale_pid, None)

    def _restore_system_critical(self):
        for pid, original_priority in list(self._boosted_critical.items()):
            handle = self._open_process(pid, PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION, quiet=True)
            if not handle:
                continue
            try:
                if not kernel32.SetPriorityClass(handle, original_priority):
                    self._log_once(
                        ("restore_critical_priority_denied", pid),
                        f"[WARN] SetPriorityClass failed restoring critical pid={pid}: {self._last_error_text()}",
                    )
            finally:
                kernel32.CloseHandle(handle)
        self._boosted_critical.clear()

    def _isolate_background(self, max_new=None, log_names=False, processes=None):
        touched = 0
        skipped = 0
        denied = 0
        deferred = 0
        touched_names = []
        touched_pids = []
        process_list = processes if processes is not None else self._get_processes()
        with self._state_lock:
            already_jailed = {
                pid for pid, entry in self._touched.items() if entry.get("source") == "jail"
            }
        is_game = self._is_game_name_normalized
        is_protected = self._is_protected_process_name
        for pid, exe_name in process_list:
            if pid in (0, 4, self._self_pid, self._parent_pid):
                continue
            if not exe_name or is_protected(exe_name) or self._profile_never_jail(exe_name):
                continue
            if is_game(exe_name) and not self._profile_always_jail(exe_name):
                continue
            if pid in already_jailed:
                skipped += 1
                continue
            if max_new is not None and touched >= max_new:
                deferred += 1
                continue
            # WHY: _jail_process now returns a tri-state:
            #   True  → jailed successfully
            #   None  → OpenProcess or registry write denied
            #   False → caller-side skip (PID was 0/4/self, name empty, etc.)
            # Distinguishing "denied" from "jailed" lets the operator tell a
            # healthy run (where everything we tried succeeded) apart from a
            # session that is silently failing on dozens of processes.
            expected_ct = int(getattr(self, "_process_create_times", {}).get(pid, 0) or 0)
            result = self._jail_process(
                pid, name=exe_name, force=True, record_state=False, expected_create_time=expected_ct
            )
            if result is True:
                touched += 1
                touched_pids.append(pid)
                touched_names.append(exe_name)
            elif result is None:
                denied += 1
        if touched_pids:
            self._record_jail_states(touched_pids)
        if touched > 0 or deferred > 0:
            denied_text = f", {denied} denied" if denied else ""
            deferred_text = f", {deferred} deferred" if deferred else ""
            self._log(f"[INFO] Throttled {touched} new background processes ({skipped} already jailed{denied_text}{deferred_text}).")
        if log_names and touched_names:
            counts = {}
            ordered_names = []
            for name in touched_names:
                if name not in counts:
                    ordered_names.append(name)
                    counts[name] = 0
                counts[name] += 1
            summary = ", ".join(
                f"{name} x{counts[name]}" if counts[name] > 1 else name
                for name in ordered_names
            )
            if deferred:
                summary = f"{summary}; deferred={deferred}"
            self._log(f"[INFO] Newly throttled: {summary}.")
        return {"touched": touched, "skipped": skipped, "denied": denied, "deferred": deferred, "names": touched_names}

    def _find_game_process_entries(self, processes=None):
        # WHY: Use combined set for fast O(1) lookup by name. Only fall back to
        # expensive full-path checks for processes not matched by name.
        result = {}
        unknown = []
        process_list = processes if processes is not None else self._get_processes()
        for pid, exe_name in process_list:
            if not exe_name or pid in (0, 4, self._self_pid, self._parent_pid):
                continue
            if self._is_game_name_normalized(exe_name):
                result[int(pid)] = exe_name
            elif self.auto_detect_steam or self.auto_detect_epic:
                unknown.append((pid, exe_name))
        # WHY: Only call _get_process_full_path for processes not matched by name.
        # This avoids ~300 OpenProcess+QueryFullProcessImageNameW calls per poll
        # cycle that the naive approach would incur.
        for pid, exe_name in unknown:
            if pid in (0, 4, self._self_pid, self._parent_pid):
                continue
            create_time = int(getattr(self, "_process_create_times", {}).get(pid, 0) or 0)
            cache_key = (int(pid), create_time, exe_name)
            if create_time:
                cached = self._path_classification_cache.get(cache_key)
                if cached is not None:
                    if cached:
                        result[int(pid)] = exe_name
                    continue
            path = self._get_process_full_path(pid)
            if not path:
                # WHY: Do NOT cache as non-game when the path lookup failed.
                # Empty path means access-denied or process exited — not that
                # the exe is definitively not a game. Caching here would cause
                # a legitimate Steam/Epic game with a generic exe name to be
                # permanently skipped until the cache is cleared at 100 entries.
                continue
            is_path_game = False
            if self.auto_detect_steam and self._is_steam_game(path):
                is_path_game = True
                result[int(pid)] = exe_name
            elif self.auto_detect_epic and self._is_epic_game(path):
                is_path_game = True
                result[int(pid)] = exe_name
            if create_time:
                self._path_classification_cache[cache_key] = is_path_game
                if len(self._path_classification_cache) > 1000:
                    self._path_classification_cache.clear()
        return result

    def _find_game_processes(self, processes=None):
        return list(self._find_game_process_entries(processes).keys())

    def _optimize_game_with_state(self, pid, name=None, classified_as_game=False):
        if not self._begin_process_mutation():
            return TuningState.SKIPPED
        try:
            return self._optimize_game_impl(
                pid,
                name=name,
                classified_as_game=classified_as_game,
            )
        finally:
            self._end_process_mutation()

    def _optimize_game_impl(self, pid, name=None, classified_as_game=False):
        pid = int(pid)
        snapshot_name_supplied = bool(name)
        name = self._normalize_name(name) if name else self._get_process_name(pid)
        if not classified_as_game and not self._is_game_name_normalized(name):
            return TuningState.FAILED
        protected_title = self._detect_protected_title(name)
        if protected_title and self.anti_cheat_mode == "conservative":
            self._log_once(("protected_game_skip", name), f"[INFO] Conservative anti-cheat policy skipped direct game tuning for {name}.")
            return TuningState.SKIPPED

        handle = self._open_process(pid, PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_INFORMATION | PROCESS_SET_LIMITED_INFORMATION, quiet=True)
        if not handle:
            return TuningState.BLOCKED

        try:
            if not self._pid_identity_matches_snapshot(
                pid,
                handle,
                name,
                "optimize_game",
                trust_snapshot_name=snapshot_name_supplied,
            ):
                return TuningState.FAILED
            # WHY: Snapshot inside the try/finally so a failure during
            # state capture cannot leak the open handle.
            self._remember_process_state(pid, handle, name, source="optimize_game")
            # WHY: Game runs with full default affinity. We intentionally
            # do NOT call _apply_process_cpu_sets for games.
            priority_override = self._profile_priority_class_value(name)
            if priority_override is not None or not self._disable_game_priority_boost:
                # WHY: SetProcessPriorityBoost(False) disables priority decay so
                # the game's threads keep their dynamic-priority bumps. We do not
                # branch on the return value — if it fails for some weird reason,
                # the rest of the optimization is still worth applying.
                kernel32.SetProcessPriorityBoost(handle, False)
                target_priority = priority_override or HIGH_PRIORITY_CLASS
                set_priority_ok = bool(kernel32.SetPriorityClass(handle, target_priority))
                if not set_priority_ok and target_priority == HIGH_PRIORITY_CLASS:
                    self._apply_ifeo_priority_fallback(name)
            try:
                self._set_process_power_throttling(handle, enabled=False)
            except OSError:
                pass
            try:
                self._set_process_page_priority(handle, PAGE_PRIORITY_NORMAL)
            except OSError as e:
                self._log_once(("page_prio", pid), f"[WARN] PagePriority failed: {e}")
            try:
                self._set_process_io_priority(handle, IO_PRIORITY_NORMAL)
            except OSError as e:
                self._log_once(("io_prio", pid), f"[WARN] IoPriority failed: {e}")

            self._log(f"[GAME] Optimized running game: {name} (pid={pid})")
            return TuningState.APPLIED
        except OSError as exc:
            self._log_once(("optimize_game", pid), f"[WARN] Failed to optimize game pid={pid}: {exc}")
            return TuningState.FAILED
        finally:
            kernel32.CloseHandle(handle)

    def _pid_identity_matches_snapshot(self, pid, handle, expected_name, operation, trust_snapshot_name=False):
        expected_create_time = int(getattr(self, "_process_create_times", {}).get(int(pid), 0) or 0)
        current_create_time = self._get_process_create_time(handle)
        if expected_create_time and current_create_time and expected_create_time != current_create_time:
            self._log_once(
                (f"{operation}_pid_reuse", int(pid), expected_name),
                f"[INFO] Skipping {operation} for pid={pid} ({expected_name}): PID reuse detected.",
            )
            return False
        if (not expected_create_time or not current_create_time) and not trust_snapshot_name:
            current_name = self._normalize_name(self._get_process_name(pid))
            if current_name and expected_name and current_name != expected_name:
                self._log_once(
                    (f"{operation}_pid_name_reuse", int(pid), expected_name),
                    f"[INFO] Skipping {operation} for pid={pid}: was '{expected_name}', now '{current_name}'.",
                )
                return False
        return True
