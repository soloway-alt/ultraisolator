"""Lifecycle bridge between the localhost API and EsportsIsolatorPro."""

import threading
import time
from contextlib import contextmanager

from isolator.app import EsportsIsolatorPro
from isolator.winapi import is_process_elevated

from .analysis import build_analysis_payload
from .config_store import ConfigStore
from .log_store import read_log_payload
from .msi import build_msi_payload, read_msi_devices
from .readiness import build_readiness_payload


class BridgeConflict(RuntimeError):
    """Raised when a requested lifecycle action is not currently valid."""


class AdministratorRequired(PermissionError):
    """Raised before a privileged lifecycle action in a non-elevated process."""


def _default_engine_factory(config_path, scan_game_libraries):
    return EsportsIsolatorPro(
        config_path=config_path,
        scan_game_libraries=scan_game_libraries,
    )


class IsolatorBridge:
    def __init__(self, config_path="config.json", engine_factory=None, config_store=None, admin_check=None):
        self.config_path = config_path
        self._engine_factory = engine_factory or _default_engine_factory
        self._config_store = config_store or ConfigStore(config_path)
        self._admin_check = admin_check or is_process_elevated
        self._lock = threading.Lock()
        # FIX 5: dedicated lifecycle lock serializes start()/stop() so a new
        # engine is never built while a previous one is still shutting down.
        self._lifecycle_lock = threading.Lock()
        self._engine = None
        self._live_clients = 0
        self._notification_state = None
        self._notification_sequence = 0
        self._readiness_cache = None
        self._readiness_cache_monotonic = 0.0
        self._readiness_cache_ttl_s = 300
        self._msi_cache = None
        self._msi_cache_monotonic = 0.0
        self._msi_cache_ttl_s = 300
        self._status_config = self._read_status_config()

    def _read_status_config(self):
        try:
            config = self._config_store.read().get("config", {})
        except Exception:
            config = {}
        return {
            "anti_cheat_mode": str(config.get("anti_cheat_mode", "aggressive") or "aggressive"),
            "background_jailing": bool(config.get("enable_background_jailing")),
            "disable_timer_resolution_tweak": bool(config.get("disable_timer_resolution_tweak")),
            "disable_power_scheme_switch": bool(config.get("disable_power_scheme_switch")),
            "disable_game_priority_boost": bool(config.get("disable_game_priority_boost")),
        }

    def _check_current_admin(self):
        try:
            return bool(self._admin_check())
        except Exception:
            return False

    def _require_admin(self):
        if not self._check_current_admin():
            raise AdministratorRequired("administrator_required")

    @staticmethod
    def _release_transient_engine(engine):
        # FIX 4: short-lived engines (topology refresh / recovery) open a log
        # file handle in __init__; release it without running the heavy
        # shutdown() side effects. _close_log_file() is the minimal teardown.
        close = getattr(engine, "_close_log_file", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _stopped_status(self):
        config = dict(self._status_config)
        return {
            "running": False,
            "monitoring_active": False,
            "game_mode": False,
            "active_games": [],
            "active_game_pids": [],
            "active_game_count": 0,
            "tracked_process_count": 0,
            "jailed_process_count": 0,
            "foreground_tracked_count": 0,
            "optimized_game_count": 0,
            "active_mutations": 0,
            "shutting_down": False,
            "shutdown_done": False,
            "admin": self._check_current_admin(),
            "anti_cheat_mode": config["anti_cheat_mode"],
            "background_jailing": config["background_jailing"],
            "power_plan_active": False,
            "power_scheme_in_use": None,
            "timer_resolution_applied": None,
            "persistent_recovery_incomplete": False,
            "reported_failure_count": 0,
            "capability_issues": [],
            "capability_notes": [],
            "discovery_issues": [],
            "cpu_partitions": {"game": 0, "background": 0, "housekeeping": 0, "game_cores": 0},
            "topology_available": False,
            "config": config,
            "api": {
                "live_updates": "idle",
                "process_snapshots": "disabled",
            },
        }

    def status(self):
        with self._lock:
            engine = self._engine
        if engine is None:
            return self._stopped_status()
        # The engine has no "config" key; the Dashboard reads status.config.*
        # for the power/timer indicators, so the bridge merges the persisted
        # toggles into BOTH branches. Copy — never mutate the engine's dict.
        status = dict(engine.get_runtime_status())
        status["config"] = dict(self._status_config)
        return status

    def live_client_count(self):
        with self._lock:
            return self._live_clients

    @contextmanager
    def live_client(self):
        with self._lock:
            self._live_clients += 1
        try:
            yield
        finally:
            with self._lock:
                self._live_clients = max(0, self._live_clients - 1)

    def live_interval_seconds(self, snapshot):
        status = snapshot.get("status", {}) if isinstance(snapshot, dict) else {}
        return 5.0 if status.get("game_mode") else 2.0

    def live_snapshot(self):
        with self._lock:
            engine = self._engine
            live_clients = self._live_clients
        if engine is None:
            snapshot = {
                "status": self._stopped_status(),
                "process_mode": "none",
                "process_count": 0,
                "processes": [],
            }
        else:
            snapshot = engine.get_live_snapshot()

        api = dict(snapshot.get("api", {}))
        interval_s = self.live_interval_seconds(snapshot)
        api.update({
            "live_clients": live_clients,
            "lazy_push": True,
            "interval_ms": int(interval_s * 1000),
        })
        snapshot["api"] = api
        return snapshot

    def notifications_for_snapshot(self, snapshot):
        status = dict(snapshot.get("status", {}) if isinstance(snapshot, dict) else {})
        current = {
            "running": bool(status.get("running")),
            "game_mode": bool(status.get("game_mode")),
            "active_game_pids": tuple(status.get("active_game_pids") or ()),
            "jailed_process_count": int(status.get("jailed_process_count", 0) or 0),
            "power_plan_active": bool(status.get("power_plan_active")),
            "reported_failure_count": int(status.get("reported_failure_count", 0) or 0),
        }
        with self._lock:
            previous = self._notification_state
            if previous is None:
                self._notification_state = current
                return []

            events = self._build_notification_events(previous, current)
            self._notification_state = current
            for event in events:
                self._notification_sequence += 1
                event["id"] = f"n{self._notification_sequence}"
                event["timestamp"] = time.time()
            return events

    def _build_notification_events(self, previous, current):
        events = []
        if previous["running"] != current["running"]:
            events.append(self._notification(
                "engine_started" if current["running"] else "engine_stopped",
                "info",
                "Isolator started" if current["running"] else "Isolator stopped",
                "The engine is running." if current["running"] else "The engine has stopped and restored state.",
                data={"monitoring_active": current["running"]},
            ))
        if previous["game_mode"] != current["game_mode"]:
            if current["game_mode"]:
                pids = ", ".join(str(pid) for pid in current["active_game_pids"]) or "not reported"
                events.append(self._notification(
                    "game_detected",
                    "info",
                    "Game mode active",
                    f"Detected game process PID {pids}.",
                    suppress_in_game_mode=True,
                    data={"pids": list(current["active_game_pids"])},
                ))
            else:
                events.append(self._notification(
                    "game_closed",
                    "info",
                    "Game mode ended",
                    "Game processes closed; restore flow can complete.",
                    data={"pids": list(previous["active_game_pids"])},
                ))
        if current["jailed_process_count"] > previous["jailed_process_count"]:
            delta = current["jailed_process_count"] - previous["jailed_process_count"]
            events.append(self._notification(
                "background_jailed",
                "info",
                "Background jailing updated",
                f"{delta} additional background process{'es' if delta != 1 else ''} jailed.",
                suppress_in_game_mode=True,
                data={"count": delta},
            ))
        if previous["power_plan_active"] != current["power_plan_active"]:
            events.append(self._notification(
                "power_plan_switched" if current["power_plan_active"] else "power_plan_restored",
                "info",
                "Power plan active" if current["power_plan_active"] else "Power plan restored",
                "Performance power plan is active." if current["power_plan_active"] else "Original power plan restored.",
                suppress_in_game_mode=current["power_plan_active"],
                data={"active": current["power_plan_active"]},
            ))
        if current["reported_failure_count"] > previous["reported_failure_count"]:
            events.append(self._notification(
                "engine_error",
                "error",
                "Isolator reported a failure",
                "Open Logs for recovery details.",
                data={
                    "count": current["reported_failure_count"],
                    "new_count": current["reported_failure_count"] - previous["reported_failure_count"],
                },
            ))
        return events

    def _notification(self, event_type, severity, title, message, suppress_in_game_mode=False, data=None):
        return {
            "type": event_type,
            "severity": severity,
            "title": title,
            "message": message,
            "data": dict(data or {}),
            "suppress_in_game_mode": bool(suppress_in_game_mode),
        }

    def get_config_defaults(self):
        return self._config_store.defaults_response()

    def get_config(self):
        payload = self._config_store.read()
        self._status_config = self._read_status_config()
        return payload

    def update_config(self, candidate):
        with self._lock:
            running = bool(self._engine and self._engine.get_runtime_status().get("running"))
        payload = self._config_store.update(candidate, running=running)
        self._status_config = self._read_status_config()
        self._invalidate_derived_caches()
        return payload

    def _invalidate_derived_caches(self):
        # Readiness embeds config-derived checks; a config change must not
        # keep serving the pre-change verdict for the rest of the cache TTL.
        with self._lock:
            self._readiness_cache = None
            self._readiness_cache_monotonic = 0.0
            self._msi_cache = None
            self._msi_cache_monotonic = 0.0

    def topology(self, refresh=False):
        with self._lock:
            engine = self._engine
        if engine is not None:
            return engine.get_topology_snapshot(refresh=refresh)
        if refresh:
            # FIX 4: release the transient engine's log handle after use.
            temp_engine = self._engine_factory(self.config_path, False)
            try:
                return temp_engine.get_topology_snapshot(refresh=True)
            finally:
                self._release_transient_engine(temp_engine)
        return {
            "available": False,
            "status": self._stopped_status(),
            "refresh": {
                "requested": False,
                "performed": False,
                "blocked_reason": "engine_stopped",
            },
            "summary": {
                "logical_processor_count": 0,
                "core_count": 0,
                "llc_group_count": 0,
                "heterogeneous_efficiency": False,
                "multi_llc": False,
                "last_refresh_monotonic_s": 0.0,
            },
            "cores": [],
            "llc_groups": [],
            "cpu_sets": [],
            "partitions": {
                "game": {"label": "Game", "cpu_set_ids": [], "logical_processor_count": 0, "core_ids": [], "core_count": 0},
                "background": {"label": "Background", "cpu_set_ids": [], "logical_processor_count": 0, "core_ids": [], "core_count": 0},
                "housekeeping": {"label": "Housekeeping", "cpu_set_ids": [], "logical_processor_count": 0, "core_ids": [], "core_count": 0},
            },
        }

    def analysis(self):
        status = self.status()
        if status.get("game_mode"):
            return build_analysis_payload(status, {}, {}, topology_refreshes=0)
        topology = self.topology(refresh=False)
        config = self._config_store.read().get("config", {})
        return build_analysis_payload(status, topology, config, topology_refreshes=0)

    def readiness(self, refresh=False):
        status = self.status()
        if status.get("game_mode"):
            return build_readiness_payload(
                status,
                {},
                {},
                cache_hit=False,
                generated_at=time.time(),
                cache_ttl_s=self._readiness_cache_ttl_s,
            )

        now = time.monotonic()
        with self._lock:
            cache = self._readiness_cache
            cache_age = now - self._readiness_cache_monotonic
        if not refresh and cache is not None and cache_age < self._readiness_cache_ttl_s:
            cached = dict(cache)
            cached["cache"] = dict(cached.get("cache", {}), hit=True)
            return cached

        topology = self.topology(refresh=False)
        config = self._config_store.read().get("config", {})
        payload = build_readiness_payload(
            status,
            topology,
            config,
            cache_hit=False,
            generated_at=time.time(),
            cache_ttl_s=self._readiness_cache_ttl_s,
        )
        with self._lock:
            self._readiness_cache = payload
            self._readiness_cache_monotonic = now
        return payload

    def logs(self, limit=500):
        config = self._config_store.read()["config"]
        log_file = config.get("log_file", "")
        return read_log_payload(log_file, limit=limit)

    def msi_devices(self, refresh=False):
        status = self.status()
        if status.get("game_mode"):
            return build_msi_payload(
                status,
                [],
                available=False,
                reason="paused_in_game_mode",
                cache_hit=False,
                generated_at=time.time(),
                cache_ttl_s=self._msi_cache_ttl_s,
            )

        now = time.monotonic()
        with self._lock:
            cache = self._msi_cache
            cache_age = now - self._msi_cache_monotonic
        if not refresh and cache is not None and cache_age < self._msi_cache_ttl_s:
            cached = dict(cache)
            cached["cache"] = dict(cached.get("cache", {}), hit=True)
            return cached

        available, reason, devices = read_msi_devices()
        status = self.status()
        if status.get("game_mode"):
            return build_msi_payload(
                status,
                [],
                available=False,
                reason="paused_in_game_mode",
                cache_hit=False,
                generated_at=time.time(),
                cache_ttl_s=self._msi_cache_ttl_s,
            )
        payload = build_msi_payload(
            status,
            devices,
            available=available,
            reason=reason,
            cache_hit=False,
            generated_at=time.time(),
            cache_ttl_s=self._msi_cache_ttl_s,
        )
        with self._lock:
            self._msi_cache = payload
            self._msi_cache_monotonic = now
        return payload

    def start(self):
        self._require_admin()
        # FIX 5: hold the lifecycle lock across the whole start transition so a
        # racing stop() cannot tear down (or a second start build) a competing
        # engine mid-flight, which previously spawned two monitor threads / a
        # single-instance-mutex clash and could leave _engine=None.
        with self._lifecycle_lock:
            with self._lock:
                engine = self._engine
            if engine is not None:
                status = engine.get_runtime_status()
                if status.get("running"):
                    return {"ok": True, "already_running": True, "status": status}
                # Stale, non-running engine: release it before building anew.
                self._release_transient_engine(engine)
                with self._lock:
                    self._engine = None

            engine = self._engine_factory(self.config_path, True)
            started = engine.run()
            if not started:
                self._release_transient_engine(engine)
                return {"ok": False, "already_running": False, "status": self._stopped_status()}
            with self._lock:
                self._engine = engine
            return {
                "ok": True,
                "already_running": False,
                "status": engine.get_runtime_status(),
            }

    def stop(self):
        # FIX 5: serialize against start() so its shutdown() completes before
        # any new engine can be created; _engine is detached under _lock first.
        with self._lifecycle_lock:
            with self._lock:
                engine = self._engine
                self._engine = None
            if engine is None:
                return {"ok": True, "status": self._stopped_status()}
            engine.shutdown()
            return {"ok": True, "status": self._stopped_status()}

    def recover(self):
        self._require_admin()
        with self._lock:
            engine = self._engine
            if engine is not None and engine.get_runtime_status().get("running"):
                raise BridgeConflict("Stop the isolator before running recovery.")
        recovery_engine = self._engine_factory(self.config_path, False)
        # FIX 4: release the recovery engine's log handle after use.
        try:
            return {"ok": bool(recovery_engine.recover())}
        finally:
            self._release_transient_engine(recovery_engine)
