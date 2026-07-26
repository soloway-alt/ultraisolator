"""Read-only system analysis and optimization score."""

from .capability import capability_warnings as _capability_warnings


def _append_category(categories, label):
    if label not in categories:
        categories.append(label)


def _grade_for_score(score):
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "strong"
    if score >= 60:
        return "fair"
    return "weak"


def _check(check_id, label, category, max_score, passed, detail_ok, detail_bad, bad_status="warning", partial_score=0):
    if passed:
        return {
            "id": check_id,
            "label": label,
            "category": category,
            "status": "ok",
            "score": int(max_score),
            "max_score": int(max_score),
            "detail": detail_ok,
            "recommendation": None,
        }
    return {
        "id": check_id,
        "label": label,
        "category": category,
        "status": bad_status,
        "score": int(partial_score),
        "max_score": int(max_score),
        "detail": detail_bad,
        "recommendation": detail_bad,
    }


def build_analysis_payload(status, topology, config, topology_refreshes=0):
    status = dict(status or {})
    topology = dict(topology or {})
    config = dict(config or {})

    if status.get("game_mode"):
        return {
            "ok": True,
            "available": False,
            "mode": "analysis",
            "reason": "paused_in_game_mode",
            "score": None,
            "grade": "paused",
            "summary": "Analysis paused during game mode.",
            "categories": [],
            "checks": [],
            "analysis_calls": {
                "status_reads": 1,
                "topology_refreshes": int(topology_refreshes),
                "config_reads": 0,
            },
        }

    summary = topology.get("summary", {}) if isinstance(topology, dict) else {}
    partitions = topology.get("partitions", {}) if isinstance(topology, dict) else {}
    capability_warnings = _capability_warnings(status)
    reported_failure_count = int(status.get("reported_failure_count", 0) or 0)

    checks = []
    categories: list[str] = []

    checks.append(_check(
        "admin",
        "Administrator rights",
        "Control plane",
        15,
        bool(status.get("admin")),
        "Admin rights are available for CPU Sets, IFEO, and power scheme work.",
        "Run the app elevated so isolator can apply system-level tuning.",
        bad_status="error",
    ))
    checks.append(_check(
        "engine_running",
        "Engine running",
        "Control plane",
        5,
        bool(status.get("running")),
        "The engine is running and can maintain optimization state.",
        "Start the isolator engine before relying on live optimization state.",
    ))
    checks.append(_check(
        "recovery_clean",
        "Recovery state clean",
        "Control plane",
        5,
        bool(not status.get("persistent_recovery_incomplete", False) and reported_failure_count == 0),
        "No recovery backlog or reported failures are blocking the engine.",
        "Resolve the recovery backlog or inspect the reported failures first.",
    ))

    topology_available = bool(topology.get("available"))
    core_count = int(summary.get("core_count", 0) or 0)
    llc_count = int(summary.get("llc_group_count", 0) or 0)
    game_partition = partitions.get("game", {}) if isinstance(partitions, dict) else {}
    background_partition = partitions.get("background", {}) if isinstance(partitions, dict) else {}
    housekeeping_partition = partitions.get("housekeeping", {}) if isinstance(partitions, dict) else {}
    has_complete_partition_layout = all(
        int(part.get("core_count", 0) or 0) > 0
        for part in (game_partition, background_partition, housekeeping_partition)
    )
    topology_quality = bool(
        topology_available
        and core_count >= 4
        and (bool(summary.get("heterogeneous_efficiency")) or bool(summary.get("multi_llc")) or llc_count >= 1)
    )

    checks.append(_check(
        "cpu_topology",
        "CPU topology available",
        "CPU isolation",
        15,
        topology_available,
        "Cached topology data is available for CPU Sets analysis.",
        "Topology data is missing, so isolation quality cannot be scored fully.",
        bad_status="error",
    ))
    checks.append(_check(
        "partition_layout",
        "Game/Background/Housekeeping partitions",
        "CPU isolation",
        10,
        has_complete_partition_layout,
        "All three partition buckets are populated.",
        "At least one partition bucket is empty, so the layout is less balanced.",
    ))
    checks.append(_check(
        "topology_quality",
        "Topology quality",
        "CPU isolation",
        5,
        topology_quality,
        "Hybrid or multi-LLC topology gives the isolator useful placement options.",
        "Topology is usable, but it does not expose extra placement advantages.",
        partial_score=2,
    ))

    timer_enabled = not bool(config.get("disable_timer_resolution_tweak"))
    timer_applied = status.get("timer_resolution_applied")
    timer_ready = bool(timer_enabled or timer_applied)
    power_enabled = not bool(config.get("disable_power_scheme_switch"))
    game_priority_enabled = not bool(config.get("disable_game_priority_boost"))

    checks.append(_check(
        "timer_resolution",
        "Timer resolution",
        "Latency tuning",
        10,
        timer_ready,
        "Low-latency timing is active." if timer_applied else "Low-latency timing is configured and ready.",
        "Low-latency timing is disabled.",
        partial_score=4 if not timer_enabled else 0,
        bad_status="info" if not timer_enabled else "warning",
    ))
    checks.append(_check(
        "power_scheme",
        "Power scheme automation",
        "Latency tuning",
        10,
        power_enabled,
        "Power scheme switching is enabled for game entry and exit.",
        "Power scheme switching is disabled, so Windows will stay on the user's current plan.",
        partial_score=4,
        bad_status="info",
    ))
    checks.append(_check(
        "game_priority",
        "Game priority/IFEO boost",
        "Latency tuning",
        5,
        game_priority_enabled,
        "Game priority and IFEO boosting are enabled.",
        "Game priority/IFEO boosting is disabled.",
        partial_score=1,
        bad_status="info",
    ))

    background_jailing_enabled = bool(config.get("enable_background_jailing"))
    notes_clean = len(capability_warnings) == 0

    checks.append(_check(
        "background_jailing",
        "Background jailing",
        "System health",
        10,
        background_jailing_enabled,
        "Background jailing is enabled.",
        "Background jailing is disabled.",
        partial_score=4,
        bad_status="info",
    ))
    checks.append(_check(
        "capability_notes",
        "Capability warnings",
        "System health",
        5,
        notes_clean,
        "No capability warnings were reported.",
        "Capability warnings are present and should be reviewed.",
        partial_score=max(0, 5 - min(5, len(capability_warnings) * 2)),
        bad_status="warning" if capability_warnings else "ok",
    ))
    checks.append(_check(
        "failure_count",
        "Recovery failures",
        "System health",
        5,
        reported_failure_count == 0 and not bool(status.get("persistent_recovery_incomplete")),
        "No reported failures are blocking recovery.",
        "Review the recovery backlog or reported failures.",
        bad_status="warning",
    ))

    score = sum(check["score"] for check in checks)
    if score > 100:
        score = 100
    if score < 0:
        score = 0

    for check in checks:
        _append_category(categories, check["category"])

    if score >= 90:
        summary_text = "Start ready: the current setup has strong CPU isolation and low-latency tuning in place."
    elif score >= 75:
        summary_text = "Good baseline: a few tuning gaps remain, but the system is close to ready."
    elif score >= 60:
        summary_text = "Mixed baseline: the isolator is helping, but there is still noticeable headroom."
    else:
        summary_text = "Weak baseline: admin rights, topology, or tuning controls are missing."

    return {
        "ok": True,
        "available": True,
        "mode": "analysis",
        "reason": None,
        "score": score,
        "grade": _grade_for_score(score),
        "summary": summary_text,
        "categories": categories,
        "checks": checks,
        "analysis_calls": {
            "status_reads": 1,
            "topology_refreshes": int(topology_refreshes),
            "config_reads": 1,
        },
        "topology": {
            "available": topology_available,
            "core_count": core_count,
            "llc_group_count": llc_count,
            "multi_llc": bool(summary.get("multi_llc")),
            "heterogeneous_efficiency": bool(summary.get("heterogeneous_efficiency")),
        },
        "runtime": {
            "running": bool(status.get("running")),
            "game_mode": bool(status.get("game_mode")),
            "admin": bool(status.get("admin")),
            "timer_resolution_applied": timer_applied,
            "power_scheme_in_use": status.get("power_scheme_in_use"),
        },
    }
