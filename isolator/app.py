"""Public EsportsIsolatorPro class assembled from focused mixins."""

import copy
import ctypes
import os
import struct
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field

from .base import BaseMixin
from .config import DEFAULT_CONFIG
from .discovery import DiscoveryMixin
from .ifeo_power import IfeoPowerMixin
from .recovery import RecoveryMixin
from .runtime import RuntimeMixin
from .topology import TopologyMixin
from .tuning import TuningMixin
from .winapi import (
    HIGH_PERFORMANCE_GUID,
    SYSTEM_PROCESS_INFORMATION,
    ULTIMATE_PERFORMANCE_GUID,
    kernel32,
    make_guid,
)


@dataclass
class ParsedConfig:
    games: set
    auto_detect_steam: bool
    auto_detect_epic: bool
    steam_library_paths: list
    epic_library_paths: list
    app_profiles: dict
    housekeeping_core_count: int
    poll_interval_idle_s: float
    poll_interval_active_s: float
    enable_background_jailing: bool
    maintenance_jail_batch_size: int
    maintenance_jail_interval_s: float
    maintenance_jail_batch_cooldown_s: float
    disable_timer_resolution_tweak: bool
    disable_game_priority_boost: bool
    game_close_debounce_s: float
    game_exit_restore_delay_s: float
    gc_full_collect_interval_s: float
    maintenance_skip_after_quiet_cycles: int
    event_backend: str
    allow_mmcss_injection: bool
    disable_power_scheme_switch: bool
    anti_cheat_mode: str

    @staticmethod
    def _normalize_profile(owner, item):
        if not isinstance(item, dict):
            return None
        exe = owner._normalize_game_name(item.get("exe", ""))
        if not exe:
            return None
        never_jail = bool(item.get("never_jail", False))
        always_jail = bool(item.get("always_jail", False))
        if never_jail and always_jail:
            always_jail = False
        priority = str(item.get("priority_class", "") or "").strip().lower()
        if priority not in {"", "idle", "below_normal", "normal", "above_normal", "high"}:
            priority = ""
        return exe, {
            "exe": exe,
            "enabled": bool(item.get("enabled", True)),
            "treat_as_game": bool(item.get("treat_as_game", False)),
            "never_jail": never_jail,
            "always_jail": always_jail,
            "priority_class": priority,
        }

    @classmethod
    def _parse_app_profiles(cls, owner, config):
        profiles = {}
        for item in config.get("app_profiles", DEFAULT_CONFIG["app_profiles"]):
            normalized = cls._normalize_profile(owner, item)
            if normalized:
                exe, profile = normalized
                profiles[exe] = profile
        return profiles

    @classmethod
    def from_config(cls, owner, config):
        return cls(
            games={owner._normalize_game_name(name) for name in config.get("games", DEFAULT_CONFIG["games"])},
            auto_detect_steam=bool(config.get("auto_detect_steam_games", DEFAULT_CONFIG["auto_detect_steam_games"])),
            auto_detect_epic=bool(config.get("auto_detect_epic_games", DEFAULT_CONFIG["auto_detect_epic_games"])),
            steam_library_paths=config.get("steam_library_paths", DEFAULT_CONFIG["steam_library_paths"]),
            epic_library_paths=config.get("epic_library_paths", DEFAULT_CONFIG["epic_library_paths"]),
            app_profiles=cls._parse_app_profiles(owner, config),
            housekeeping_core_count=max(1, owner._safe_int(config.get("housekeeping_cores", DEFAULT_CONFIG["housekeeping_cores"]), DEFAULT_CONFIG["housekeeping_cores"])),
            poll_interval_idle_s=max(0.05, owner._safe_int(config.get("poll_interval_idle_ms", DEFAULT_CONFIG["poll_interval_idle_ms"]), DEFAULT_CONFIG["poll_interval_idle_ms"]) / 1000.0),
            poll_interval_active_s=max(0.05, owner._safe_int(config.get("poll_interval_active_ms", DEFAULT_CONFIG["poll_interval_active_ms"]), DEFAULT_CONFIG["poll_interval_active_ms"]) / 1000.0),
            enable_background_jailing=bool(config.get("enable_background_jailing", DEFAULT_CONFIG["enable_background_jailing"])),
            maintenance_jail_batch_size=max(1, owner._safe_int(config.get("maintenance_jail_batch_size", DEFAULT_CONFIG["maintenance_jail_batch_size"]), DEFAULT_CONFIG["maintenance_jail_batch_size"])),
            maintenance_jail_interval_s=max(5.0, owner._safe_int(config.get("maintenance_jail_interval_ms", DEFAULT_CONFIG["maintenance_jail_interval_ms"]), DEFAULT_CONFIG["maintenance_jail_interval_ms"]) / 1000.0),
            maintenance_jail_batch_cooldown_s=max(1.0, owner._safe_int(config.get("maintenance_jail_batch_cooldown_ms", DEFAULT_CONFIG["maintenance_jail_batch_cooldown_ms"]), DEFAULT_CONFIG["maintenance_jail_batch_cooldown_ms"]) / 1000.0),
            disable_timer_resolution_tweak=bool(config.get("disable_timer_resolution_tweak", DEFAULT_CONFIG["disable_timer_resolution_tweak"])),
            disable_game_priority_boost=bool(config.get("disable_game_priority_boost", DEFAULT_CONFIG["disable_game_priority_boost"])),
            game_close_debounce_s=max(0.0, owner._safe_int(config.get("game_close_debounce_s", DEFAULT_CONFIG["game_close_debounce_s"]), DEFAULT_CONFIG["game_close_debounce_s"])),
            game_exit_restore_delay_s=max(0.0, float(config.get("game_exit_restore_delay_s", DEFAULT_CONFIG["game_exit_restore_delay_s"]))),
            gc_full_collect_interval_s=max(60.0, float(config.get("gc_full_collect_interval_s", DEFAULT_CONFIG["gc_full_collect_interval_s"]))),
            maintenance_skip_after_quiet_cycles=max(0, owner._safe_int(config.get("maintenance_skip_after_quiet_cycles", DEFAULT_CONFIG["maintenance_skip_after_quiet_cycles"]), DEFAULT_CONFIG["maintenance_skip_after_quiet_cycles"])),
            event_backend=str(config.get("event_backend", DEFAULT_CONFIG["event_backend"])).lower(),
            allow_mmcss_injection=bool(config.get("allow_mmcss_injection", DEFAULT_CONFIG["allow_mmcss_injection"])),
            disable_power_scheme_switch=bool(config.get("disable_power_scheme_switch", DEFAULT_CONFIG["disable_power_scheme_switch"])),
            anti_cheat_mode=str(config.get("anti_cheat_mode", DEFAULT_CONFIG["anti_cheat_mode"])).lower(),
        )


