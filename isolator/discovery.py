"""DiscoveryMixin implementation slice."""

import ctypes
import gc
import json
import os
import re
import threading
import time
import winreg
from ctypes import wintypes
from typing import Any, Protocol

from .winapi import (
    NON_GAME_DIR_PRUNE_TOKENS,
    NON_GAME_EXE_NAME_PATTERN,
    NON_GAME_PATH_TOKENS,
    PROCESS_QUERY_LIMITED_INFORMATION,
    STATUS_INFO_LENGTH_MISMATCH,
    kernel32,
    nt_success,
    ntdll,
)

# WHY: Module-level constants — SPI-derived names hit _is_game_name_normalized
# hundreds of times per poll; avoid per-call set literals and re-normalization.
_LAUNCHER_EXES = frozenset({
    "epicwebhelper.exe",
    "epicgameslauncher.exe",
    "steam.exe",
    "steamwebhelper.exe",
    "eadesktop.exe",
    # WHY: BattlEye DRM wrapper. Spawns the real game and exits ~30s later.
    # Was being auto-detected as a game itself via Steam library scan, causing
    # double Game Mode entry/exit cycles and stray IFEO writes.
    "start_protected_game.exe",
})
_PROTECTED_GAME_TITLES = frozenset({
    "valorant.exe",
    "fortniteclient-win64-shipping.exe",
    "rainbowsix.exe",
})
_PROTECTED_TITLE_TOKENS = ("easyanticheat", "battleye", "beservice", "vgc", "vgtray")

# WHY: A wall-clock ceiling per provider scan pass. Multi-terabyte game
# libraries can hold tens of thousands of files; without a budget one slow
# disk turns a background refresh into minutes of I/O.
LIBRARY_SCAN_BUDGET_S = 15.0


class DiscoveryHost(Protocol):
    """Typing-only host contract for DiscoveryMixin.

    Enumerates every attribute and cross-mixin method DiscoveryMixin reads
    but does not own. EsportsIsolatorPro.__init__ provides the attributes
    (from ParsedConfig / RuntimeState / Win32Scratch); the mixins named in
    the comments provide the methods. DiscoveryMixin deliberately does NOT
    inherit from this Protocol — that would change the MRO for zero runtime
    benefit — it exists so the implicit host coupling is written down and
    reviewable in one place.
    """

    # -- config (ParsedConfig-backed) --
    games: set
    auto_detect_steam: bool
    auto_detect_epic: bool
    auto_detect_gog: bool
    auto_detect_ea: bool
    auto_detect_battlenet: bool
    auto_detect_ubisoft: bool
    auto_detect_xbox: bool
    steam_library_paths: list
    epic_library_paths: list
    app_profiles: dict
    protected_exact: set
    protected_prefixes: tuple

    # -- shared runtime state (RuntimeState-backed) --
    _state_lock: threading.Lock
    _stop_event: threading.Event
    _library_scan_ready: threading.Event
    _library_scan_thread: threading.Thread | None
    _last_steam_scan: float
    _last_epic_scan: float
    _last_gog_scan: float
    _last_ea_scan: float
    _last_battlenet_scan: float
    _last_ubisoft_scan: float
    _last_xbox_scan: float
    _steam_games_cache: set
    _epic_games_cache: set
    _gog_games_cache: set
    _ea_games_cache: set
    _battlenet_games_cache: set
    _ubisoft_games_cache: set
    _xbox_games_cache: set
    _discovery_issues: list
    _protected_cache: dict
    # NOTE: host-seeded but PUBLISHED by this mixin — _get_processes rewrites
    # it every poll cycle for TuningMixin's PID-reuse guards.
    _process_create_times: dict
    # NOTE: host-seeded but PUBLISHED by this mixin — _get_processes rewrites
    # it every poll cycle for RuntimeMixin's ProBalance CPU sampling.
    _process_cpu_times: dict

    # -- SPI parsing scratch (Win32Scratch-backed) --
    _spi_buffer: Any
    _spi_buffer_size: Any
    _spi_off_next: int
    _spi_off_pid: int
    _spi_off_name: int
    _spi_off_create_time: int
    _spi_off_user_time: int
    _spi_off_kernel_time: int
    _spi_ptr_size: int
    _spi_struct_ulong: Any
    _spi_struct_ushort: Any
    _spi_struct_longlong: Any
    _spi_struct_ptr: Any

    # -- cross-mixin methods --
    # BaseMixin
    def _normalize_name(self, name): ...
    def _log_once(self, key, message): ...
    def _open_process(self, pid, access, quiet=False): ...
    # TopologyMixin
    def _filetime_to_int(self, value): ...


