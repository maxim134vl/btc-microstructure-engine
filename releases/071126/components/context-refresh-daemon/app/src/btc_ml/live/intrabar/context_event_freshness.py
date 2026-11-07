"""Context-event provenance and freshness gates for LIVE1A materialization and LIVE1B."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Mapping

import pandas as pd

DEFAULT_CONTEXT_EVENT_MAX_AGE_SECONDS = 300.0

ENTRY_EVENT_TYPES = frozenset({"CONTEXT_START", "CONTEXT_FLIP"})
DELIVERY_MODE_RECOVERY = "RECOVERY"
CLOSED_BAR_CONTEXT_DECISION = "CLOSED_BAR_CONTEXT_DECISION"
CLOSED_BAR_MATERIALIZATION_SOURCE = "closed_bar_context_decision"

FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE_AGE = "STALE_AGE"
FRESHNESS_RESTART_BACKFILL = "STALE_RESTART_BACKFILL"
FRESHNESS_RECOVERY = "STALE_RECOVERY"
FRESHNESS_INVALID_PROVENANCE = "INVALID_PROVENANCE"

FRESHNESS_KIND_DECISION_AVAILABLE_AT = "decision_available_at"
FRESHNESS_KIND_EVENT_TIMESTAMP = "event_timestamp"
FRESHNESS_KIND_MATERIALIZED_TIMESTAMP = "materialized_timestamp"
FRESHNESS_KIND_SOURCE_BAR_TIMESTAMP = "source_bar_timestamp"
FRESHNESS_KIND_ORIGINAL_CONTEXT_TIMESTAMP = "original_context_timestamp"


def is_restart_backfill_event(event: Mapping[str, Any]) -> bool:
    if bool(event.get("restart_backfill")):
        return True
    if str(event.get("materialization_class") or "").upper() == "RESTART_BACKFILL":
        return True
    if bool(event.get("revalidated_after_restart")):
        return True
    if bool(event.get("recovered_after_restart")):
        return True
    if str(event.get("materialization_class") or "").upper() == "DURABLE_CONTEXT_RECOVERY":
        return True
    return False


def is_recovery_delivery_event(event: Mapping[str, Any]) -> bool:
    if str(event.get("delivery_mode") or "").upper() == DELIVERY_MODE_RECOVERY:
        return True
    return is_restart_backfill_event(event)


def is_closed_bar_context_decision(event: Mapping[str, Any]) -> bool:
    """True when the event was materialized from a completed-bar context decision."""
    for key in ("evaluation_mode", "materialization_class"):
        if str(event.get(key) or "").strip().upper() == CLOSED_BAR_CONTEXT_DECISION:
            return True
    source = str(event.get("materialization_source") or "").strip()
    if source.upper() == CLOSED_BAR_CONTEXT_DECISION:
        return True
    if source.lower() == CLOSED_BAR_MATERIALIZATION_SOURCE:
        return True
    return False


def resolve_context_event_max_age_seconds(
    *,
    configured: float | None = None,
) -> float:
    env_value = os.environ.get("CONTEXT_EVENT_MAX_AGE_SECONDS")
    if env_value is not None and str(env_value).strip():
        return float(env_value)
    if configured is not None:
        return float(configured)
    return DEFAULT_CONTEXT_EVENT_MAX_AGE_SECONDS


def _to_utc_ts(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    out = pd.Timestamp(ts)
    return out.tz_convert("UTC") if out.tzinfo is not None else out.tz_localize("UTC")


def original_context_timestamp(event: Mapping[str, Any]) -> pd.Timestamp | None:
    for key in (
        "original_context_timestamp",
        "context_origin_timestamp",
        "historical_context_origin_timestamp",
    ):
        ts = _to_utc_ts(event.get(key))
        if ts is not None:
            return ts
    return None


def _iso(ts: pd.Timestamp | None) -> str | None:
    if ts is None:
        return None
    return ts.isoformat().replace("+00:00", "Z")


def resolve_freshness_reference(
    event: Mapping[str, Any],
    *,
    max_age_seconds: float | None = None,
) -> tuple[pd.Timestamp | None, str | None]:
    """Return (timestamp, kind) used for execution freshness.

    Closed-bar live decisions age from ``decision_available_at``. Origin / bar
    timestamps stay diagnostic and must not make a fresh closed-bar decision
    look stale. Non-closed-bar events keep the origin-gap replay guard.
    """
    decision_ts = _to_utc_ts(event.get("decision_available_at"))
    event_ts = _to_utc_ts(event.get("event_timestamp"))
    materialized_ts = _to_utc_ts(event.get("materialized_timestamp"))
    source_bar_ts = _to_utc_ts(event.get("source_bar_timestamp"))
    origin = original_context_timestamp(event)

    if is_closed_bar_context_decision(event):
        if decision_ts is not None:
            return decision_ts, FRESHNESS_KIND_DECISION_AVAILABLE_AT
        if materialized_ts is not None:
            return materialized_ts, FRESHNESS_KIND_MATERIALIZED_TIMESTAMP
        if event_ts is not None:
            return event_ts, FRESHNESS_KIND_EVENT_TIMESTAMP
        if source_bar_ts is not None:
            return source_bar_ts, FRESHNESS_KIND_SOURCE_BAR_TIMESTAMP
        return None, None

    threshold = float(max_age_seconds or DEFAULT_CONTEXT_EVENT_MAX_AGE_SECONDS)
    if origin is not None and decision_ts is not None:
        gap_seconds = float((decision_ts - origin).total_seconds())
        if gap_seconds > threshold:
            return origin, FRESHNESS_KIND_ORIGINAL_CONTEXT_TIMESTAMP

    if decision_ts is not None:
        return decision_ts, FRESHNESS_KIND_DECISION_AVAILABLE_AT
    if event_ts is not None:
        return event_ts, FRESHNESS_KIND_EVENT_TIMESTAMP
    if origin is not None:
        return origin, FRESHNESS_KIND_ORIGINAL_CONTEXT_TIMESTAMP
    if source_bar_ts is not None:
        return source_bar_ts, FRESHNESS_KIND_SOURCE_BAR_TIMESTAMP
    return None, None


def causal_decision_timestamp(
    event: Mapping[str, Any],
    *,
    max_age_seconds: float | None = None,
) -> pd.Timestamp | None:
    """Timestamp used for entry-age checks (execution freshness reference)."""
    ts, _kind = resolve_freshness_reference(event, max_age_seconds=max_age_seconds)
    return ts


def compute_event_age_seconds(
    event: Mapping[str, Any],
    *,
    consumption_time: datetime | None = None,
    reference_timestamp: Any | None = None,
    max_age_seconds: float | None = None,
) -> float | None:
    causal = causal_decision_timestamp(event, max_age_seconds=max_age_seconds)
    if causal is None:
        return None
    reference = _to_utc_ts(reference_timestamp)
    if reference is None:
        reference = _to_utc_ts(event.get("materialized_timestamp"))
    if reference is None:
        now = consumption_time or datetime.now(timezone.utc)
        reference = pd.Timestamp(now).tz_convert("UTC")
    return float((reference - causal).total_seconds())


def compute_origin_age_seconds(
    event: Mapping[str, Any],
    *,
    materialized_timestamp: Any | None = None,
) -> float | None:
    origin = original_context_timestamp(event)
    if origin is None:
        return None
    reference = _to_utc_ts(materialized_timestamp)
    if reference is None:
        reference = _to_utc_ts(event.get("materialized_timestamp"))
    if reference is None:
        return None
    return float((reference - origin).total_seconds())


def evaluate_entry_freshness(
    event: Mapping[str, Any],
    *,
    max_age_seconds: float,
    consumption_time: datetime | None = None,
) -> str:
    etype = str(event.get("event_type") or event.get("type") or "").upper()
    if etype not in ENTRY_EVENT_TYPES:
        return FRESHNESS_FRESH
    if is_restart_backfill_event(event):
        return FRESHNESS_RESTART_BACKFILL
    if is_recovery_delivery_event(event):
        return FRESHNESS_RECOVERY
    age = compute_event_age_seconds(
        event,
        consumption_time=consumption_time,
        max_age_seconds=max_age_seconds,
    )
    if age is None:
        return FRESHNESS_INVALID_PROVENANCE
    if age > float(max_age_seconds):
        return FRESHNESS_STALE_AGE
    return FRESHNESS_FRESH


def _is_live_entry_event(event: Mapping[str, Any]) -> bool:
    etype = str(event.get("event_type") or event.get("type") or "").upper()
    if etype not in ENTRY_EVENT_TYPES:
        return False
    if is_restart_backfill_event(event) or is_recovery_delivery_event(event):
        return False
    delivery = str(event.get("delivery_mode") or "LIVE").upper()
    return delivery == "LIVE" or delivery == ""


def _explicit_execution_eligible_is_authoritative(event: Mapping[str, Any]) -> bool:
    """Legacy stamped eligibility is authoritative only on recovery/backfill paths.

    LIVE CONTEXT_START / CONTEXT_FLIP may carry stale materializer stamps
    (``execution_eligible=false``, ``freshness_status=STALE_AGE``) from before the
    closed-bar freshness-clock fix. Those stamps must not override a recomputed
    FRESH decision.
    """
    if is_restart_backfill_event(event) or is_recovery_delivery_event(event):
        return True
    if str(event.get("delivery_mode") or "").upper() == DELIVERY_MODE_RECOVERY:
        return True
    if not _is_live_entry_event(event):
        return True
    return False


def is_entry_execution_eligible(
    event: Mapping[str, Any],
    *,
    max_age_seconds: float,
    consumption_time: datetime | None = None,
) -> bool:
    status = evaluate_entry_freshness(
        event,
        max_age_seconds=max_age_seconds,
        consumption_time=consumption_time,
    )
    if status == FRESHNESS_FRESH and _is_live_entry_event(event):
        return True
    explicit = event.get("execution_eligible")
    if (
        explicit is not None
        and str(explicit).strip()
        and _explicit_execution_eligible_is_authoritative(event)
    ):
        return bool(explicit)
    return status == FRESHNESS_FRESH


def entry_freshness_block_reason(
    event: Mapping[str, Any],
    *,
    max_age_seconds: float,
    consumption_time: datetime | None = None,
) -> str | None:
    etype = str(event.get("event_type") or event.get("type") or "").upper()
    if etype not in ENTRY_EVENT_TYPES:
        return None
    if is_entry_execution_eligible(
        event,
        max_age_seconds=max_age_seconds,
        consumption_time=consumption_time,
    ):
        return None
    status = evaluate_entry_freshness(
        event,
        max_age_seconds=max_age_seconds,
        consumption_time=consumption_time,
    )
    if status == FRESHNESS_RESTART_BACKFILL or is_restart_backfill_event(event):
        return "ENTRY_BLOCKED_RESTART_BACKFILL"
    if status == FRESHNESS_RECOVERY or is_recovery_delivery_event(event):
        return "ENTRY_BLOCKED_REPLAY_SIGNAL"
    if status == FRESHNESS_INVALID_PROVENANCE:
        return "ENTRY_BLOCKED_INVALID_CONTEXT_PROVENANCE"
    if status == FRESHNESS_STALE_AGE:
        return "ENTRY_BLOCKED_STALE_CONTEXT_EVENT"
    age = compute_event_age_seconds(
        event,
        consumption_time=consumption_time,
        max_age_seconds=max_age_seconds,
    )
    if age is None:
        return "ENTRY_BLOCKED_INVALID_CONTEXT_PROVENANCE"
    if age > float(max_age_seconds):
        return "ENTRY_BLOCKED_STALE_CONTEXT_EVENT"
    return "ENTRY_BLOCKED_INVALID_CONTEXT_PROVENANCE"


def annotate_event_provenance(
    event: dict[str, Any],
    *,
    materialization_source: str,
    max_age_seconds: float,
    materialized_timestamp: str | None = None,
) -> dict[str, Any]:
    """Attach immutable provenance fields and execution eligibility to a context event."""
    mat_ts = _to_utc_ts(materialized_timestamp) or pd.Timestamp.now(tz="UTC")
    mat_iso = mat_ts.isoformat().replace("+00:00", "Z")
    origin = original_context_timestamp(event)
    origin_iso = _iso(origin) or _iso(_to_utc_ts(event.get("decision_available_at")))
    working = dict(event)
    working["materialized_timestamp"] = mat_iso
    working["materialization_source"] = str(materialization_source)
    ref_ts, ref_kind = resolve_freshness_reference(working, max_age_seconds=max_age_seconds)
    age = compute_event_age_seconds(
        working,
        reference_timestamp=mat_ts,
        max_age_seconds=max_age_seconds,
    )
    origin_age = compute_origin_age_seconds(working, materialized_timestamp=mat_ts)
    restart_backfill = is_restart_backfill_event(working)
    freshness_status = evaluate_entry_freshness(
        working,
        max_age_seconds=max_age_seconds,
        consumption_time=mat_ts.to_pydatetime(),
    )
    execution_eligible = freshness_status == FRESHNESS_FRESH
    return {
        "original_context_timestamp": origin_iso,
        "materialized_timestamp": mat_iso,
        "materialization_source": str(materialization_source),
        "restart_backfill": bool(restart_backfill),
        "event_age_seconds": age,
        "origin_age_seconds": origin_age,
        "context_origin_age_seconds": origin_age,
        "freshness_reference_timestamp": _iso(ref_ts),
        "freshness_reference_kind": ref_kind,
        "freshness_status": freshness_status,
        "execution_eligible": execution_eligible,
    }