@dataclass
class RuntimeState:
    state_lock: object = field(default_factory=threading.Lock)
    active_mutations: int = 0
    shutting_down: bool = False
    touched: dict = field(default_factory=dict)
    active_games: dict = field(default_factory=dict)
    ifeo_original: dict = field(default_factory=dict)
    monitor_thread: object = None
    stop_event: object = field(default_factory=threading.Event)
    shutdown_done: bool = False
    mutex_handle: object = None
    original_power_scheme: object = None
    power_plan_active: bool = False
    power_scheme_in_use: object = None
    persistent_recovery_incomplete: bool = False
    timer_resolution_applied: object = None
    capability_notes: list = field(default_factory=list)
    capability_notes_seen: set = field(default_factory=set)
    capability_issues: list = field(default_factory=list)
    capability_issues_seen: set = field(default_factory=set)
    reported_failures: dict = field(default_factory=dict)
    topology: object = None
    cpu_partitions: dict = field(default_factory=lambda: {"game": [], "background": [], "housekeeping": [], "game_cores": []})
    cpu_sets_by_id: dict = field(default_factory=dict)
    boosted_critical: dict = field(default_factory=dict)
    last_topology_refresh: float = 0.0
    last_steam_scan: float = float("-inf")
    last_epic_scan: float = float("-inf")
    steam_games_cache: set = field(default_factory=set)
    epic_games_cache: set = field(default_factory=set)
    library_scan_ready: object = field(default_factory=threading.Event)
    library_scan_thread: object = None
    discovery_issues: list = field(default_factory=list)
    known_non_games: set = field(default_factory=set)
    path_classification_cache: dict = field(default_factory=dict)
    process_create_times: dict = field(default_factory=dict)
    protected_cache: dict = field(default_factory=dict)
    entry_gen: int = 0


