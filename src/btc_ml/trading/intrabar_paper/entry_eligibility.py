"""Entry-signal freshness checks for LIVE1B context consumption."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

ENTRY_EVENT_TYPES = frozenset({"CONTEXT_START", "CONTEXT_FLIP"})


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


def decision_timestamp(event: dict[str, Any]) -> pd.Timestamp | None:
    """Causal availability timestamp for entry-age checks."""
    if is_restart_backfill_event(event):
        return _to_utc_ts(event.get("decision_available_at"))
    decision_ts = _to_utc_ts(event.get("decision_available_at"))
    if decision_ts is not None:
        return decision_ts
    return _to_utc_ts(event.get("event_timestamp")) or _to_utc_ts(event.get("timestamp"))


def entry_signal_age_seconds(
    event: dict[str, Any],
    *,
    consumption_time: datetime | None = None,
) -> float | None:
    decision_ts = decision_timestamp(event)
    if decision_ts is None:
        return None
    now = consumption_time or datetime.now(timezone.utc)
    consumption_ts = pd.Timestamp(now).tz_convert("UTC")
    return float((consumption_ts - decision_ts).total_seconds())


def is_restart_backfill_event(event: dict[str, Any]) -> bool:
    if bool(event.get("restart_backfill")):
        return True
    if str(event.get("materialization_class") or "").upper() == "RESTART_BACKFILL":
        return True
    if bool(event.get("revalidated_after_restart")):
        return True
    return False


def is_stale_entry_signal(
    event: dict[str, Any],
    *,
    max_age_seconds: float,
    consumption_time: datetime | None = None,
) -> bool:
    """True when an entry leg must be blocked due to signal age."""
    etype = str(event.get("event_type") or event.get("type") or "").upper()
    if etype not in ENTRY_EVENT_TYPES:
        return False
    age = entry_signal_age_seconds(event, consumption_time=consumption_time)
    if age is None:
        return True
    if age > float(max_age_seconds):
        return True
    if is_restart_backfill_event(event) and age > 0:
        return True
    return False


def stale_entry_block_reason(
    event: dict[str, Any],
    *,
    max_age_seconds: float,
    consumption_time: datetime | None = None,
) -> str | None:
    if not is_stale_entry_signal(
        event,
        max_age_seconds=max_age_seconds,
        consumption_time=consumption_time,
    ):
        return None
    if is_restart_backfill_event(event) and decision_timestamp(event) is None:
        return "ENTRY_BLOCKED_STALE_SIGNAL_NO_DECISION_TIME"
    if is_restart_backfill_event(event):
        return "ENTRY_BLOCKED_RESTART_BACKFILL"
    if entry_signal_age_seconds(event, consumption_time=consumption_time) is None:
        return "ENTRY_BLOCKED_STALE_SIGNAL_NO_DECISION_TIME"
    return "ENTRY_BLOCKED_STALE_SIGNAL"
