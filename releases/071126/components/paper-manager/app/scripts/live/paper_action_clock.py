#!/usr/bin/env python3
"""Paper action clock: separate source bucket time from action/detection time."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import pandas as pd

CLOCK_FALLBACK_TO_SOURCE_CONTEXT_TS = "CLOCK_FALLBACK_TO_SOURCE_CONTEXT_TS"
CLOCK_FALLBACK_TO_CONTROLLER_CYCLE_TS = "CLOCK_FALLBACK_TO_CONTROLLER_CYCLE_TS"
CLOCK_FALLBACK_TO_M15_CLOSE = "CLOCK_FALLBACK_TO_M15_CLOSE"
DECISION_LOG_CLOSE_ONLY = "DECISION_LOG_CLOSE_ONLY"
INTRABAR_DATA_MISSING = "INTRABAR_DATA_MISSING"
VISUAL_WAS_USING_SOURCE_CONTEXT_TS = "VISUAL_WAS_USING_SOURCE_CONTEXT_TS"
ACTION_USED_DETECTED_AT = "ACTION_USED_DETECTED_AT"
ACTION_USED_DECISION_AVAILABLE_AT = "ACTION_USED_DECISION_AVAILABLE_AT"
ACTION_USED_INTRABAR_EVENT_DETECTED_AT = "ACTION_USED_INTRABAR_EVENT_DETECTED_AT"
INTRABAR_EVENT_PROVISIONAL = "INTRABAR_EVENT_PROVISIONAL"
NO_INTRABAR_EVENT_FOR_CONTEXT = "NO_INTRABAR_EVENT_FOR_CONTEXT"
EXIT_CLOCK_INTRABAR_FEED_UNHEALTHY_FALLBACK = "EXIT_CLOCK_INTRABAR_FEED_UNHEALTHY_FALLBACK"

M15_SECONDS = 900


def _to_ts(value: Any) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def iso_ts(value: Any, *, with_micros: bool = False) -> Optional[str]:
    ts = _to_ts(value)
    if ts is None:
        return None
    if with_micros:
        return ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    # Preserve sub-second when present.
    if ts.microsecond:
        return ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def m15_bar_open_ts(value: Any) -> Optional[str]:
    ts = _to_ts(value)
    if ts is None:
        return None
    floored = ts.floor("15min")
    return iso_ts(floored)


def m15_bar_close_ts(value: Any) -> Optional[str]:
    ts = _to_ts(value)
    if ts is None:
        return None
    floored = ts.floor("15min") + pd.Timedelta(seconds=M15_SECONDS)
    return iso_ts(floored)


def is_m15_close_ts(value: Any) -> bool:
    ts = _to_ts(value)
    if ts is None:
        return False
    # Exact M15 boundary that is a close (minute%15==0) and not also open of same bar
    # Treat as close label when equal to open+15m of previous open.
    open_ts = ts.floor("15min")
    return bool(ts == open_ts) and False  # unused; prefer equals_m15_bar_close


def equals_m15_bar_close(action_ts: Any, source_or_any: Any) -> bool:
    close = m15_bar_close_ts(source_or_any)
    action = iso_ts(_to_ts(action_ts))
    return bool(close and action and close == action)


def extract_source_context_ts(row: Mapping[str, Any] | None) -> Optional[str]:
    if not isinstance(row, Mapping):
        return None
    for key in ("source_context_ts", "candle_timestamp", "active_context_started_at", "timestamp"):
        val = row.get(key)
        if val is not None and str(val).strip():
            out = iso_ts(val)
            if out:
                return out
    return None


def extract_decision_available_at(row: Mapping[str, Any] | None) -> Optional[str]:
    if not isinstance(row, Mapping):
        return None
    for key in (
        "decision_available_at",
        "decision_written_at_utc",
        "signal_fields_generated_at_utc",
        "decision_written_at",
    ):
        val = row.get(key)
        if val is not None and str(val).strip():
            out = iso_ts(val, with_micros=True)
            if out:
                return out
    return None


def extract_context_event_detected_at(row: Mapping[str, Any] | None) -> Optional[str]:
    if not isinstance(row, Mapping):
        return None
    for key in (
        "context_event_detected_at",
        "event_detected_at",
        "detected_at",
        "evidence_last_update_ts",
    ):
        val = row.get(key)
        if val is not None and str(val).strip():
            out = iso_ts(val, with_micros=True)
            if out:
                return out
    return None


def resolve_paper_action_ts(
    *,
    context_event_detected_at: Any = None,
    decision_available_at: Any = None,
    controller_cycle_at: Any = None,
    source_context_ts: Any = None,
    m15_bar_close: Any = None,
    allow_m15_close_fallback: bool = False,
    intrabar_event_detected_at: Any = None,
    intrabar_event_id: Any = None,
    intrabar_event_provisional: bool | None = None,
) -> dict[str, Any]:
    """Prefer intrabar/detection time for paper entry/exit; never prefer M15 close silently.

    Priority:
      1. intrabar_context_events.event_detected_at
      2. context_event_detected_at (generic)
      3. decision_available_at
      4. controller_cycle_at (warning)
      5. source_context_ts (warning)
    """
    warnings: list[str] = []
    intrabar_detected = iso_ts(intrabar_event_detected_at, with_micros=True)
    detected = iso_ts(context_event_detected_at, with_micros=True)
    decision_at = iso_ts(decision_available_at, with_micros=True)
    cycle_at = iso_ts(controller_cycle_at, with_micros=True)
    source = iso_ts(source_context_ts)
    close = iso_ts(m15_bar_close) or (m15_bar_close_ts(source_context_ts) if source_context_ts is not None else None)

    paper_action_ts: Optional[str] = None
    clock_source_used: Optional[str] = None

    if intrabar_detected:
        paper_action_ts = intrabar_detected
        clock_source_used = "intrabar_event_detected_at"
        warnings.append(ACTION_USED_INTRABAR_EVENT_DETECTED_AT)
        if intrabar_event_provisional:
            warnings.append(INTRABAR_EVENT_PROVISIONAL)
    elif detected:
        paper_action_ts = detected
        clock_source_used = "context_event_detected_at"
        warnings.append(ACTION_USED_DETECTED_AT)
    elif decision_at:
        paper_action_ts = decision_at
        clock_source_used = "decision_available_at"
        warnings.append(ACTION_USED_DECISION_AVAILABLE_AT)
        if close and _to_ts(decision_at) is not None and _to_ts(close) is not None:
            if _to_ts(decision_at) >= _to_ts(close):
                warnings.append(DECISION_LOG_CLOSE_ONLY)
    elif cycle_at:
        paper_action_ts = cycle_at
        clock_source_used = "controller_cycle_at"
        warnings.append(CLOCK_FALLBACK_TO_CONTROLLER_CYCLE_TS)
    elif allow_m15_close_fallback and close:
        paper_action_ts = close
        clock_source_used = "m15_bar_close_ts"
        warnings.append(CLOCK_FALLBACK_TO_M15_CLOSE)
    elif source:
        paper_action_ts = source
        clock_source_used = "source_context_ts"
        warnings.append(CLOCK_FALLBACK_TO_SOURCE_CONTEXT_TS)
        warnings.append(NO_INTRABAR_EVENT_FOR_CONTEXT)
    else:
        warnings.append(INTRABAR_DATA_MISSING)
        warnings.append(NO_INTRABAR_EVENT_FOR_CONTEXT)

    action_used_source = bool(clock_source_used == "source_context_ts")
    action_used_m15_close = bool(clock_source_used == "m15_bar_close_ts")
    action_used_detected = bool(clock_source_used in {"context_event_detected_at", "intrabar_event_detected_at"})

    return {
        "source_context_ts": source,
        "m15_bar_open_ts": m15_bar_open_ts(source_context_ts or detected or decision_at or intrabar_detected),
        "m15_bar_close_ts": close,
        "context_event_detected_at": detected or intrabar_detected,
        "intrabar_event_detected_at": intrabar_detected,
        "intrabar_event_id": str(intrabar_event_id) if intrabar_event_id else None,
        "intrabar_event_provisional": bool(intrabar_event_provisional) if intrabar_event_provisional is not None else None,
        "decision_available_at": decision_at,
        "controller_cycle_at": cycle_at,
        "paper_action_ts": paper_action_ts,
        "clock_source_used": clock_source_used,
        "action_clock_source": clock_source_used,
        "action_used_source_context_ts": action_used_source,
        "action_used_m15_close": action_used_m15_close,
        "action_used_detected_at": action_used_detected,
        "warnings": warnings,
        "clock_warning": warnings[0] if warnings else None,
    }


def lookup_intrabar_event_for_source(
    events: pd.DataFrame | None,
    *,
    source_context_ts: Any,
    event_types: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """Find matching intrabar context event for a source M15 bucket timestamp."""
    if events is None or getattr(events, "empty", True):
        return None
    source = iso_ts(source_context_ts)
    if not source or "source_context_ts" not in events.columns:
        return None
    key = source[:16]
    match = events[events["source_context_ts"].astype(str).str.startswith(key)].copy()
    if event_types and "event_type" in match.columns:
        match = match[match["event_type"].astype(str).isin(list(event_types))]
    if match.empty:
        return None
    row = match.iloc[-1].to_dict()
    return row


def feed_cadence_seconds(feed: pd.DataFrame, ts_col: str = "timestamp") -> dict[str, Any]:
    if feed is None or feed.empty or ts_col not in feed.columns:
        return {
            "intrabar_data_available": False,
            "live_feed_cadence_seconds": None,
            "minute_rows_total": 0,
            "m15_aligned_rows": 0,
        }
    ts = pd.to_datetime(feed[ts_col], utc=True, errors="coerce").dropna().sort_values()
    if ts.empty:
        return {
            "intrabar_data_available": False,
            "live_feed_cadence_seconds": None,
            "minute_rows_total": 0,
            "m15_aligned_rows": 0,
        }
    delta = ts.diff().dt.total_seconds().dropna()
    median = float(delta.median()) if len(delta) else None
    minutes = ts.dt.minute
    m15_aligned = int((minutes % 15 == 0).sum())
    # Intrabar = rows that are not on 15m boundaries, or cadence < 900s.
    non_m15 = int((minutes % 15 != 0).sum())
    intrabar = bool(non_m15 > 0 or (median is not None and median < 800))
    return {
        "intrabar_data_available": intrabar,
        "live_feed_cadence_seconds": median,
        "minute_rows_total": int(len(ts)),
        "m15_aligned_rows": m15_aligned,
        "non_m15_rows": non_m15,
    }


def minute_rows_inside_m15_bucket(feed: pd.DataFrame, bucket_open: Any, ts_col: str = "timestamp") -> int:
    open_ts = _to_ts(bucket_open)
    if open_ts is None or feed is None or feed.empty or ts_col not in feed.columns:
        return 0
    close_ts = open_ts + pd.Timedelta(seconds=M15_SECONDS)
    ts = pd.to_datetime(feed[ts_col], utc=True, errors="coerce")
    mask = (ts >= open_ts) & (ts < close_ts)
    return int(mask.sum())


def decision_logger_is_close_only(decision_log: pd.DataFrame) -> bool:
    if decision_log is None or decision_log.empty:
        return True
    if "source_timeframe" in decision_log.columns:
        tf = decision_log["source_timeframe"].astype(str).str.lower()
        if len(tf) and (tf == "15m").all():
            # Further: written_at at/after candle_close when available.
            if "decision_written_at_utc" in decision_log.columns and "candle_close_time_utc" in decision_log.columns:
                written = pd.to_datetime(decision_log["decision_written_at_utc"], utc=True, errors="coerce")
                close = pd.to_datetime(decision_log["candle_close_time_utc"], utc=True, errors="coerce")
                valid = written.notna() & close.notna()
                if valid.any() and (written[valid] >= close[valid]).mean() >= 0.8:
                    return True
            return True
    return False


__all__ = [
    "ACTION_USED_DECISION_AVAILABLE_AT",
    "ACTION_USED_DETECTED_AT",
    "ACTION_USED_INTRABAR_EVENT_DETECTED_AT",
    "CLOCK_FALLBACK_TO_CONTROLLER_CYCLE_TS",
    "CLOCK_FALLBACK_TO_M15_CLOSE",
    "CLOCK_FALLBACK_TO_SOURCE_CONTEXT_TS",
    "DECISION_LOG_CLOSE_ONLY",
    "INTRABAR_DATA_MISSING",
    "INTRABAR_EVENT_PROVISIONAL",
    "M15_SECONDS",
    "NO_INTRABAR_EVENT_FOR_CONTEXT",
    "VISUAL_WAS_USING_SOURCE_CONTEXT_TS",
    "decision_logger_is_close_only",
    "extract_context_event_detected_at",
    "extract_decision_available_at",
    "extract_source_context_ts",
    "feed_cadence_seconds",
    "iso_ts",
    "lookup_intrabar_event_for_source",
    "m15_bar_close_ts",
    "m15_bar_open_ts",
    "minute_rows_inside_m15_bucket",
    "resolve_paper_action_ts",
]