@dataclass
class Win32Scratch:
    spi_buffer: object
    fg_pid_dword: object
    spi_buffer_size: object
    spi_off_next: int
    spi_off_pid: int
    spi_off_name: int
    spi_off_create_time: int
    spi_ptr_size: int
    spi_struct_ulong: object
    spi_struct_ushort: object
    spi_struct_longlong: object
    spi_struct_ptr: object

    @classmethod
    def create(cls):
        ptr_size = ctypes.sizeof(ctypes.c_void_p)
        return cls(
            spi_buffer=ctypes.create_string_buffer(1024 * 1024),
            fg_pid_dword=wintypes.DWORD(),
            spi_buffer_size=wintypes.ULONG(),
            spi_off_next=SYSTEM_PROCESS_INFORMATION.NextEntryOffset.offset,
            spi_off_pid=SYSTEM_PROCESS_INFORMATION.UniqueProcessId.offset,
            spi_off_name=SYSTEM_PROCESS_INFORMATION.ImageName.offset,
            spi_off_create_time=SYSTEM_PROCESS_INFORMATION.CreateTime.offset,
            spi_ptr_size=ptr_size,
            spi_struct_ulong=struct.Struct('<I'),
            spi_struct_ushort=struct.Struct('<H'),
            spi_struct_longlong=struct.Struct('<q'),
            spi_struct_ptr=struct.Struct('<Q' if ptr_size == 8 else '<I'),
        )


def _parsed_config_alias(field_name):
    """Alias an EsportsIsolatorPro attribute to a ParsedConfig field.

    Reads come from self._parsed_config, and writes (tests toggling
    isolator.games, _register_capability_defaults forcing
    event_backend="poll") go back into it — so the parsed dataclass stays
    the single source of truth instead of an init-time copy that can drift.
    """
    def _get(self):
        return getattr(self._parsed_config, field_name)

    def _set(self, value):
        setattr(self._parsed_config, field_name, value)

    return property(_get, _set)


