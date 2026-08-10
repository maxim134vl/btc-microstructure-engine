"""Entry-signal freshness checks for LIVE1B context consumption."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

ENTRY_EVENT_TYPES = frozenset({"CONTEXT_START", "CONTEXT_FLIP"})
DELIVERY_MODE_RECOVERY = "RECOVERY"


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
    from btc_ml.live.intrabar.context_event_freshness import causal_decision_timestamp

    return causal_decision_timestamp(event)


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
    if bool(event.get("recovered_after_restart")):
        return True
    if str(event.get("materialization_class") or "").upper() == "DURABLE_CONTEXT_RECOVERY":
        return True
    return False


def is_recovery_delivery_event(event: dict[str, Any]) -> bool:
    """True when materialization marked the event as recovery/catch-up delivery."""
    if str(event.get("delivery_mode") or "").upper() == DELIVERY_MODE_RECOVERY:
        return True
    return is_restart_backfill_event(event)


def is_replay_entry_blocked(event: dict[str, Any]) -> bool:
    etype = str(event.get("event_type") or event.get("type") or "").upper()
    if etype not in ENTRY_EVENT_TYPES:
        return False
    return is_recovery_delivery_event(event)


def replay_entry_block_reason(event: dict[str, Any]) -> str | None:
    if not is_replay_entry_blocked(event):
        return None
    return "ENTRY_BLOCKED_REPLAY_SIGNAL"


def is_stale_entry_signal(
    event: dict[str, Any],
    *,
    max_age_seconds: float,
    consumption_time: datetime | None = None,
) -> bool:
    """True when an entry leg must be blocked due to signal age."""
    from btc_ml.live.intrabar.context_event_freshness import is_entry_execution_eligible

    etype = str(event.get("event_type") or event.get("type") or "").upper()
    if etype not in ENTRY_EVENT_TYPES:
        return False
    return not is_entry_execution_eligible(
        event,
        max_age_seconds=max_age_seconds,
        consumption_time=consumption_time,
    )


def stale_entry_block_reason(
    event: dict[str, Any],
    *,
    max_age_seconds: float,
    consumption_time: datetime | None = None,
) -> str | None:
    from btc_ml.live.intrabar.context_event_freshness import entry_freshness_block_reason

    freshness_reason = entry_freshness_block_reason(
        event,
        max_age_seconds=max_age_seconds,
        consumption_time=consumption_time,
    )
    if freshness_reason:
        return freshness_reason
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
