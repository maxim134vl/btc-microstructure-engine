"""Canonical candle identity helpers for volume_response (Phase 4B).

Contract (additive — does not rewrite historical wall-clock `timestamp`):

  source_candle_timestamp = candle_structure.timestamp  (M15 bar open, passthrough)
  source_candle_close     = source_candle_timestamp + 15 minutes
  evaluated_at            = wall-clock calculation time
  timestamp               = legacy wall-clock field (unchanged meaning)

Join key when BTC_ML_VOLUME_LOCALIZATION_LIVE=1:

  volume_response.source_candle_timestamp == volume_localization.timestamp
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

BAR_SECONDS = 15 * 60
SOURCE_TIMEFRAME = "M15"

STATUS_EXACT = "EXACT_FRESH_MATCH"
STATUS_NO_MATCH = "NO_LOCALIZATION_MATCH"
STATUS_AMBIGUOUS = "AMBIGUOUS_LOCALIZATION_MATCH"
STATUS_STALE = "STALE_LOCALIZATION_MATCH"
STATUS_LEGACY_NO_SOURCE = "LEGACY_RESPONSE_NO_SOURCE_TIMESTAMP"


def _as_utc(ts) -> pd.Timestamp:
    out = pd.Timestamp(ts)
    if out.tzinfo is None:
        return out.tz_localize("UTC")
    return out.tz_convert("UTC")


def canonical_source_candle_timestamp(structure_row: pd.Series | dict[str, Any]) -> pd.Timestamp:
    """Passthrough M15 bar-open from candle_structure row. Never derived from wall-clock."""
    if isinstance(structure_row, dict):
        if "timestamp" not in structure_row:
            raise KeyError("structure row missing timestamp")
        return _as_utc(structure_row["timestamp"])
    if "timestamp" not in structure_row.index:
        raise KeyError("structure row missing timestamp")
    return _as_utc(structure_row["timestamp"])


def source_candle_close_from_open(source_candle_timestamp) -> pd.Timestamp:
    return _as_utc(source_candle_timestamp) + pd.Timedelta(seconds=BAR_SECONDS)


def wall_clock_evaluated_at(now: datetime | pd.Timestamp | None = None) -> pd.Timestamp:
    if now is None:
        return pd.Timestamp(datetime.now(timezone.utc))
    return _as_utc(now)


def build_response_identity_fields(
    structure_row: pd.Series | dict[str, Any],
    *,
    evaluated_at: datetime | pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Identity payload for a newly computed volume_response row."""
    source_ts = canonical_source_candle_timestamp(structure_row)
    evaluated = wall_clock_evaluated_at(evaluated_at)
    return {
        "source_candle_timestamp": source_ts,
        "source_candle_close": source_candle_close_from_open(source_ts),
        "source_timeframe": SOURCE_TIMEFRAME,
        "evaluated_at": evaluated,
        # Legacy field meaning preserved: wall-clock evaluation time.
        "timestamp": evaluated,
    }


def response_has_canonical_source_timestamp(response_row: pd.Series | dict[str, Any]) -> bool:
    if isinstance(response_row, dict):
        val = response_row.get("source_candle_timestamp")
    else:
        if "source_candle_timestamp" not in response_row.index:
            return False
        val = response_row["source_candle_timestamp"]
    if val is None:
        return False
    try:
        return bool(pd.notna(val))
    except Exception:
        return False


def _resolve_localization():
    """Load resolve_localization_for_structure without executing volume_response script."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent / "volume_localization_engine_v1.py"
    spec = importlib.util.spec_from_file_location(
        "btc_ml_cognition_volume_localization_engine_v1_ts",
        path,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.resolve_localization_for_structure


def classify_response_localization_join(
    response_row: pd.Series | dict[str, Any],
    localization: pd.DataFrame,
    *,
    live_v1: bool = True,
) -> dict[str, Any]:
    """Join localization using response.source_candle_timestamp (fail-closed)."""
    if not response_has_canonical_source_timestamp(response_row):
        return {
            "localization_join_status": STATUS_LEGACY_NO_SOURCE,
            "localization_source_timestamp": None,
            "localization_fresh": False,
            "row": None,
            "source_candle_timestamp": None,
        }

    if isinstance(response_row, dict):
        source_ts = response_row["source_candle_timestamp"]
    else:
        source_ts = response_row["source_candle_timestamp"]

    resolve_localization_for_structure = _resolve_localization()
    join = resolve_localization_for_structure(
        localization,
        source_ts,
        live_v1=live_v1,
    )
    join["source_candle_timestamp"] = _as_utc(source_ts)
    return join