class EsportsIsolatorPro(
    BaseMixin,
    DiscoveryMixin,
    IfeoPowerMixin,
    RecoveryMixin,
    TopologyMixin,
    TuningMixin,
    RuntimeMixin,
):
    # ParsedConfig-backed aliases (see _parsed_config_alias above). The
    # anti_cheat_mode field is NOT aliased: __init__ validates it and stores
    # the sanitized value as a plain attribute.
    games = _parsed_config_alias("games")
    auto_detect_steam = _parsed_config_alias("auto_detect_steam")
    auto_detect_epic = _parsed_config_alias("auto_detect_epic")
    steam_library_paths = _parsed_config_alias("steam_library_paths")
    epic_library_paths = _parsed_config_alias("epic_library_paths")
    app_profiles = _parsed_config_alias("app_profiles")
    housekeeping_core_count = _parsed_config_alias("housekeeping_core_count")
    poll_interval_idle_s = _parsed_config_alias("poll_interval_idle_s")
    poll_interval_active_s = _parsed_config_alias("poll_interval_active_s")
    enable_background_jailing = _parsed_config_alias("enable_background_jailing")
    maintenance_jail_batch_size = _parsed_config_alias("maintenance_jail_batch_size")
    maintenance_jail_interval_s = _parsed_config_alias("maintenance_jail_interval_s")
    maintenance_jail_batch_cooldown_s = _parsed_config_alias("maintenance_jail_batch_cooldown_s")
    game_close_debounce_s = _parsed_config_alias("game_close_debounce_s")
    game_exit_restore_delay_s = _parsed_config_alias("game_exit_restore_delay_s")
    gc_full_collect_interval_s = _parsed_config_alias("gc_full_collect_interval_s")
    maintenance_skip_after_quiet_cycles = _parsed_config_alias("maintenance_skip_after_quiet_cycles")
    event_backend = _parsed_config_alias("event_backend")
    allow_mmcss_injection = _parsed_config_alias("allow_mmcss_injection")
    _disable_timer_resolution_tweak = _parsed_config_alias("disable_timer_resolution_tweak")
    _disable_game_priority_boost = _parsed_config_alias("disable_game_priority_boost")
    # WHY: Escape hatch for the user-reported issue where Windows /
    # third-party tools accumulated multiple "Ultimate Performance"
    # power plans over time. Setting this to True skips the power-
    # scheme switch entirely, leaving the user's plan untouched.
    _disable_power_scheme_switch = _parsed_config_alias("disable_power_scheme_switch")

    def __init__(self, config_path="config.json", scan_game_libraries=True):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        self.config_path = config_path
        self.config = self._load_config()
        # The ParsedConfig-backed attributes (games, auto_detect_*, poll
        # intervals, ...) are class-level property aliases over this dataclass;
        # no per-field copies are made here.
        self._parsed_config = ParsedConfig.from_config(self, self.config)
        self._log_file_path = None
        self._log_file_handle = None
        self._log_use_timestamp = False
        log_file = self.config.get("log_file")
        if isinstance(log_file, str) and log_file.strip():
            self.set_log_file(log_file.strip())
        self.protected_exact = {
            "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
            "lsass.exe", "lsaiso.exe", "winlogon.exe", "svchost.exe", "spoolsv.exe", "dwm.exe",
            "explorer.exe", "audiodg.exe", "rdpclip.exe", "sihost.exe", "taskmgr.exe",
            "conhost.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe",
            "windowsterminal.exe", "openconsole.exe",
            "steam.exe", "steamwebhelper.exe", "gameoverlayui.exe", "steamservice.exe", "steamerrorreporter.exe",
            "gameoverlayui64.exe", "faceitclient.exe", "faceitservice.exe", "rtkauduservice64.exe",
            "eadesktop.exe",
            # WHY: System / security / input services observed in field logs being
            # jailed. wmiprvse: anti-cheats query WMI (Vanguard/BattlEye/EAC) —
            # throttling risks false-positive bans. fontdrvhost: SYSTEM font
            # driver, jailing causes DirectWrite hitches in HUDs. smartscreen:
            # security service. taskhostw: Task Scheduler host. gameinput*:
            # controller/gamepad runtime — throttling directly harms input
            # latency in the very game we're optimizing for.
            "wmiprvse.exe", "fontdrvhost.exe", "smartscreen.exe", "taskhostw.exe",
            "gameinputredistservice.exe", "gameinputsvc.exe",
        }
        self.protected_prefixes = (
            "easyanticheat", "vgc", "beservice", "battleye", "vgtray", "nvdisplay.container",
            "nvcontainer", "nvidia", "nvapp", "nvsphelper", "amdrsserv", "riotclient", "rustclient", "xbox",
            # WHY: Future-proof against Microsoft renaming the GameInput
            # service (gameinputredist→gameinputsvc rename observed in
            # Windows 11 24H2). Match any gameinput* binary.
            "gameinput",
        )
        own_exe = os.path.basename(sys.executable).lower()
        if own_exe:
            self.protected_exact.add(own_exe)
        protected_extra = self.config.get("protected_extra", [])
        if isinstance(protected_extra, list):
            for name in protected_extra:
                if isinstance(name, str):
                    normalized = self._normalize_game_name(name)
                    if normalized:
                        self.protected_exact.add(normalized)
        self.ultimate_guid = make_guid(ULTIMATE_PERFORMANCE_GUID)
        self.high_performance_guid = make_guid(HIGH_PERFORMANCE_GUID)
        self._runtime_state = RuntimeState()
        state = self._runtime_state
        self._win32_scratch = Win32Scratch.create()
        scratch = self._win32_scratch
        self._spi_buffer = scratch.spi_buffer
        self._self_pid = int(kernel32.GetCurrentProcessId())
        self._parent_pid = int(os.getppid())
        self._last_fg_transition_time = 0.0
        self._foreground_transition_debounce_s = 0.5
        self._state_lock = state.state_lock
        # WHY (item 11): Serialize topology REBUILDS so the monitor thread and
        # an API-triggered refresh (get_topology_snapshot(refresh=True)) can
        # never run the Win32 enumeration + field rebind concurrently. This is
        # a separate lock from _state_lock: the expensive Win32 enumeration runs
        # under _topology_lock (NOT _state_lock), and only the final field
        # assignment is taken briefly under _state_lock so API reads stay fast.
        self._topology_lock = threading.RLock()
        self._mutation_idle = threading.Condition(self._state_lock)
        self._active_mutations = state.active_mutations
        self._shutting_down = state.shutting_down
        self._touched = state.touched
        self._active_games = state.active_games
        self._ifeo_original = state.ifeo_original
        self._monitor_thread = state.monitor_thread
        self._stop_event = state.stop_event
        self._shutdown_done = state.shutdown_done
        self._mutex_handle = state.mutex_handle
        self._original_power_scheme = state.original_power_scheme
        self._power_plan_active = state.power_plan_active
        self._power_scheme_in_use = state.power_scheme_in_use
        # WHY (item 3): Track a power-scheme set that succeeded but failed its
        # verify readback so _restore_power_scheme still reverts it even though
        # _power_plan_active was never set True.
        self._power_scheme_set_unverified = False
        self._power_scheme_unverified_in_use = None
        self._persistent_recovery_incomplete = state.persistent_recovery_incomplete
        self._timer_resolution_applied = state.timer_resolution_applied
        self._capability_notes = state.capability_notes
        self._capability_notes_seen = state.capability_notes_seen
        self._capability_issues = state.capability_issues
        self._capability_issues_seen = state.capability_issues_seen
        self._reported_failures = state.reported_failures
        self._reported_failure_ttl_s = 3600.0
        self._reported_failure_limit = 5000
        self._reported_failure_message_chars = 96
        self._reported_failure_prune_interval_s = 60.0
        self._last_reported_failure_prune = 0.0
        anti_cheat_mode = self._parsed_config.anti_cheat_mode
        if anti_cheat_mode not in ("aggressive", "conservative"):
            self._log_once(
                ("anti_cheat_mode_invalid", anti_cheat_mode),
                f"[WARN] Unknown anti_cheat_mode '{anti_cheat_mode}'; using aggressive.",
            )
            anti_cheat_mode = "aggressive"
        self.anti_cheat_mode = anti_cheat_mode
        self._is_admin = self._check_admin()
        self._topology = state.topology
        self._cpu_partitions = state.cpu_partitions
        self._cpu_sets_by_id = state.cpu_sets_by_id
        self._boosted_critical = state.boosted_critical
        self._last_topology_refresh = state.last_topology_refresh
        self._last_steam_scan = state.last_steam_scan
        self._last_epic_scan = state.last_epic_scan
        self._steam_games_cache = state.steam_games_cache
        self._epic_games_cache = state.epic_games_cache
        self._library_scan_ready = state.library_scan_ready
        self._library_scan_thread = state.library_scan_thread
        self._discovery_issues = state.discovery_issues
        self._known_non_games = state.known_non_games
        self._path_classification_cache = state.path_classification_cache
        self._process_create_times = state.process_create_times
        self._protected_cache = state.protected_cache
        self._entry_gen = state.entry_gen
        # WHY: Pre-allocate reusable ctypes objects once instead of creating them
        # every poll cycle. wintypes.DWORD() for foreground PID tracking and
        # wintypes.ULONG() for NtQuerySystemInformation buffer_size are created
        # ~500 times/s in the hot path. Pre-allocation avoids that churn entirely.
        self._fg_pid_dword = scratch.fg_pid_dword
        self._spi_buffer_size = scratch.spi_buffer_size
        # WHY: Pre-compute SYSTEM_PROCESS_INFORMATION field offsets at init time.
        # These let _get_processes read raw memory at fixed byte positions instead
        # of calling ctypes.cast() + .contents per process entry. ctypes.cast is
        # expensive: it constructs a new Python wrapper object for the underlying
        # C struct on every call. With ~300 processes, that's 300 wrapper objects
        # per poll cycle (every 2s during game mode) — all instantly becoming
        # garbage. Raw offset reads produce only int/str primitives.
        self._spi_off_next = scratch.spi_off_next
        self._spi_off_pid = scratch.spi_off_pid
        self._spi_off_name = scratch.spi_off_name
        self._spi_off_create_time = scratch.spi_off_create_time
        self._spi_ptr_size = scratch.spi_ptr_size
        # WHY: Pre-compute the struct format strings for pointer-sized reads.
        # struct.unpack_from is the zero-copy alternative to .raw + int.from_bytes.
        # '<Q' reads 8 bytes on x64, '<I' reads 4 bytes on x86.
        self._spi_struct_ulong = scratch.spi_struct_ulong
        self._spi_struct_ushort = scratch.spi_struct_ushort
        self._spi_struct_longlong = scratch.spi_struct_longlong
        self._spi_struct_ptr = scratch.spi_struct_ptr
        self._register_capability_defaults()
        # WHY: Library scanning walks multi-terabyte game libraries and used
        # to block construction (and therefore CLI startup and the API
        # bridge's engine build) for seconds. It now runs on a daemon worker;
        # background jailing waits on _library_scan_ready so an auto-detected
        # game can never be classified as background before the caches are
        # warm — the same safety the old synchronous scan provided.
        if scan_game_libraries and (self.auto_detect_steam or self.auto_detect_epic):
            self._request_library_scan(force=True)
        else:
            self._library_scan_ready.set()

    def get_runtime_status(self):
        """Return a small read-only runtime snapshot for localhost UI bridges."""
        with self._state_lock:
            monitor_thread = self._monitor_thread
            touched_entries = [
                (int(pid), entry.get("name", ""), entry.get("source", ""))
                for pid, entry in self._touched.items()
            ]
            active_mutations = int(self._active_mutations)
            shutting_down = bool(self._shutting_down)
            shutdown_done = bool(self._shutdown_done)
            reported_failure_count = len(self._reported_failures)
            active_games = [dict(game) for game in self._active_games.values()]
            discovery_issues = [dict(issue) for issue in self._discovery_issues]
            capability_issues = copy.deepcopy(self._capability_issues)
            # WHY (item 11): Snapshot the partition/topology references under
            # the same lock that guards the rebind in _build_topology_map /
            # _select_cpu_partitions, so we never read a reference that is being
            # swapped by a concurrent _refresh_topology on the monitor thread.
            cpu_partitions = self._cpu_partitions
            topology_available = bool(self._topology)
            # Scalars the monitor thread mutates during power-scheme and timer
            # transitions; reading them under the same lock keeps the reported
            # status from mixing a pre-switch and post-switch view.
            is_admin = bool(self._is_admin)
            power_plan_active = bool(self._power_plan_active)
            power_scheme_in_use = self._power_scheme_in_use
            timer_resolution_applied = self._timer_resolution_applied
            persistent_recovery_incomplete = bool(self._persistent_recovery_incomplete)
            capability_notes = list(self._capability_notes)

        jailed_count = 0
        foreground_count = 0
        optimized_game_count = 0
        for _pid, _name, source in touched_entries:
            if source == "jail":
                jailed_count += 1
            elif source == "foreground":
                foreground_count += 1
            elif source == "optimize_game":
                optimized_game_count += 1

        active_games.sort(key=lambda game: (str(game.get("name", "")), int(game.get("pid", 0))))
        active_game_pids = sorted(int(game["pid"]) for game in active_games)
        game_mode = bool(active_games)
        partition_counts = {
            key: len(value) if isinstance(value, list) else 0
            for key, value in cpu_partitions.items()
            if key != "game_cores"
        }
        partition_counts["game_cores"] = len(cpu_partitions.get("game_cores", []))

        running = bool(
            monitor_thread
            and monitor_thread.is_alive()
            and not self._stop_event.is_set()
            and not shutdown_done
        )
        return {
            "running": running,
            "monitoring_active": running,
            "game_mode": game_mode,
            "active_games": active_games,
            "active_game_pids": active_game_pids,
            "active_game_count": len(active_games),
            "tracked_process_count": len(touched_entries),
            "jailed_process_count": jailed_count,
            "foreground_tracked_count": foreground_count,
            "optimized_game_count": optimized_game_count,
            "active_mutations": active_mutations,
            "shutting_down": shutting_down,
            "shutdown_done": shutdown_done,
            "admin": is_admin,
            "anti_cheat_mode": self.anti_cheat_mode,
            "background_jailing": bool(self.enable_background_jailing),
            "power_plan_active": power_plan_active,
            "power_scheme_in_use": power_scheme_in_use,
            "timer_resolution_applied": timer_resolution_applied,
            "persistent_recovery_incomplete": persistent_recovery_incomplete,
            "reported_failure_count": reported_failure_count,
            "capability_notes": capability_notes,
            "capability_issues": capability_issues,
            "discovery_issues": discovery_issues,
            "cpu_partitions": partition_counts,
            "topology_available": topology_available,
            "api": {
                "live_updates": "paused" if game_mode else "idle",
                "process_snapshots": "disabled",
            },
        }

    def get_live_snapshot(self):
        """Return live UI data without starting a parallel process poll."""
        status = self.get_runtime_status()
        active_games = {
            int(game["pid"]): dict(game)
            for game in status.get("active_games", [])
        }
        with self._state_lock:
            entries = [
                {
                    "pid": int(pid),
                    "name": entry.get("name", ""),
                    "source": entry.get("source", ""),
                    "gen": int(entry.get("gen", 0) or 0),
                    "create_time": int(entry.get("create_time", 0) or 0),
                    "thread_count": len(entry.get("threads", {})),
                    "priority_class": (entry.get("state", {}) or {}).get("priority_class"),
                    "cpu_set_ids": list((entry.get("state", {}) or {}).get("cpu_set_ids", [])),
                    "affinity_mask": (entry.get("state", {}) or {}).get("affinity_mask"),
                    "io_priority": (entry.get("state", {}) or {}).get("io_priority"),
                    "page_priority": (entry.get("state", {}) or {}).get("page_priority"),
                    "priority_boost_disabled": (entry.get("state", {}) or {}).get("priority_boost_disabled"),
                }
                for pid, entry in self._touched.items()
            ]
            process_create_times = dict(self._process_create_times)

        tracked_pids = {entry["pid"] for entry in entries}
        for pid, game in active_games.items():
            if pid in tracked_pids:
                continue
            entries.append({
                "pid": pid,
                "name": game.get("name", ""),
                "source": "observed_game",
                "gen": 0,
                "create_time": int(process_create_times.get(pid, 0) or 0),
                "thread_count": 0,
                "priority_class": None,
                "cpu_set_ids": [],
                "affinity_mask": None,
                "io_priority": None,
                "page_priority": None,
                "priority_boost_disabled": None,
            })

        active_game_pids = set(status.get("active_game_pids", []))
        processes = []
        for entry in entries:
            name = self._normalize_name(entry["name"])
            source = entry["source"]
            tuning_state = active_games.get(entry["pid"], {}).get("tuning_state")
            protected = bool(
                name in self.protected_exact
                or (name and name.startswith(self.protected_prefixes))
            )
            game = bool(
                entry["pid"] in active_game_pids
                or source == "optimize_game"
                or (source == "foreground" and self._is_game_name_normalized(name))
            )
            if game:
                marker = "game"
            elif source == "jail":
                marker = "jailed"
            elif source == "foreground":
                marker = "foreground"
            elif protected:
                marker = "protected"
            else:
                marker = "tracked"
            processes.append({
                **entry,
                "status": marker,
                "game": game,
                "protected": protected,
                "tuning_state": tuning_state,
            })

        processes.sort(key=lambda process: (process["status"] != "game", process["name"], process["pid"]))
        return {
            "status": status,
            "process_mode": "tracked_only",
            "process_count": len(processes),
            "processes": processes,
            "generated_at": time.time(),
            "api": {
                "process_snapshots": "tracked_only",
                "full_process_list": False,
                "reason": "Avoids parallel process polling from the API thread.",
            },
        }

    def get_topology_snapshot(self, refresh=False):
        """Return CPU topology and partition data formatted for UI core maps."""
        topology_lock = getattr(self, "_topology_lock", None)
        if topology_lock is None:
            return self._get_topology_snapshot_locked(refresh)
        with topology_lock:
            return self._get_topology_snapshot_locked(refresh)

    def _get_topology_snapshot_locked(self, refresh=False):
        status = self.get_runtime_status()
        refresh_info = {
            "requested": bool(refresh),
            "performed": False,
            "blocked_reason": None,
        }
        if refresh:
            if status.get("game_mode"):
                refresh_info["blocked_reason"] = "game_mode"
            else:
                with self._state_lock:
                    game_mode_now = any(
                        entry.get("source") == "optimize_game"
                        for entry in self._touched.values()
                        if isinstance(entry, dict)
                    )
                if game_mode_now:
                    refresh_info["blocked_reason"] = "game_mode"
                else:
                    self._refresh_topology("api")
                    refresh_info["performed"] = True
                    status = self.get_runtime_status()

        with self._state_lock:
            topology = self._topology or {}
            cpu_partitions = self._cpu_partitions
        cpu_sets = [dict(cpu) for cpu in topology.get("cpu_sets", [])]
        core_groups = [dict(core) for core in topology.get("core_groups", [])]
        llc_groups = [dict(llc) for llc in topology.get("llc_groups", [])]
        partitions = {
            "game": list(cpu_partitions.get("game", [])),
            "background": list(cpu_partitions.get("background", [])),
            "housekeeping": list(cpu_partitions.get("housekeeping", [])),
        }

        partition_by_cpu_set = {}
        for partition_name, cpu_set_ids in partitions.items():
            for cpu_set_id in cpu_set_ids:
                partition_by_cpu_set[int(cpu_set_id)] = partition_name

        max_efficiency = max((int(core.get("efficiency_class", 0)) for core in core_groups), default=0)
        min_efficiency = min((int(core.get("efficiency_class", 0)) for core in core_groups), default=0)
        heterogeneous = bool(topology.get("heterogeneous_efficiency", False))

        def key_id(prefix, key):
            if isinstance(key, (list, tuple)) and len(key) == 2:
                return f"g{int(key[0])}{prefix}{int(key[1])}"
            return ""

        def efficiency_type(efficiency_class):
            value = int(efficiency_class)
            if not heterogeneous:
                return "standard"
            if value == max_efficiency:
                return "performance"
            if value == min_efficiency:
                return "efficiency"
            return "mixed"

        cores = []
        core_partition_by_id = {}
        for core in core_groups:
            cpu_set_ids = [int(cpu_set_id) for cpu_set_id in core.get("cpu_set_ids", [])]
            partition = "unassigned"
            for candidate in ("game", "background", "housekeeping"):
                if any(partition_by_cpu_set.get(cpu_set_id) == candidate for cpu_set_id in cpu_set_ids):
                    partition = candidate
                    break
            core_id = key_id("c", core.get("key", (core.get("group", 0), core.get("core_index", 0))))
            llc_id = key_id("l", core.get("llc_key", (core.get("group", 0), core.get("llc_index", 0))))
            core_partition_by_id[core_id] = partition
            cores.append({
                "id": core_id,
                "group": int(core.get("group", 0)),
                "core_index": int(core.get("core_index", 0)),
                "llc_id": llc_id,
                "llc_index": int(core.get("llc_index", 0)),
                "efficiency_class": int(core.get("efficiency_class", 0)),
                "efficiency_type": efficiency_type(core.get("efficiency_class", 0)),
                "cpu_set_ids": cpu_set_ids,
                "logical_indices": [int(index) for index in core.get("logical_indices", [])],
                "logical_processor_count": len(core.get("logical_indices", [])),
                "parked": bool(core.get("parked", False)),
                "allocated": bool(core.get("allocated", False)),
                "realtime": bool(core.get("realtime", False)),
                "l3_size_bytes": int(core.get("l3_size", 0)),
                "partition": partition,
            })

        llc_response = []
        for llc in llc_groups:
            core_ids = [key_id("c", key) for key in llc.get("core_keys", [])]
            llc_response.append({
                "id": key_id("l", llc.get("key", (llc.get("group", 0), llc.get("llc_index", 0)))),
                "group": int(llc.get("group", 0)),
                "llc_index": int(llc.get("llc_index", 0)),
                "l3_size_bytes": int(llc.get("l3_size", 0)),
                "efficiency_class": int(llc.get("efficiency_class", 0)),
                "core_ids": core_ids,
                "core_count": len(core_ids),
            })

        partition_response = {}
        for partition_name in ("game", "background", "housekeeping"):
            cpu_set_ids = partitions[partition_name]
            core_ids = [
                core["id"] for core in cores
                if core_partition_by_id.get(core["id"]) == partition_name
            ]
            partition_response[partition_name] = {
                "label": {
                    "game": "Game",
                    "background": "Background",
                    "housekeeping": "Housekeeping",
                }[partition_name],
                "cpu_set_ids": cpu_set_ids,
                "logical_processor_count": len(cpu_set_ids),
                "core_ids": core_ids,
                "core_count": len(core_ids),
            }

        return {
            "available": bool(topology),
            "status": status,
            "refresh": refresh_info,
            "summary": {
                "logical_processor_count": len(cpu_sets),
                "core_count": len(cores),
                "llc_group_count": len(llc_response),
                "heterogeneous_efficiency": heterogeneous,
                "multi_llc": bool(topology.get("multi_llc", False)),
                "last_refresh_monotonic_s": float(self._last_topology_refresh or 0.0),
            },
            "cores": cores,
            "llc_groups": llc_response,
            "cpu_sets": cpu_sets,
            "partitions": partition_response,
        }
