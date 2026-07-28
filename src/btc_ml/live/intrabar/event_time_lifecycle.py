"""Event-time lifecycle wrapper around canonical step_lifecycle."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from build_market_context_lifecycle_memory import (  # noqa: E402
    MIN_ACTIVE_CONTEXT_HOLD_BARS,
    step_lifecycle,
)

from .partial_bar_state import TF_SECONDS


def age_bars_from_elapsed(elapsed_seconds: float, timeframe: str) -> int:
    """Map elapsed event time to bar-age equivalents without changing N."""
    bar_seconds = float(TF_SECONDS[timeframe])
    if elapsed_seconds < 0:
        return 0
    return int(elapsed_seconds // bar_seconds)


def step_event_time_lifecycle(
    *,
    timeframe: str,
    provisional_context: Mapping[str, Any],
    timestamp: Any,
    prev: Optional[dict[str, Any]],
    active_started_at: Any = None,
) -> dict[str, Any]:
    """Call canonical step_lifecycle with age expressed as floor(elapsed/TF)."""
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    prev_adapted = None if prev is None else dict(prev)
    if prev_adapted is not None and active_started_at is not None:
        started = pd.Timestamp(active_started_at)
        if started.tzinfo is None:
            started = started.tz_localize("UTC")
        else:
            started = started.tz_convert("UTC")
        elapsed = (ts - started).total_seconds()
        prev_adapted["active_context_age_bars"] = age_bars_from_elapsed(elapsed, timeframe)
        prev_adapted["active_context_started_at"] = started

    out = step_lifecycle(
        raw_market_context=str(provisional_context.get("market_context") or "OBSERVE"),
        raw_context_status=str(provisional_context.get("context_status") or "UNKNOWN"),
        raw_context_reason=str(provisional_context.get("context_reason") or "UNKNOWN"),
        raw_cognitive_market_state=str(provisional_context.get("cognitive_market_state") or "UNKNOWN"),
        raw_state_direction=str(provisional_context.get("state_direction") or "UNKNOWN"),
        auction_episode=str(provisional_context.get("auction_episode") or "UNKNOWN"),
        timestamp=ts,
        prev=prev_adapted,
    )
    out["_timeframe"] = timeframe
    out["_min_hold_bars"] = MIN_ACTIVE_CONTEXT_HOLD_BARS
    out["_min_hold_seconds"] = MIN_ACTIVE_CONTEXT_HOLD_BARS * TF_SECONDS[timeframe]
    out["evaluation_mode"] = "PROVISIONAL_INTRABAR"
    return out


def detect_context_transition(
    prev_lifecycle: Optional[Mapping[str, Any]],
    new_lifecycle: Mapping[str, Any],
) -> Optional[dict[str, str]]:
    """Return CONTEXT_START/END/FLIP descriptor or None."""
    prev_active = (prev_lifecycle or {}).get("active_market_context") or "OBSERVE"
    new_active = new_lifecycle.get("active_market_context") or "OBSERVE"
    directional = {"LONG_CONTEXT", "SHORT_CONTEXT"}
    if prev_active == new_active:
        return None
    if prev_active not in directional and new_active in directional:
        return {
            "event_type": "CONTEXT_START",
            "previous_context": str(prev_active),
            "new_context": str(new_active),
        }
    if prev_active in directional and new_active not in directional:
        return {
            "event_type": "CONTEXT_END",
            "previous_context": str(prev_active),
            "new_context": str(new_active),
        }
    if prev_active in directional and new_active in directional and prev_active != new_active:
        return {
            "event_type": "CONTEXT_FLIP",
            "previous_context": str(prev_active),
            "new_context": str(new_active),
        }
    return None
