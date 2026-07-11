"""Dashboard monitoring KPIs — pure functions for ops and research pipeline cards."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

SHADOW_MACRO_F1_HEALTHY = 0.50
SHADOW_LOSS_RECALL_HEALTHY = 0.80

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
