"""Dashboard monitoring KPIs — pure functions for ops and research pipeline cards."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

SHADOW_MACRO_F1_HEALTHY = 0.50
SHADOW_LOSS_RECALL_HEALTHY = 0.80

# Current stall/timeout window for runtime stability (Stage 13).
CURRENT_STALL_WINDOW_S = 15 * 60

WATCH_TRADING_STATES = frozenset({"REVERSAL_WATCH", "OBSERVE", "STAND_ASIDE"})
NO_ENTRY_POSTURES = frozenset(
    {
        "BLOCK_ALL_ENTRIES",
        "MONITOR_ONLY",
        "WATCHLIST_ONLY",
        "ALERT_PASSIVE",
        "ENTRY_ELIGIBLE_WAIT_CONFIRM",
    }
)


def latest_by_engine(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in records:
        engine = row.get("engine")
        if engine:
            latest[str(engine)] = row
    return latest


def count_latest_status(
    records: list[dict[str, Any]],
    status: str,
    *,
    is_required: Callable[[str], bool] | None = None,
) -> int:
    latest = latest_by_engine(records)
    count = 0
    for engine, row in latest.items():
        if row.get("status") != status:
            continue
        if is_required is not None and not is_required(engine):
            continue
        count += 1
    return count


def count_optional_latest_status(
    records: list[dict[str, Any]],
    status: str,
    *,
    is_required: Callable[[str], bool],
) -> int:
    latest = latest_by_engine(records)
    count = 0
    for engine, row in latest.items():
        if row.get("status") != status:
            continue
        if is_required(engine):
            continue
        count += 1
    return count


def derive_pipeline_heartbeat(
    *,
    failed_health: int,
    timeout_health: int,
    cycling: bool,
    cycle_count: int,
) -> str:
    """Pipeline heartbeat — required runtime health only (manifest-scoped)."""
    if cycle_count == 0:
        return "YELLOW"
    if failed_health > 0:
        return "RED"
    if timeout_health > 0:
        return "YELLOW"
    if cycling:
        return "GREEN"
    return "YELLOW"


def decision_level_and_label(
    *,
    entry_eligible: bool | None,
    trading_state: str | None,
    execution_posture: str | None,
    missing: bool,
) -> tuple[str, str]:
    """Business posture semantics — RED only when decision memories are missing."""
    if missing:
        return "GREY", "UNAVAILABLE"

    if entry_eligible is True:
        return "GREEN", "ENTRY_ELIGIBLE"

    state = (trading_state or "").upper()
    posture = (execution_posture or "").upper()

    if state == "STAND_ASIDE":
        return "YELLOW", "STAND_ASIDE"
    if state == "OBSERVE":
        return "YELLOW", "OBSERVE"
    if state == "REVERSAL_WATCH":
        return "YELLOW", "REVERSAL_WATCH"
    if posture == "BLOCK_ALL_ENTRIES":
        return "YELLOW", "NO_ENTRY"
    if posture in NO_ENTRY_POSTURES or state in WATCH_TRADING_STATES:
        return "YELLOW", "WATCH"
    return "YELLOW", "WATCH"


def drift_composite_level(
    *,
    psi: float | None,
    macro_f1: float | None,
    loss_recall: float | None,
    macro_f1_trend: float | None = None,
    loss_recall_trend: float | None = None,
) -> tuple[str, str]:
    """Severity considers PSI together with live shadow performance."""
    model_healthy = (
        macro_f1 is not None
        and macro_f1 >= SHADOW_MACRO_F1_HEALTHY
        and loss_recall is not None
        and loss_recall >= SHADOW_LOSS_RECALL_HEALTHY
    )
    performance_declining = (
        (macro_f1_trend is not None and macro_f1_trend < -0.05)
        or (loss_recall_trend is not None and loss_recall_trend < -0.05)
    )

    if psi is None:
        return "GREY", "Unknown"

    if psi > 0.25:
        if model_healthy and not performance_declining:
            return "YELLOW", "Monitor"
        return "RED", "Critical"

    if psi > 0.10 or performance_declining:
        return "YELLOW", "Warning"

    return "GREEN", "Stable"


def toxic_severity_level(
    *,
    events_last_7d: int,
    events_last_30d: int,
    trend: str,
    hours_since_last_routed: float | None = None,
    is_bulk_backfill: bool = False,
) -> tuple[str, str]:
    """Rate-based toxic severity on live router activity, not historical T0 backfill."""
    if is_bulk_backfill and events_last_7d == 0:
        return "GREEN", "Baseline loaded"

    if hours_since_last_routed is not None and hours_since_last_routed > 48:
        return "GREEN", "No recent activity"

    toxic_rate_7d = events_last_7d / 7.0
    toxic_rate_30d = events_last_30d / 30.0 if events_last_30d else 0.0

    if toxic_rate_7d >= 5.0 and trend == "UP":
        return "RED", "Critical"
    if toxic_rate_7d >= 3.0 and trend == "UP" and toxic_rate_7d > max(toxic_rate_30d * 1.5, 1.0):
        return "RED", "Critical"
    if toxic_rate_7d >= 2.0 or (trend == "UP" and toxic_rate_7d > max(toxic_rate_30d * 1.25, 0.5)):
        return "YELLOW", "Elevated"
    return "GREEN", "Normal"


def toxic_routing_is_bulk_backfill(propagation_timestamps: list[Any]) -> bool:
    """Detect one-shot backfill batches (single propagation second, many rows)."""
    if len(propagation_timestamps) < 100:
        return False
    try:
        import pandas as pd

        prop = pd.to_datetime(propagation_timestamps, utc=True, errors="coerce").dropna()
        if len(prop) < 100:
            return False
        spread_seconds = (prop.max() - prop.min()).total_seconds()
        return spread_seconds < 3600
    except Exception:
        return False


def governance_age_days(iso_timestamp: str | None) -> int | None:
    if not iso_timestamp:
        return None
    try:
        ts = datetime.fromisoformat(str(iso_timestamp).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
        return max(0, delta.days)
    except (TypeError, ValueError):
        return None


def _parse_event_epoch(value: Any) -> float | None:
    if value is None:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def classify_blocking_stalls(
    chain_events: list[dict[str, Any]],
    *,
    now: float | None = None,
    window_s: float = CURRENT_STALL_WINDOW_S,
    lookback: int = 50,
) -> dict[str, Any]:
    """Split TIMEOUT/STALL_DETECTED into current vs historical."""
    now_ts = now if now is not None else datetime.now(timezone.utc).timestamp()
    events = [
        e
        for e in (chain_events[-lookback:] if lookback else chain_events)
        if isinstance(e, dict) and e.get("event") in ("TIMEOUT", "STALL_DETECTED")
    ]
    current: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    for event in events:
        age = None
        epoch = _parse_event_epoch(event.get("timestamp"))
        if epoch is not None:
            age = now_ts - epoch
        if age is not None and age <= window_s:
            current.append(event)
        else:
            historical.append(event)

    latest_hist = None
    if historical:
        latest_hist = max(
            historical,
            key=lambda e: _parse_event_epoch(e.get("timestamp")) or 0.0,
        ).get("timestamp")

    latest_cur = None
    if current:
        latest_cur = max(
            current,
            key=lambda e: _parse_event_epoch(e.get("timestamp")) or 0.0,
        ).get("timestamp")

    return {
        "current_count": len(current),
        "historical_count": len(historical),
        "latest_current_at": latest_cur,
        "latest_historical_at": latest_hist,
        "current_events": current,
        "historical_events": historical,
    }


def resource_health_status(
    *,
    cpu_pct: float,
    memory_pct: float,
    disk_pct: float,
) -> dict[str, Any]:
    """Resource card status — separate from runtime infrastructure health."""
    reasons: list[str] = []
    status = "OPERATIONAL"
    if memory_pct > 95 or disk_pct > 95 or cpu_pct > 95:
        status = "CRITICAL"
    elif memory_pct >= 75 or disk_pct >= 90 or cpu_pct >= 90:
        status = "DEGRADED"

    if memory_pct >= 75:
        reasons.append(f"Resource warning: memory {memory_pct:.0f}%")
    if disk_pct >= 90:
        reasons.append(f"Resource warning: disk {disk_pct:.0f}%")
    if cpu_pct >= 90:
        reasons.append(f"Resource warning: cpu {cpu_pct:.0f}%")

    return {
        "status": status,
        "cpu_pct": round(float(cpu_pct), 1),
        "memory_pct": round(float(memory_pct), 1),
        "disk_pct": round(float(disk_pct), 1),
        "reason": reasons[0] if reasons else "Resources nominal",
        "reasons": reasons,
    }


def build_health_dimensions(
    *,
    runtime_status: str,
    runtime_reason: str,
    current_failures_count: int,
    failed_engine_count: int,
    required_datasets_stale_count: int,
    collectors_status: str,
    websocket_status: str,
    pipeline_status: str,
    resources: dict[str, Any],
    research_status: str,
    research_reason: str,
    governance_status: str,
    economic_status: str,
    shadow_status: str,
    toxic_status: str,
    historical_failures_count: int,
    historical_stalls_count: int,
    latest_historical_failure_at: str | None,
    latest_historical_stall_at: str | None,
    historical_reason: str,
) -> dict[str, Any]:
    """Three-layer health: runtime / research_validation / historical_audit + resources."""
    hist_status = "INFORMATIONAL"
    return {
        "runtime": {
            "status": runtime_status,
            "reason": runtime_reason,
            "current_failures_count": int(current_failures_count),
            "failed_engine_count": int(failed_engine_count),
            "required_datasets_stale_count": int(required_datasets_stale_count),
            "collectors_status": collectors_status,
            "websocket_status": websocket_status,
            "pipeline_status": pipeline_status,
        },
        "resources": resources,
        "research_validation": {
            "status": research_status,
            "reason": research_reason,
            "governance_status": governance_status,
            "economic_status": economic_status,
            "shadow_status": shadow_status,
            "toxic_status": toxic_status,
        },
        "historical_audit": {
            "status": hist_status,
            "historical_failures_count": int(historical_failures_count),
            "historical_stalls_count": int(historical_stalls_count),
            "latest_historical_failure_at": latest_historical_failure_at,
            "latest_historical_stall_at": latest_historical_stall_at,
            "reason": historical_reason,
        },
    }


def derive_system_health_level(
    *,
    runtime_status: str,
    resources_status: str,
) -> tuple[str, str | None]:
    """Top System Health from runtime + critical resources only.

    Returns (level, display_suffix) where level is HEALTHY|DEGRADED|CRITICAL
    and display_suffix may be OPERATIONAL_WITH_WARNINGS.
    """
    rt = runtime_status.upper()
    res = resources_status.upper()
    if rt == "CRITICAL" or res == "CRITICAL":
        return "CRITICAL", None
    if rt == "DEGRADED":
        return "DEGRADED", None
    if res == "DEGRADED":
        return "HEALTHY", "OPERATIONAL_WITH_WARNINGS"
    return "HEALTHY", None
