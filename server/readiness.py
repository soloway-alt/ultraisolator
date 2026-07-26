"""Read-only competitive gaming readiness checklist."""

from .capability import capability_warnings as _capability_warnings


def _check(check_id, label, status, detail, recommendation=None):
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": detail,
        "recommendation": recommendation,
    }


def build_readiness_payload(status, topology, config, cache_hit=False, generated_at=None, cache_ttl_s=300):
    status = dict(status or {})
    topology = dict(topology or {})
    config = dict(config or {})

    if status.get("game_mode"):
        return {
            "ok": True,
            "available": False,
            "reason": "paused_in_game_mode",
            "summary": {"ok": 0, "warning": 0, "error": 0, "total": 0},
            "checks": [],
            "cache": {
                "hit": bool(cache_hit),
                "ttl_s": int(cache_ttl_s),
                "generated_at": generated_at,
            },
        }

    configured_games = {
        str(name).strip().lower()
        for name in config.get("games", [])
        if isinstance(name, str) and name.strip()
    }
    timer_configured = not bool(config.get("disable_timer_resolution_tweak"))
    timer_applied = bool(status.get("timer_resolution_applied"))
    power_configured = not bool(config.get("disable_power_scheme_switch"))
    power_active = bool(status.get("power_plan_active"))
    capability_warnings = _capability_warnings(status)

    checks = [
        _check(
            "admin",
            "Administrator rights",
            "ok" if status.get("admin") else "error",
            "System-level tuning permissions are available." if status.get("admin") else "Run the app as Administrator.",
            None if status.get("admin") else "Restart the desktop app elevated.",
        ),
        _check(
            "power_plan",
            "Automatic performance mode",
            "ok" if power_active or power_configured else "warning",
            (
                status.get("power_scheme_in_use")
                or ("Ready to activate when a game starts." if power_configured else "Automatic performance mode is off.")
            ),
            None if power_active or power_configured else "Enable automatic performance mode in Settings.",
        ),
        _check(
            "timer_resolution",
            "Low-latency timer",
            "ok" if timer_applied or timer_configured else "warning",
            "Low-latency timer is active." if timer_applied else (
                "Ready for the next monitoring session." if timer_configured else "Low-latency timer is off."
            ),
            None if timer_applied or timer_configured else "Enable the low-latency timer in Settings.",
        ),
        _check(
            "configured_games",
            "Games to optimize",
            "ok" if configured_games else "warning",
            (
                f"{len(configured_games)} game{'s' if len(configured_games) != 1 else ''} configured."
                if configured_games
                else "No games are configured yet."
            ),
            None if configured_games else "Add at least one game in Settings.",
        ),
        _check(
            "background_jailing",
            "Background load control",
            "ok" if config.get("enable_background_jailing") else "warning",
            "Background load is limited while you play." if config.get("enable_background_jailing") else "Background load control is off.",
            None if config.get("enable_background_jailing") else "Enable background load control for stricter isolation.",
        ),
        _check(
            "ifeo_priority",
            "Game priority boost",
            "ok" if not config.get("disable_game_priority_boost") else "warning",
            "Game priority boost is ready." if not config.get("disable_game_priority_boost") else "Game priority boost is off.",
            None if not config.get("disable_game_priority_boost") else "Enable game priority boost unless compatibility testing requires otherwise.",
        ),
        _check(
            "topology",
            "CPU topology",
            "ok" if topology.get("available") else "warning",
            _topology_detail(topology),
            None if topology.get("available") else "Start the engine to populate CPU topology.",
        ),
        _check(
            "recovery",
            "Safe restore",
            "ok" if not status.get("persistent_recovery_incomplete") and not status.get("reported_failure_count") else "error",
            "Windows settings can be restored safely." if not status.get("persistent_recovery_incomplete") and not status.get("reported_failure_count") else "Some Windows settings still need to be restored.",
            None if not status.get("persistent_recovery_incomplete") and not status.get("reported_failure_count") else "Restore Windows settings before starting a match.",
        ),
        _check(
            "capability_notes",
            "Compatibility notices",
            "ok" if not capability_warnings else "warning",
            (
                "No compatibility issues were found."
                if not capability_warnings
                else str(capability_warnings[0].get("message") or capability_warnings[0].get("code"))
            ),
            None if not capability_warnings else "Review the technical details for this notice.",
        ),
    ]
    summary = {
        "ok": sum(1 for check in checks if check["status"] == "ok"),
        "warning": sum(1 for check in checks if check["status"] == "warning"),
        "error": sum(1 for check in checks if check["status"] == "error"),
        "total": len(checks),
    }
    return {
        "ok": True,
        "available": True,
        "reason": None,
        "summary": summary,
        "checks": checks,
        "cache": {
            "hit": bool(cache_hit),
            "ttl_s": int(cache_ttl_s),
            "generated_at": generated_at,
        },
    }


def _topology_detail(topology):
    if not topology.get("available"):
        return "CPU topology is not available."
    summary = topology.get("summary", {}) if isinstance(topology, dict) else {}
    cores = summary.get("core_count", 0) or 0
    logical = summary.get("logical_processor_count", 0) or 0
    return f"{cores} cores / {logical} logical processors mapped."
