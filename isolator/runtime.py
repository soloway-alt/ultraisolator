"""RuntimeMixin implementation slice."""

import atexit
import ctypes
import gc
import threading
import time
from ctypes import wintypes

from .winapi import (
    CONSOLE_CTRL_HANDLER,
    CTRL_BREAK_EVENT,
    CTRL_C_EVENT,
    CTRL_CLOSE_EVENT,
    CTRL_LOGOFF_EVENT,
    CTRL_SHUTDOWN_EVENT,
    ERROR_ALREADY_EXISTS,
    MUTEX_NAME,
    is_process_elevated,
    kernel32,
    nt_success,
    ntdll,
    user32,
)


class RuntimeMixin:
    def _run_background_jail(self, initial=False, processes=None):
        if not self.enable_background_jailing:
            if initial:
                self._log("[INFO] Background jailing disabled by config; skipping background process priority/affinity changes.")
            return {"touched": 0, "skipped": 0, "denied": 0, "deferred": 0, "names": []}
        if not self._library_scan_ready.is_set():
            # The initial Steam/Epic scan is still populating the game caches;
            # jailing now could classify an auto-detected game as background.
            self._log_once(
                ("jail_waiting_library_scan",),
                "[INFO] Waiting for the initial game-library scan before background jailing.",
            )
            return {"touched": 0, "skipped": 0, "denied": 0, "deferred": 0, "names": []}
        return self._isolate_background(
            max_new=self.maintenance_jail_batch_size,
            log_names=True,
            processes=processes,
        )

    def _maintenance_jail_due(self, now, last_interval, last_batch, backlog):
        if backlog:
            return now - last_batch >= self.maintenance_jail_batch_cooldown_s
        return now - last_interval >= self.maintenance_jail_interval_s

    def _process_game_pid_transitions(self, active_games, current_game_pids, pending_closed, now):
        # WHY: A single missed SPI poll must not restore a still-running game (CS2/VAC).
        new_games = current_game_pids - active_games
        pending_closed = dict(pending_closed)
        for pid in active_games - current_game_pids:
            if pid not in pending_closed:
                pending_closed[pid] = now
        for pid in list(pending_closed.keys()):
            if pid in current_game_pids:
                pending_closed.pop(pid, None)
        confirmed_closed = []
        if self.game_close_debounce_s <= 0:
            confirmed_closed = list(pending_closed.keys())
            pending_closed.clear()
        else:
            for pid, first_seen in list(pending_closed.items()):
                if now - first_seen >= self.game_close_debounce_s:
                    confirmed_closed.append(pid)
                    pending_closed.pop(pid, None)
        retained_games = (active_games | current_game_pids) - set(confirmed_closed)
        return new_games, confirmed_closed, retained_games, pending_closed

    def _update_active_game_observations(self, observed_games, pending_closed, now):
        observed_games = {
            int(pid): self._normalize_name(name)
            for pid, name in dict(observed_games or {}).items()
        }
        current_game_pids = set(observed_games)
        with self._state_lock:
            active_game_pids = set(self._active_games)
            new_games, confirmed_closed, retained_games, pending_closed = self._process_game_pid_transitions(
                active_game_pids,
                current_game_pids,
                pending_closed,
                now,
            )
            for pid, name in observed_games.items():
                game = self._active_games.setdefault(pid, {
                    "pid": pid,
                    "name": name,
                    "tuning_state": "pending",
                })
                game["name"] = name
            for pid in confirmed_closed:
                self._active_games.pop(pid, None)
        return new_games, confirmed_closed, retained_games, pending_closed

    def _set_active_game_tuning_state(self, pid, tuning_state):
        with self._state_lock:
            game = self._active_games.get(int(pid))
            if game is not None:
                game["tuning_state"] = tuning_state

    def _foreground_transition_due(self, now, last_transition_time):
        return now - last_transition_time >= self._foreground_transition_debounce_s

    def _handle_foreground_transition(self, last_fg_pid, fg_pid, game_was_running):
        protected_pids = (self._self_pid, self._parent_pid)
        if last_fg_pid > 4 and last_fg_pid not in protected_pids:
            if game_was_running and self.enable_background_jailing:
                self._jail_process(last_fg_pid)
        if fg_pid > 4 and fg_pid not in protected_pids:
            name = self._get_process_name(fg_pid)
            is_game = self._is_game_name(name)
            if is_game or (game_was_running and self.enable_background_jailing):
                self._boost_foreground(fg_pid)

    def _cleanup_dead_processes(self, processes=None, game_pids=None):
        with self._state_lock:
            pids = list(self._touched.keys())
        all_processes = processes if processes is not None else self._get_processes()
        # WHY (item 5): A single failed/empty process enumeration must NOT be
        # treated as "every tracked process died". If the snapshot is empty
        # (NtQuerySystemInformation hiccup, transient failure), active_pids
        # would be empty and we would evict the ENTIRE _touched map — meaning
        # jailed processes never get restored. Skip the dead-process eviction
        # this cycle when there is no usable snapshot; the next cycle with a
        # valid snapshot will clean up genuinely-dead PIDs.
        if not all_processes:
            self._log_once(
                ("cleanup_empty_snapshot",),
                "[INFO] Skipping dead-process cleanup this cycle: process enumeration returned no entries.",
            )
            return
        active_pids = {p[0] for p in all_processes}
        # WHY: Reuse game PIDs from the monitor loop when provided to avoid
        # re-classifying every process name on the 60s cleanup path.
        if game_pids is not None:
            game_pids = set(game_pids)
        else:
            game_pids = {pid for pid, name in all_processes if self._is_game_name_normalized(name)}
        fg_pid = 0
        fg_hwnd = user32.GetForegroundWindow()
        if fg_hwnd:
            # WHY: Reuse the pre-allocated _fg_pid_dword to avoid allocating a
            # new wintypes.DWORD() on every cleanup cycle (called every 60s).
            user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(self._fg_pid_dword))
            fg_pid = self._fg_pid_dword.value

        with self._state_lock:
            for pid in pids:
                if pid not in active_pids and pid not in game_pids:
                    self._touched.pop(pid, None)
                elif pid not in game_pids and pid != fg_pid:
                    entry = self._touched.get(pid)
                    if entry:
                        entry.get("threads", {}).clear()

        with self._state_lock:
            stale_keys = [
                key for key in self._reported_failures
                if isinstance(key, tuple) and len(key) >= 2
                and isinstance(key[1], int) and key[1] not in active_pids
            ]
            for key in stale_keys:
                self._reported_failures.pop(key, None)
            self._prune_reported_failures_locked()

        # WHY: These caches grow monotonically — every unique process name seen
        # gets an entry. After an hour of gameplay with process churn (services
        # restarting, browser helpers, scheduled tasks), they can reach hundreds
        # of entries. Clearing them periodically is cheap (O(1) for set/dict)
        # and the caches rebuild on-demand within 1-2 poll cycles.
        if len(self._known_non_games) > 100:
            self._known_non_games.clear()
        if len(self._path_classification_cache) > 1000:
            self._path_classification_cache.clear()
        else:
            for key in list(self._path_classification_cache.keys()):
                if key[0] not in active_pids:
                    self._path_classification_cache.pop(key, None)
        if len(self._protected_cache) > 200:
            self._protected_cache.clear()

    def _begin_process_mutation(self):
        with self._state_lock:
            if self._shutting_down or self._shutdown_done:
                return False
            self._active_mutations += 1
            return True

    def _end_process_mutation(self):
        with self._mutation_idle:
            self._active_mutations = max(0, self._active_mutations - 1)
            if self._active_mutations == 0:
                self._mutation_idle.notify_all()

    def _wait_for_process_mutations(self):
        with self._mutation_idle:
            while self._active_mutations > 0:
                self._mutation_idle.wait()

    def _monitor_loop(self):
        last_fg_pid = 0
        active_games = set()
        last_cleanup = time.monotonic()
        power_scheme_attempted = False
        gc_disabled = False
        last_gc_sweep = time.monotonic()
        last_gc_gen0_sweep = time.monotonic()
        last_background_jail = 0.0
        last_jail_batch = 0.0
        maintenance_jail_backlog = False
        maintenance_idle_streak = 0
        game_was_running = False
        last_game_exit_time = 0.0
        pending_closed = {}
        last_known_game_pids = set()

        # WHY: Hoist attribute lookups out of the hot loop. CPython resolves
        # self.attr via __dict__ lookup + descriptor protocol on every access.
        # For attributes accessed every poll cycle (every 2s during game mode),
        # caching them as local variables eliminates ~20 dict lookups per cycle.
        # Local variable access is a single LOAD_FAST bytecode vs LOAD_ATTR.
        _self_pid = self._self_pid
        _stop_event = self._stop_event
        _fg_pid_dword = self._fg_pid_dword
        _fg_pid_byref = ctypes.byref(_fg_pid_dword)
        _GetForegroundWindow = user32.GetForegroundWindow
        _GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        _poll_active = self.poll_interval_active_s
        _poll_idle = self.poll_interval_idle_s
        _monotonic = time.monotonic
        _maintenance_jail_due = self._maintenance_jail_due

        while not _stop_event.is_set():
            # WHY (item 6): In fast shutdown (console close / logoff / OS
            # shutdown) shutdown() sets _shutting_down BEFORE restoring, but
            # does NOT join this thread. Without this gate the loop could run
            # another full cycle and re-jail / re-optimize processes AFTER
            # _restore_all_processes, leaving them throttled forever. Bail out
            # of the loop body as soon as shutdown begins so we never start new
            # per-process tuning concurrently with (or after) restore. The
            # per-process mutation paths are also gated via
            # _begin_process_mutation, but stopping here avoids wasted work and
            # closes the window between enumeration and mutation.
            if self._shutting_down:
                break
            now = _monotonic()
            processes = self._get_processes()
            if now - self._last_topology_refresh > 300.0:
                self._refresh_topology("periodic")
            # Library refreshes run on the scan worker so the poll loop —
            # responsible for game launch/exit detection and the debounced
            # restore — never stalls on filesystem walks.
            if (self.auto_detect_steam and now - self._last_steam_scan > 300.0) or (
                self.auto_detect_epic and now - self._last_epic_scan > 300.0
            ):
                self._request_library_scan()

            # An empty SPI result is an enumeration failure, not proof that every
            # process exited. Keep all observation/debounce state unchanged and
            # retry on the next poll instead of restoring a still-running game.
            if not processes:
                self._log_once(
                    ("monitor_empty_snapshot",),
                    "[INFO] Process enumeration returned no entries; keeping the last game observation.",
                )
                with self._state_lock:
                    active_games = set(self._active_games)
                next_interval = _poll_active if active_games else _poll_idle
                if _stop_event.wait(next_interval):
                    break
                continue

            cleanup_due = now - last_cleanup > 60.0
            current_game_pids = set()
            cleanup_ran = False
            try:
                observed_games = self._find_game_process_entries(processes)
                current_game_pids = set(observed_games)
                last_known_game_pids = current_game_pids
                new_games, confirmed_closed, active_games, pending_closed = self._update_active_game_observations(
                    observed_games,
                    pending_closed,
                    now,
                )
                if cleanup_due:
                    self._cleanup_dead_processes(processes, game_pids=active_games)
                    last_cleanup = now
                    cleanup_ran = True

                for pid in new_games:
                    tuning_state = self._optimize_game_with_state(
                        pid,
                        observed_games[pid],
                        classified_as_game=True,
                    )
                    self._set_active_game_tuning_state(pid, tuning_state)
                for pid in confirmed_closed:
                    self._restore_process(pid)
                    self._log(f"[GAME] Game closed: pid={pid}")

                if current_game_pids:
                    last_game_exit_time = 0.0
                    if not game_was_running:
                        game_was_running = True
                        maintenance_jail_backlog = False
                        maintenance_idle_streak = 0
                        last_background_jail = now
                        last_jail_batch = now
                        self._refresh_topology("game_mode_entry")
                        # WHY: Reset GC sweep timers when entering game mode
                        # so the next sweeps respect the configured intervals
                        # rather than firing immediately because the timers
                        # were last updated minutes/hours ago in idle mode.
                        last_gc_gen0_sweep = now
                        last_gc_sweep = now
                        self._log("==================================================")
                        if self.enable_background_jailing:
                            self._log("[INFO] Entering Game Mode. Jailing background processes...")
                        else:
                            self._log("[INFO] Entering Game Mode.")
                        stats = self._run_background_jail(initial=True, processes=processes)
                        maintenance_jail_backlog = bool(stats.get("deferred")) if isinstance(stats, dict) else False
                        self._log("==================================================")
                    # WHY: Re-jail on a dedicated interval to catch processes spawned
                    # AFTER Game Mode started. Backlog batches use batch_cooldown
                    # instead of poll_interval_active to avoid syscall storms every 2s.
                    elif self.enable_background_jailing and _maintenance_jail_due(
                        now, last_background_jail, last_jail_batch, maintenance_jail_backlog
                    ):
                        skip_quiet_maintenance = (
                            not maintenance_jail_backlog
                            and maintenance_idle_streak >= self.maintenance_skip_after_quiet_cycles
                        )
                        if skip_quiet_maintenance:
                            last_background_jail = now
                        else:
                            stats = self._run_background_jail(initial=False, processes=processes)
                            last_jail_batch = now
                            maintenance_jail_backlog = bool(stats.get("deferred")) if isinstance(stats, dict) else False
                            if isinstance(stats, dict) and stats.get("touched", 0) == 0 and stats.get("deferred", 0) == 0:
                                maintenance_idle_streak += 1
                            else:
                                maintenance_idle_streak = 0
                            if not maintenance_jail_backlog:
                                last_background_jail = now

                    if not gc_disabled:
                        gc.disable()
                        gc_disabled = True
                        self._log("[INFO] Python GC disabled to prevent micro-stutters.")
                    # WHY: Generational GC instead of full collect every 5 min.
                    # gen0 collect touches only ~500 young objects (sub-ms pause).
                    # Full collect every 10 min instead of 5 reduces the frequency
                    # of the expensive 30-50ms stop-the-world pauses that cause
                    # frame skips on 144Hz+ displays.
                    if gc_disabled:
                        if now - last_gc_gen0_sweep > 30.0:
                            gc.collect(0)
                            last_gc_gen0_sweep = now
                        if now - last_gc_sweep > self.gc_full_collect_interval_s:
                            gc.collect()
                            last_gc_sweep = now
                    if not self._power_plan_active and not power_scheme_attempted:
                        switched = self._set_preferred_power_scheme()
                        if switched and self._power_plan_active:
                            self._refresh_topology("power_scheme_switch")
                        power_scheme_attempted = True

                elif not current_game_pids:
                    if game_was_running:
                        if pending_closed:
                            last_game_exit_time = 0.0
                        elif last_game_exit_time == 0.0:
                            last_game_exit_time = now

                        if now - last_game_exit_time > self.game_exit_restore_delay_s:
                            game_was_running = False
                            self._log("==================================================")
                            self._log(
                                f"[INFO] All games closed for {self.game_exit_restore_delay_s:.0f}s. "
                                "System restored to normal stable state."
                            )
                            self._restore_all_processes()
                            self._log("==================================================")

                            if gc_disabled:
                                gc.enable()
                                gc.collect()
                                gc_disabled = False
                                self._log("[INFO] Python GC re-enabled and memory collected.")
                            if self._power_plan_active or getattr(self, "_power_scheme_set_unverified", False):
                                self._restore_power_scheme()
                            power_scheme_attempted = False
                            maintenance_jail_backlog = False
                            maintenance_idle_streak = 0

                # WHY: Reuse the pre-allocated _fg_pid_dword and its byref instead
                # of creating wintypes.DWORD() + ctypes.byref() every poll cycle.
                # On the hot path (~500 cycles/1000s of game play), this eliminates
                # 2 object allocations per cycle that become immediate garbage.
                hwnd = _GetForegroundWindow()
                if hwnd:
                    _GetWindowThreadProcessId(hwnd, _fg_pid_byref)
                    fg_pid = _fg_pid_dword.value
                    if fg_pid != last_fg_pid:
                        if self._foreground_transition_due(now, self._last_fg_transition_time):
                            self._handle_foreground_transition(last_fg_pid, fg_pid, game_was_running)
                            self._last_fg_transition_time = now
                        last_fg_pid = fg_pid
            except Exception as exc:
                # WHY: _log_once folds monitor exceptions by type plus a
                # scrubbed message fingerprint, so distinct failures remain
                # visible without letting volatile pid/path details flood logs.
                self._log_once(("monitor_exception", type(exc).__name__), f"[WARN] Monitor loop error: {exc}")
            finally:
                if cleanup_due and not cleanup_ran:
                    game_pids = last_known_game_pids if last_known_game_pids else active_games
                    self._cleanup_dead_processes(processes, game_pids=game_pids)
                    last_cleanup = now

            next_interval = _poll_active if active_games else _poll_idle
            if _stop_event.wait(next_interval):
                break

    def _start_monitoring(self):
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_thread = threading.Thread(target=self._monitor_loop, name="IsolatorMonitor", daemon=True)
        self._monitor_thread.start()

    def _set_timer_resolution(self):
        minimum = wintypes.ULONG()
        maximum = wintypes.ULONG()
        current = wintypes.ULONG()
        status = ntdll.NtQueryTimerResolution(ctypes.byref(minimum), ctypes.byref(maximum), ctypes.byref(current))
        if not nt_success(status):
            return
        new_current = wintypes.ULONG()
        status = ntdll.NtSetTimerResolution(maximum.value, True, ctypes.byref(new_current))
        if nt_success(status):
            self._timer_resolution_applied = maximum.value

    def _restore_timer_resolution(self):
        if self._timer_resolution_applied is None:
            return
        current = wintypes.ULONG()
        ntdll.NtSetTimerResolution(self._timer_resolution_applied, False, ctypes.byref(current))
        self._timer_resolution_applied = None

    def _print_capability_report(self):
        self._log("==================================================")
        self._log("Capability report")
        self._log(f"  Admin rights: {'yes' if self._is_admin else 'no'}")
        self._log(f"  Anti-cheat mode: {self.anti_cheat_mode}")
        self._log(f"  Steam auto-detect: {'ON' if self.auto_detect_steam else 'OFF'}")
        self._log(f"  Epic auto-detect: {'ON' if self.auto_detect_epic else 'OFF'}")
        self._log(f"  Background jailing: {'ON' if self.enable_background_jailing else 'OFF'}")
        self._log(f"  Game priority/IFEO boost: {'OFF' if self._disable_game_priority_boost else 'ON'}")
        self._log(f"  Timer resolution tweak: {'OFF' if self._disable_timer_resolution_tweak else 'ON'}")
        self._log(f"  Power scheme switch: {'OFF' if self._disable_power_scheme_switch else 'ON'}")
        if self._capability_notes:
            for note in self._capability_notes:
                self._log(f"  - {note}")
        else:
            self._log("  - Full feature set is available.")
        if any(self._cpu_partitions.values()):
            self._log(
                "  - CPU partitions:"
                f" game={len(self._cpu_partitions.get('game', []))}"
                f" background={len(self._cpu_partitions.get('background', []))}"
                f" housekeeping={len(self._cpu_partitions.get('housekeeping', []))}"
            )
        self._log("==================================================")

    def _ensure_single_instance(self):
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            self._log(f"[ERROR] Failed to create single-instance mutex: {self._last_error_text()}")
            return False
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            self._log("[ERROR] Another instance of Esports Isolator PRO is already running.")
            return False
        self._mutex_handle = handle
        return True

    def _release_single_instance(self):
        handle = self._mutex_handle
        if not handle:
            return
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
        self._mutex_handle = None

    def _lock_working_set_memory(self):
        # WHY: SetProcessWorkingSetSize without the QUOTA_LIMITS_HARDWS_*
        # flags is treated as a HINT by the kernel — the trimmer can and
        # will discard pages anyway under memory pressure. Truly hard limits
        # require SE_INC_WORKING_SET_NAME privilege + SetProcessWorkingSetSizeEx.
        # We log this honestly rather than overpromising.
        try:
            handle = kernel32.GetCurrentProcess()
            min_ws = ctypes.c_size_t(50 * 1024 * 1024)
            max_ws = ctypes.c_size_t(100 * 1024 * 1024)
            if kernel32.SetProcessWorkingSetSize(handle, min_ws, max_ws):
                self._log("[INFO] Working-set hint applied (50-100MB). Note: not a hard limit without SeIncreaseWorkingSetPrivilege.")
        except Exception as e:
            self._log_once(("working_set_lock", type(e).__name__), f"[WARN] Working set lock failed: {e}")

    def _install_console_ctrl_handler(self):
        # WHY: On Windows, clicking the console window's "X" button sends
        # CTRL_CLOSE_EVENT. Python's atexit and try/finally do NOT execute
        # for this event — Windows gives the handler ~5 seconds then kills
        # the process. Similarly, CTRL_LOGOFF_EVENT and CTRL_SHUTDOWN_EVENT
        # fire during user logoff / system shutdown. We must intercept all
        # of these to guarantee state restoration (power plan, IFEO registry,
        # process priorities, timer resolution).
        def _console_handler(ctrl_type):
            if ctrl_type in (CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT,
                             CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
                # WHY: CTRL_CLOSE_EVENT / CTRL_LOGOFF_EVENT / CTRL_SHUTDOWN_EVENT
                # give the handler ~5 seconds before Windows force-kills the
                # process. fast=True skips the 3s monitor-thread join so the
                # full restore budget is spent on actual state recovery.
                fast = ctrl_type in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT)
                self.shutdown(fast=fast)
                return True  # WHY: Returning TRUE tells Windows we handled it
            return False
        # WHY: Store the callback as an instance attribute so it is never
        # garbage-collected. If the WINFUNCTYPE wrapper is collected, the
        # kernel's callback pointer becomes dangling → crash on next event.
        self._console_ctrl_callback = CONSOLE_CTRL_HANDLER(_console_handler)
        if not kernel32.SetConsoleCtrlHandler(self._console_ctrl_callback, True):
            self._log_once(("console_ctrl_handler",), f"[WARN] SetConsoleCtrlHandler failed: {self._last_error_text()}")
        else:
            self._log("[INFO] Installed native Windows console control handler for safe shutdown.")

    def run(self):
        if not is_process_elevated():
            self._log("[ERROR] administrator_required")
            return False
        if not self._ensure_single_instance():
            return False

        atexit.register(self.shutdown)
        # WHY: Install the native console handler BEFORE any system state is
        # modified. This ensures that even if setup crashes partway through,
        # the handler is already in place to clean up whatever was changed.
        self._install_console_ctrl_handler()
        if not self._recover_persistent_state(auto=True):
            return False
        if not self._recover_jail_state_from_crash(auto=True):
            self._persistent_recovery_incomplete = True
            self._log("[RECOVERY:jail:auto] Crash jail recovery incomplete; refusing to apply new system changes.")
            return False
        self._lock_working_set_memory()
        self._original_power_scheme = self._get_active_power_scheme()
        if self._original_power_scheme is not None and not self._disable_power_scheme_switch:
            self._write_power_recovery_state(original_scheme=self._original_power_scheme, switched=False)
        self._refresh_topology("startup")
        self._print_capability_report()
        if not self._disable_timer_resolution_tweak:
            self._set_timer_resolution()

        self._load_ifeo_backups()
        self._apply_configured_game_ifeo_priorities()

        self._boost_system_critical()
        self._start_monitoring()
        return True

    def dry_run(self):
        self._refresh_topology("dry_run")
        self._print_capability_report()
        self._log(
            "[DRY-RUN] No IFEO, power plan, timer resolution, jailing, or process priority changes were applied."
        )
        return True

    def shutdown(self, fast=False):
        # WHY: Guard against double-execution. shutdown() can be called from:
        # 1. atexit handler (normal exit)
        # 2. Console Ctrl Handler (user clicks X, Ctrl+C, logoff, OS shutdown)
        # 3. finally block in __main__
        # 4. The monitor thread itself (if it detects a fatal error)
        # All four can race. We use _state_lock for an atomic compare-and-set:
        # only the first caller proceeds; all subsequent callers return immediately.
        with self._state_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
            self._shutting_down = True

        self._log("==================================================")
        self._log("[SHUTDOWN] Initiating safe shutdown and state restoration...")
        self._log("==================================================")

        # WHY: Transactional shutdown — each restore step is independently
        # guarded with try/except. If one step raises, the remaining steps
        # still run so we never leave the system stuck in a half-restored
        # state (power plan altered, IFEO keys dangling, GC disabled, etc.).
        #
        # ORDER RATIONALE: The Windows console-control handler (CTRL_CLOSE_
        # EVENT / CTRL_LOGOFF / CTRL_SHUTDOWN) gives us only ~5 seconds
        # before the kernel force-kills the process. Process restoration
        # touches up to dozens of handles and each call can block 50-1200ms
        # under anti-cheat minifilters, so we run the cheap-but-globally-
        # visible steps FIRST (power scheme, timer, IFEO) and the slow,
        # best-effort process restoration LAST. That way even if Windows
        # kills us mid-shutdown, the user's PC is left with a sane power
        # plan and registry rather than stuck in Ultimate Performance.

        # Step 1: Signal the monitor thread to stop.
        # WHY: In fast mode (console close / logoff / shutdown) we skip the
        # 3-second join — every millisecond before the 5s kill counts and
        # the daemon monitor thread will be torn down by the OS anyway.
        try:
            self._stop_event.set()
            if not fast and self._monitor_thread and self._monitor_thread.is_alive() and threading.current_thread() is not self._monitor_thread:
                self._monitor_thread.join(timeout=3.0)
            self._wait_for_process_mutations()
            with self._state_lock:
                self._active_games.clear()
            self._log("[SHUTDOWN] Step 1/8: Monitor thread signalled; active mutations drained.")
        except Exception as e:
            self._log(f"[ERROR] Shutdown step 1: failed to stop monitor thread: {e}")

        # Step 2: Restore the original Windows power scheme (cheap, high-impact).
        try:
            self._restore_power_scheme()
            self._log("[SHUTDOWN] Step 2/8: Power scheme restored.")
        except Exception as e:
            self._log(f"[ERROR] Shutdown step 2: failed to restore power scheme: {e}")

        # Step 3: Restore the system timer resolution (cheap, high-impact).
        try:
            self._restore_timer_resolution()
            self._log("[SHUTDOWN] Step 3/8: Timer resolution restored.")
        except Exception as e:
            self._log(f"[ERROR] Shutdown step 3: failed to restore timer resolution: {e}")

        # Step 4: Restore IFEO registry keys (medium cost, persists across boots).
        try:
            self._restore_ifeo_priorities()
            self._log("[SHUTDOWN] Step 4/8: IFEO registry restored.")
        except Exception as e:
            self._log(f"[ERROR] Shutdown step 4: failed to restore IFEO registry: {e}")

        # Step 5: Restore all jailed/boosted processes (slow, best-effort).
        try:
            self._log("[SHUTDOWN] Step 5/8: Restoring process priorities, EcoQoS, and affinities...")
            self._restore_all_processes()
        except Exception as e:
            self._log(f"[ERROR] Shutdown step 5: failed to restore processes: {e}")

        # Step 6: Restore system-critical process priorities (dwm.exe, audiodg.exe, etc.)
        try:
            self._restore_system_critical()
            self._log("[SHUTDOWN] Step 6/8: System-critical process priorities restored.")
        except Exception as e:
            self._log(f"[ERROR] Shutdown step 6: failed to restore system critical: {e}")

        # Step 7: Re-enable and run the garbage collector
        # WHY: gc.disable() may have been called by the monitor loop during
        # game mode. If the script crashes or the console is closed while GC
        # is disabled, Python's cyclic GC remains disabled for any code that
        # runs after us (e.g., atexit handlers from other modules). We must
        # unconditionally re-enable it here.
        try:
            gc.enable()
            gc.collect()
            self._log("[SHUTDOWN] Step 7/8: GC re-enabled.")
        except Exception:
            pass

        # Step 8: Release the single-instance mutex (always last)
        # WHY: This is in a bare try/finally because the mutex MUST be
        # released even if everything above failed. If we don't release it,
        # the user cannot start a new instance until they reboot.
        try:
            self._release_single_instance()
            self._log("[SHUTDOWN] Step 8/8: Mutex released.")
        except Exception:
            pass

        self._log("==================================================")
        self._log("[SHUTDOWN] All state restored. Safe to close.")
        self._log("==================================================")

        try:
            self._close_log_file()
        except Exception:
            pass