class DiscoveryMixin:
    """Process enumeration, game classification, and launcher library scans.

    Host contract: DiscoveryHost (above) documents every attribute and
    cross-mixin method this mixin consumes but does not assign.
    """

    def _request_library_scan(self, force=False):
        """Kick off a Steam/Epic library scan on a background daemon thread.

        Library scanning walks configured libraries with os.walk (depth 4)
        and used to run synchronously inside __init__ and the monitor loop,
        stalling engine construction and game detection for seconds on large
        libraries. One worker at a time; a request while a scan is running is
        dropped (the running scan already publishes fresh caches).
        """
        with self._state_lock:
            thread = self._library_scan_thread
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._run_library_scans,
                kwargs={"force": force},
                name="IsolatorLibraryScan",
                daemon=True,
            )
            self._library_scan_thread = thread
        thread.start()

    def _run_library_scans(self, force=False):
        try:
            if self.auto_detect_steam:
                self._scan_steam_games(force=force or self._last_steam_scan == float("-inf"))
            if self.auto_detect_epic:
                self._scan_epic_games(force=force or self._last_epic_scan == float("-inf"))
            if self.auto_detect_gog:
                self._scan_gog_games(force=force or self._last_gog_scan == float("-inf"))
            if self.auto_detect_ea:
                self._scan_ea_games(force=force or self._last_ea_scan == float("-inf"))
            if self.auto_detect_battlenet:
                self._scan_battlenet_games(force=force or self._last_battlenet_scan == float("-inf"))
            if self.auto_detect_ubisoft:
                self._scan_ubisoft_games(force=force or self._last_ubisoft_scan == float("-inf"))
            if self.auto_detect_xbox:
                self._scan_xbox_games(force=force or self._last_xbox_scan == float("-inf"))
        finally:
            # Background jailing waits on this so an auto-detected game can
            # never be classified as background before the caches are warm.
            self._library_scan_ready.set()

    def _library_scan_due(self, now):
        """True when any enabled provider's periodic library refresh is due.

        Keeps the monitor loop's refresh gate readable now that seven
        providers carry their own throttle timestamps.
        """
        return (
            (self.auto_detect_steam and now - self._last_steam_scan > 300.0)
            or (self.auto_detect_epic and now - self._last_epic_scan > 300.0)
            or (self.auto_detect_gog and now - self._last_gog_scan > 300.0)
            or (self.auto_detect_ea and now - self._last_ea_scan > 300.0)
            or (self.auto_detect_battlenet and now - self._last_battlenet_scan > 300.0)
            or (self.auto_detect_ubisoft and now - self._last_ubisoft_scan > 300.0)
            or (self.auto_detect_xbox and now - self._last_xbox_scan > 300.0)
        )
    def _clear_discovery_issues(self, provider):
        prefix = f"{provider}_"
        with self._state_lock:
            self._discovery_issues[:] = [
                issue for issue in self._discovery_issues
                if not str(issue.get("code", "")).startswith(prefix)
            ]

    def _record_discovery_issue(self, code, **data):
        issue = {"code": str(code), "data": dict(data)}
        with self._state_lock:
            if issue not in self._discovery_issues:
                self._discovery_issues.append(issue)
                if len(self._discovery_issues) > 50:
                    del self._discovery_issues[:-50]

    def _app_profile_for_name(self, name):
        normalized = name if name and "\\" not in str(name) and "/" not in str(name) else self._normalize_name(name)
        profile = getattr(self, "app_profiles", {}).get(normalized)
        if profile and profile.get("enabled", True):
            return profile
        return None

    def _profile_treats_as_game(self, normalized):
        profile = self._app_profile_for_name(normalized)
        if not profile or not profile.get("treat_as_game"):
            return False
        return not self._is_protected_process_name(normalized)

    def _profile_never_jail(self, normalized):
        profile = self._app_profile_for_name(normalized)
        return bool(profile and profile.get("never_jail"))

    def _profile_always_jail(self, normalized):
        profile = self._app_profile_for_name(normalized)
        return bool(profile and profile.get("always_jail"))

    def _profile_priority_class(self, normalized):
        profile = self._app_profile_for_name(normalized)
        if not profile:
            return ""
        return str(profile.get("priority_class", "") or "")

    def _is_game_name_normalized(self, normalized):
        if not normalized or normalized in _LAUNCHER_EXES:
            return False
        if self._profile_treats_as_game(normalized):
            return True
        if normalized in self.games:
            return True
        if self.auto_detect_steam and normalized in self._steam_games_cache:
            return True
        if self.auto_detect_epic and normalized in self._epic_games_cache:
            return True
        if self.auto_detect_gog and normalized in self._gog_games_cache:
            return True
        if self.auto_detect_ea and normalized in self._ea_games_cache:
            return True
        if self.auto_detect_battlenet and normalized in self._battlenet_games_cache:
            return True
        if self.auto_detect_ubisoft and normalized in self._ubisoft_games_cache:
            return True
        if self.auto_detect_xbox and normalized in self._xbox_games_cache:
            return True
        return False

    def _is_game_name(self, name):
        return self._is_game_name_normalized(self._normalize_name(name))

    def _normalize_spi_name(self, name):
        return name.lower() if name else ""

    def _is_protected_process_name(self, name):
        normalized = self._normalize_name(name)
        if not normalized:
            return True
        if normalized in self._protected_cache:
            return self._protected_cache[normalized]
        if normalized in self.protected_exact:
            self._protected_cache[normalized] = True
            return True
        is_protected = normalized.startswith(self.protected_prefixes)
        self._protected_cache[normalized] = is_protected
        return is_protected

    def _get_processes(self):
        # WHY: Reuse a pre-allocated wintypes.ULONG for the buffer_size parameter
        # instead of creating a new one each call. This avoids allocating a ctypes
        # wrapper object on every poll cycle (every 2s during game mode).
        buffer_size = self._spi_buffer_size
        buffer_size.value = ctypes.sizeof(self._spi_buffer)
        max_spi_retries = 10
        max_spi_buffer_size = 256 * 1024 * 1024
        attempts = 0
        while attempts < max_spi_retries:
            status = ntdll.NtQuerySystemInformation(5, self._spi_buffer, buffer_size, ctypes.byref(buffer_size))
            if status == STATUS_INFO_LENGTH_MISMATCH:
                new_size = max(buffer_size.value, ctypes.sizeof(self._spi_buffer)) + (1024 * 1024)
                if new_size > max_spi_buffer_size:
                    self._log_once(("spi_buffer_overflow",), "[ERROR] Process enumeration buffer exceeded 256MB limit.")
                    return []
                self._spi_buffer = ctypes.create_string_buffer(new_size)
                buffer_size.value = new_size
                attempts += 1
                continue
            if not nt_success(status):
                self._log_once(("nt_query_system_information", int(status)), f"[WARN] NtQuerySystemInformation failed: 0x{ctypes.c_ulong(status).value:08X}")
                return []
            break
        else:
            self._log_once(("spi_max_retries",), "[ERROR] Process enumeration exceeded maximum retry attempts.")
            return []

        # WHY: Use struct.unpack_from to read fields directly from the ctypes
        # buffer via the C buffer protocol — TRUE ZERO-COPY. The previous
        # approach used self._spi_buffer.raw which copies the ENTIRE buffer
        # (1MB+) into a temporary Python bytes object on every poll cycle.
        # That single .raw call was allocating 1MB of immediate garbage every
        # 2 seconds during game mode — the exact kind of memory churn that
        # triggers GC pauses and frame-time spikes. struct.unpack_from reads
        # directly from the buffer's C memory without any Python-side copy.
        # Measured: 218μs wasted per cycle for .raw → eliminated completely.
        spi_buf = self._spi_buffer
        buf_len = buffer_size.value
        off_next = self._spi_off_next
        off_pid = self._spi_off_pid
        off_name = self._spi_off_name
        off_create_time = self._spi_off_create_time
        off_user_time = self._spi_off_user_time
        off_kernel_time = self._spi_off_kernel_time
        ptr_size = self._spi_ptr_size
        fmt_ulong = self._spi_struct_ulong.unpack_from
        fmt_ushort = self._spi_struct_ushort.unpack_from
        fmt_longlong = self._spi_struct_longlong.unpack_from
        fmt_ptr = self._spi_struct_ptr.unpack_from
        # WHY: UNICODE_STRING layout is { USHORT Length, USHORT MaxLength, LPWSTR Buffer }.
        # Length is at off_name+0 (2 bytes), Buffer pointer is at off_name+8 on x64
        # (off_name+4 on x86). We read Length to know how many WCHARs to extract.
        name_len_offset = off_name  # USHORT Length at start of UNICODE_STRING
        name_buf_offset = off_name + (8 if ptr_size == 8 else 4)  # LPWSTR Buffer
        normalize = self._normalize_spi_name
        processes = []
        process_create_times = {}
        process_cpu_times = {}
        processes_append = processes.append
        offset = 0
        while offset < buf_len:
            # WHY: struct.unpack_from reads directly from the ctypes buffer's
            # C memory via the buffer protocol. No Python bytes object is created.
            # [0] extracts the single value from the returned tuple.
            next_entry = fmt_ulong(spi_buf, offset + off_next)[0]
            pid = fmt_ptr(spi_buf, offset + off_pid)[0]
            create_time = fmt_longlong(spi_buf, offset + off_create_time)[0]
            name_length = fmt_ushort(spi_buf, offset + name_len_offset)[0]
            name = ""
            if name_length > 0:
                name_ptr = fmt_ptr(spi_buf, offset + name_buf_offset)[0]
                if name_ptr:
                    try:
                        name = ctypes.wstring_at(name_ptr, name_length // 2)
                    except Exception:
                        name = ""
            if pid:
                process_create_times[int(pid)] = int(create_time)
                # WHY: UserTime+KernelTime (100ns units) feed ProBalance's
                # per-process CPU% deltas; summing here keeps the hot loop to
                # two extra fixed-offset reads per entry.
                user_time = fmt_longlong(spi_buf, offset + off_user_time)[0]
                kernel_time = fmt_longlong(spi_buf, offset + off_kernel_time)[0]
                process_cpu_times[int(pid)] = int(user_time) + int(kernel_time)
            processes_append((pid, normalize(name)))
            if next_entry == 0:
                break
            offset += next_entry
        self._process_create_times = process_create_times
        self._process_cpu_times = process_cpu_times

        # WHY: Shrink the buffer AFTER parsing, not before. The old buffer holds
        # the NtQuerySystemInformation results; replacing it before the parsing
        # loop would cause the loop to read from a new, empty buffer — returning
        # zero processes and triggering false "all games closed" events that
        # thrash process priorities and cause micro-stutters.
        # WHY: Skip buffer shrink when GC is disabled (during game mode).
        # Replacing the buffer creates a 1-4MB garbage object that won't be
        # collected until the next gc.collect() — contributing to the memory
        # buildup that makes those periodic collections expensive and stuttery.
        actual_used = buffer_size.value
        current_size = ctypes.sizeof(self._spi_buffer)
        if current_size > 4 * 1024 * 1024 and actual_used < current_size // 4 and gc.isenabled():
            self._spi_buffer = ctypes.create_string_buffer(max(1024 * 1024, actual_used * 2))

        return processes

    def _get_process_create_time(self, handle):
        creation_time = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if kernel32.GetProcessTimes(handle, ctypes.byref(creation_time), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return self._filetime_to_int(creation_time)
        return 0

    def _get_process_name(self, pid):
        handle = self._open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION, quiet=True)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return self._normalize_name(buffer.value)
        finally:
            kernel32.CloseHandle(handle)
        return ""

    def _get_process_full_path(self, pid):
        handle = self._open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION, quiet=True)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
        finally:
            kernel32.CloseHandle(handle)
        return ""

    def _is_wow64_process(self, handle):
        result = wintypes.BOOL()
        return bool(kernel32.IsWow64Process(handle, ctypes.byref(result)) and result.value)

    def _get_steam_path(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam_path = winreg.QueryValueEx(key, "SteamPath")[0]
                return steam_path.replace("/", "\\")
        except Exception:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam") as key:
                    steam_path = winreg.QueryValueEx(key, "InstallPath")[0]
                    return steam_path
            except Exception:
                return None

    def _scan_steam_games(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_steam_scan) < 300:
            return
        self._last_steam_scan = now
        self._clear_discovery_issues("steam")
        steam_path = self._get_steam_path()
        library_paths = []
        for configured_path in self.steam_library_paths:
            common_path = self._steam_common_directory(configured_path)
            if common_path:
                library_paths.append(common_path)
        if steam_path:
            library_paths.append(os.path.join(steam_path, "steamapps", "common"))
        elif not library_paths:
            self._record_discovery_issue("steam_install_not_found")

        vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf") if steam_path else ""
        if vdf_path and os.path.exists(vdf_path):
            try:
                with open(vdf_path, "r", encoding="utf-8") as f:
                    for p in re.findall(r'"path"\s+"([^"]+)"', f.read()):
                        p = p.replace("\\\\", "\\")
                        common = self._steam_common_directory(p)
                        if common and os.path.exists(common) and common not in library_paths:
                            library_paths.append(common)
            except (OSError, UnicodeError) as exc:
                self._record_discovery_issue(
                    "steam_library_manifest_read_failed",
                    path=vdf_path,
                    error=type(exc).__name__,
                )
        steam_games = self._scan_launcher_library("steam", library_paths, set())
        # Publish atomically for readers on the monitor/API threads.
        with self._state_lock:
            self._steam_games_cache = steam_games

    def _scan_launcher_library(self, provider, library_paths, out_set):
        """Walk one provider's library roots into out_set under the scan budget.

        Shared loop for every launcher scanner: dedupe roots, skip missing
        ones, walk each with _scan_for_game_exes under one wall-clock budget,
        and record provider-prefixed discovery issues
        (f"{provider}_library_unavailable" / "_library_scan_failed" /
        "_scan_budget_exceeded") on failure. The caller keeps its
        provider-specific root discovery and publishes the returned set to
        its cache attribute under _state_lock.
        """
        seen_paths = set()
        deadline = time.monotonic() + LIBRARY_SCAN_BUDGET_S
        for lib in library_paths:
            path_key = os.path.normcase(os.path.abspath(lib))
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            if not os.path.exists(lib):
                self._record_discovery_issue(f"{provider}_library_unavailable", path=lib)
                continue
            try:
                completed = self._scan_for_game_exes(lib, out_set, max_depth=4, deadline=deadline)
            except OSError as exc:
                self._record_discovery_issue(
                    f"{provider}_library_scan_failed",
                    path=lib,
                    error=type(exc).__name__,
                )
                continue
            if not completed:
                if not self._stop_event.is_set():
                    self._record_discovery_issue(f"{provider}_scan_budget_exceeded", path=lib)
                break
        return out_set

    @staticmethod
    def _steam_common_directory(path):
        if not isinstance(path, str) or not path.strip():
            return None
        normalized = os.path.normpath(path.strip())
        basename = os.path.basename(normalized).lower()
        parent_basename = os.path.basename(os.path.dirname(normalized)).lower()
        if basename == "common" and parent_basename == "steamapps":
            return normalized
        if basename == "steamapps":
            return os.path.join(normalized, "common")
        return os.path.join(normalized, "steamapps", "common")

    @staticmethod
    def _looks_like_game_exe(exe_name, exe_full_path=None):
        # WHY: Filter out redistributables, installers, crash handlers, and
        # anti-cheat utility exes that live under Steam / Epic library trees.
        # Without this filter every vcredist_x64.exe and UnityCrashHandler.exe
        # in steamapps/common/<game>/_CommonRedist/ would be treated as a game.
        if not exe_name:
            return False
        lowered = exe_name.lower()
        if not lowered.endswith(".exe"):
            return False
        if NON_GAME_EXE_NAME_PATTERN.match(lowered):
            return False
        if exe_full_path:
            normalized_path = exe_full_path.lower().replace("/", "\\")
            for token in NON_GAME_PATH_TOKENS:
                if token in normalized_path:
                    return False
        return True

    def _scan_for_game_exes(self, root_path, out_set, max_depth=3, deadline=None):
        """Walk one library root collecting game exe names.

        Returns True when the walk completed, False when it stopped early —
        either the wall-clock deadline passed or the engine is shutting down.
        """
        # WHY: Pre-prune `dirs` so os.walk skips redistributable / installer
        # subtrees AND so depth-(max_depth+1) directories are never entered
        # in the first place. The previous implementation called _dirs.clear()
        # AFTER already walking depth-(max_depth+1), wasting filesystem I/O.
        def raise_walk_error(error):
            raise error

        stop_event = getattr(self, "_stop_event", None)
        for current_root, dirs, files in os.walk(root_path, onerror=raise_walk_error):
            if stop_event is not None and stop_event.is_set():
                return False
            if deadline is not None and time.monotonic() > deadline:
                return False
            rel = os.path.relpath(current_root, root_path)
            depth = 0 if rel in (".", "") else rel.count(os.sep) + 1
            if depth >= max_depth:
                dirs[:] = []
            else:
                # WHY: Substring match (not exact equality) so dirs named
                # "Game Installers" or "_CommonRedist_x86" are also pruned.
                dirs[:] = [
                    d for d in dirs
                    if not any(tok in d.lower() for tok in NON_GAME_DIR_PRUNE_TOKENS)
                ]
            for f in files:
                if self._looks_like_game_exe(f, os.path.join(current_root, f)):
                    out_set.add(f.lower())
        return True

    def _is_steam_game(self, exe_path):
        if not self.auto_detect_steam or not exe_path:
            return False
        p = exe_path.lower().replace("/", "\\")
        if not self._looks_like_game_exe(os.path.basename(p), p):
            return False
        if "\\steamapps\\common\\" in p:
            return True
        return os.path.basename(p) in self._steam_games_cache

    def _get_epic_path(self):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Epic Games\EpicGamesLauncher") as key:
                return os.path.dirname(winreg.QueryValueEx(key, "AppDataPath")[0])
        except Exception:
            return r"C:\Program Files\Epic Games" if os.path.exists(r"C:\Program Files\Epic Games") else None

    def _get_epic_manifest_dirs(self):
        paths = []
        program_data = os.environ.get("ProgramData")
        if program_data:
            paths.append(os.path.join(program_data, "Epic", "EpicGamesLauncher", "Data", "Manifests"))
        return paths

    def _read_epic_manifests(self):
        install_paths = []
        launch_executables = set()
        for manifest_dir in self._get_epic_manifest_dirs():
            if not os.path.isdir(manifest_dir):
                continue
            try:
                manifest_names = [name for name in os.listdir(manifest_dir) if name.lower().endswith(".item")]
            except OSError as exc:
                self._record_discovery_issue(
                    "epic_manifest_directory_read_failed",
                    path=manifest_dir,
                    error=type(exc).__name__,
                )
                continue
            for manifest_name in manifest_names:
                manifest_path = os.path.join(manifest_dir, manifest_name)
                try:
                    with open(manifest_path, "r", encoding="utf-8") as handle:
                        manifest = json.load(handle)
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    self._record_discovery_issue(
                        "epic_manifest_read_failed",
                        path=manifest_path,
                        error=type(exc).__name__,
                    )
                    continue
                if not isinstance(manifest, dict):
                    self._record_discovery_issue(
                        "epic_manifest_invalid",
                        path=manifest_path,
                    )
                    continue
                install_location = manifest.get("InstallLocation")
                if isinstance(install_location, str) and install_location.strip():
                    install_paths.append(os.path.normpath(install_location.strip()))
                launch_executable = manifest.get("LaunchExecutable")
                if isinstance(launch_executable, str):
                    exe_name = os.path.basename(launch_executable.replace("\\", os.sep))
                    if self._looks_like_game_exe(exe_name):
                        launch_executables.add(exe_name.lower())
        return install_paths, launch_executables

    def _scan_epic_games(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_epic_scan) < 300:
            return
        self._last_epic_scan = now
        self._clear_discovery_issues("epic")
        base = self._get_epic_path()
        paths = list(self.epic_library_paths)
        if base and os.path.exists(base):
            paths.append(base)
        if os.path.exists(r"C:\Program Files\Epic Games") and r"C:\Program Files\Epic Games" not in paths:
            paths.append(r"C:\Program Files\Epic Games")
        manifest_paths, epic_games = self._read_epic_manifests()
        paths.extend(manifest_paths)
        if not paths:
            self._record_discovery_issue("epic_install_not_found")
        epic_games = self._scan_launcher_library("epic", paths, epic_games)
        # Publish atomically for readers on the monitor/API threads.
        with self._state_lock:
            self._epic_games_cache = epic_games

    def _is_epic_game(self, exe_path):
        if not self.auto_detect_epic or not exe_path:
            return False
        p = exe_path.lower().replace("/", "\\")
        if not self._looks_like_game_exe(os.path.basename(p), p):
            return False
        if "\\epic games\\" in p:
            return True
        return os.path.basename(p) in self._epic_games_cache

    def _enum_registry_install_dirs(self, key_path, value_name):
        """Enumerate HKLM\\<key_path> subkeys and collect <value_name> paths.

        Shared root discovery for the registry-based launcher scanners (GOG,
        EA, Battle.net, Ubisoft). A missing hive or an unreadable subkey is
        normal on machines without that launcher, so per-key failures stay
        silent; the caller records the provider-level discovery issue when
        the final root list is empty.
        """
        roots = []
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            value = winreg.QueryValueEx(subkey, value_name)[0]
                    except Exception:
                        continue
                    if isinstance(value, str) and value.strip():
                        normalized = os.path.normpath(value.strip())
                        if normalized not in roots:
                            roots.append(normalized)
        except Exception:
            pass
        return roots

    def _gog_library_roots(self):
        # GOG Galaxy writes one subkey per installed game with its "path".
        roots = self._enum_registry_install_dirs(r"SOFTWARE\WOW6432Node\GOG.com\Games", "path")
        for root in self._enum_registry_install_dirs(r"SOFTWARE\GOG.com\Games", "path"):
            if root not in roots:
                roots.append(root)
        return roots

    def _ea_library_roots(self):
        # Origin-era installs keep per-game "Install Dir" subkeys; EA Desktop
        # keeps no per-game registry entries, so the default install
        # directories are added best-effort when they exist.
        roots = self._enum_registry_install_dirs(r"SOFTWARE\WOW6432Node\Origin Games", "Install Dir")
        for default_dir in (r"C:\Program Files\EA Games", r"C:\Program Files (x86)\Origin Games"):
            if default_dir not in roots and os.path.exists(default_dir):
                roots.append(default_dir)
        return roots

    def _battlenet_library_roots(self):
        # One subkey per Blizzard title with its "InstallPath". The
        # %ProgramData%\Battle.net product.db alternative is a binary blob
        # and deliberately not parsed.
        return self._enum_registry_install_dirs(r"SOFTWARE\WOW6432Node\Blizzard Entertainment", "InstallPath")

    def _ubisoft_library_roots(self):
        # Ubisoft Connect writes one numeric subkey per install with "InstallDir".
        return self._enum_registry_install_dirs(r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs", "InstallDir")

    def _xbox_library_roots(self):
        r"""Fixed-drive <X>:\XboxGames roots (the modern Xbox app default).

        Deliberately does NOT touch C:\Program Files\WindowsApps — that tree
        is ACL-denied even to administrators and walking it produces nothing
        but access errors. Existence checks only, driven by the logical-drive
        bitmask so absent drive letters are never probed.
        """
        roots = []
        try:
            drives_mask = int(kernel32.GetLogicalDrives())
        except Exception:
            drives_mask = 0
        for index in range(26):
            if not drives_mask & (1 << index):
                continue
            root = f"{chr(ord('A') + index)}:\\XboxGames"
            if os.path.exists(root):
                roots.append(root)
        return roots

    def _scan_registry_launcher(self, provider, roots):
        """Shared scan body for the registry/default-dir launcher providers."""
        self._clear_discovery_issues(provider)
        if not roots:
            self._record_discovery_issue(f"{provider}_install_not_found")
        return self._scan_launcher_library(provider, roots, set())

    def _scan_gog_games(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_gog_scan) < 300:
            return
        self._last_gog_scan = now
        gog_games = self._scan_registry_launcher("gog", self._gog_library_roots())
        # Publish atomically for readers on the monitor/API threads.
        with self._state_lock:
            self._gog_games_cache = gog_games

    def _scan_ea_games(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_ea_scan) < 300:
            return
        self._last_ea_scan = now
        ea_games = self._scan_registry_launcher("ea", self._ea_library_roots())
        # Publish atomically for readers on the monitor/API threads.
        with self._state_lock:
            self._ea_games_cache = ea_games

    def _scan_battlenet_games(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_battlenet_scan) < 300:
            return
        self._last_battlenet_scan = now
        battlenet_games = self._scan_registry_launcher("battlenet", self._battlenet_library_roots())
        # Publish atomically for readers on the monitor/API threads.
        with self._state_lock:
            self._battlenet_games_cache = battlenet_games

    def _scan_ubisoft_games(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_ubisoft_scan) < 300:
            return
        self._last_ubisoft_scan = now
        ubisoft_games = self._scan_registry_launcher("ubisoft", self._ubisoft_library_roots())
        # Publish atomically for readers on the monitor/API threads.
        with self._state_lock:
            self._ubisoft_games_cache = ubisoft_games

    def _scan_xbox_games(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_xbox_scan) < 300:
            return
        self._last_xbox_scan = now
        xbox_games = self._scan_registry_launcher("xbox", self._xbox_library_roots())
        # Publish atomically for readers on the monitor/API threads.
        with self._state_lock:
            self._xbox_games_cache = xbox_games

    def _detect_protected_title(self, name):
        normalized = self._normalize_name(name)
        if not normalized:
            return False
        return normalized in _PROTECTED_GAME_TITLES or any(
            token in normalized for token in _PROTECTED_TITLE_TOKENS
        )
