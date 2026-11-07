"""Read-only MTF aggregation and health semantics for dashboard observability."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

MTF_HEALTH_CURRENT = "CURRENT"
MTF_HEALTH_SPARSE_OK = "SPARSE_OK"
MTF_HEALTH_PRODUCER_STALE = "PRODUCER_STALE"
MTF_HEALTH_PRODUCER_FAILED = "PRODUCER_FAILED"
MTF_HEALTH_INPUT_STALE = "INPUT_STALE"
MTF_HEALTH_OUTPUT_NOT_REFRESHING = "OUTPUT_NOT_REFRESHING"

DEFAULT_MTF_HEALTH_STALE_SECONDS = 30 * 60


def aggregate_behavioral_timeframe(dataset: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    timeframe_map = {
        "M30": "30min",
        "H1": "1h",
        "H4": "4h",
        "D1": "1D",
    }

    frame = dataset.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.set_index("timestamp")

    aggregated = frame.resample(timeframe_map[timeframe]).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "delta": "sum",
        }
    )
    aggregated = aggregated.dropna().reset_index()

    aggregated["spread"] = aggregated["high"] - aggregated["low"]
    aggregated["body"] = (aggregated["close"] - aggregated["open"]).abs()
    aggregated["upper_wick"] = aggregated["high"] - aggregated[["open", "close"]].max(axis=1)
    aggregated["lower_wick"] = aggregated[["open", "close"]].min(axis=1) - aggregated["low"]
    aggregated["candle_type"] = np.where(
        aggregated["close"] >= aggregated["open"],
        "bullish",
        "bearish",
    )
    return aggregated


def _to_utc_epoch(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        ts = pd.to_datetime(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if getattr(ts, "tzinfo", None) is not None and ts.tzinfo is not None:
        return float(ts.tz_convert("UTC").timestamp())

    as_utc = float(ts.tz_localize("UTC").timestamp())
    now = time.time()
    # Runtime/file mtimes can arrive as local-naive wall clock. If interpreting
    # them as UTC puts them in the future, reinterpret using local timezone.
    if as_utc - now > 30:
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        return float(ts.tz_localize(local_tz).tz_convert("UTC").timestamp())
    return as_utc


def _iso_utc(value: Any) -> str | None:
    epoch = _to_utc_epoch(value)
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _lag_seconds(reference: Any, observed: Any) -> float | None:
    reference_epoch = _to_utc_epoch(reference)
    observed_epoch = _to_utc_epoch(observed)
    if reference_epoch is None or observed_epoch is None:
        return None
    return round(max(0.0, reference_epoch - observed_epoch), 3)


def _age_seconds(observed: Any, *, now: float) -> float | None:
    observed_epoch = _to_utc_epoch(observed)
    if observed_epoch is None:
        return None
    return round(max(0.0, now - observed_epoch), 3)


def classify_mtf_health(
    *,
    latest_event_timestamp: Any,
    latest_input_candle_timestamp: Any,
    producer_heartbeat_timestamp: Any,
    producer_last_status: Any,
    output_mtime: Any,
    source_reference_timestamp: Any = None,
    lineage_propagation_timestamp: Any = None,
    now: float | None = None,
    stale_after_seconds: float = DEFAULT_MTF_HEALTH_STALE_SECONDS,
) -> dict[str, Any]:
    """Classify sparse MTF outputs without treating old event time as failure."""

    now_epoch = time.time() if now is None else float(now)
    reference = source_reference_timestamp or latest_input_candle_timestamp
    status = str(producer_last_status or "UNKNOWN").upper()

    event_lag = _lag_seconds(latest_input_candle_timestamp, latest_event_timestamp)
    input_lag = _lag_seconds(reference, latest_input_candle_timestamp)
    heartbeat_lag = _age_seconds(producer_heartbeat_timestamp, now=now_epoch)
    output_lag = _age_seconds(output_mtime, now=now_epoch)

    failed_statuses = {"FAILED", "TIMEOUT", "ERROR"}
    classification = MTF_HEALTH_CURRENT
    warning = None

    if status in failed_statuses:
        classification = MTF_HEALTH_PRODUCER_FAILED
        warning = f"MTF producer last status is {status}"
    elif heartbeat_lag is None or heartbeat_lag > stale_after_seconds:
        classification = MTF_HEALTH_PRODUCER_STALE
        warning = "MTF producer heartbeat is stale or missing"
    elif input_lag is None or input_lag > stale_after_seconds:
        classification = MTF_HEALTH_INPUT_STALE
        warning = "MTF input candle is stale relative to live source"
    elif output_lag is None or output_lag > stale_after_seconds:
        classification = MTF_HEALTH_OUTPUT_NOT_REFRESHING
        warning = "MTF output parquet mtime is stale while producer/input are fresh"
    elif event_lag is None or event_lag > stale_after_seconds:
        classification = MTF_HEALTH_SPARSE_OK
        warning = "NO_NEW_MTF_EVENT: sparse MTF output is healthy but no newer event was produced"

    return {
        "latest_event_timestamp": _iso_utc(latest_event_timestamp),
        "latest_input_candle_timestamp": _iso_utc(latest_input_candle_timestamp),
        "producer_heartbeat_timestamp": _iso_utc(producer_heartbeat_timestamp),
        "producer_last_status": status,
        "output_mtime": _iso_utc(output_mtime),
        "lineage_propagation_timestamp": _iso_utc(lineage_propagation_timestamp),
        "source_reference_timestamp": _iso_utc(reference),
        "event_lag_seconds": event_lag,
        "heartbeat_lag_seconds": heartbeat_lag,
        "input_lag_seconds": input_lag,
        "source_lag_seconds": input_lag,
        "output_mtime_lag_seconds": output_lag,
        "health_classification": classification,
        "freshness_warning": warning,
    }
