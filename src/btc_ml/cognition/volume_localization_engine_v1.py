"""Canonical estimated_local_volume producer — Phase 4A live-wiring candidate.

Proven algorithm from git 8fbde36 (config/volume_localization.py constants unchanged).
Writes volume_localization_memory under data/cognition via atomic parquet replace.

Not activated until pipeline registration + process restart (see pipeline candidate helper).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from parquet_utils import atomic_parquet_write, safe_read_parquet

# Frozen constants from config/volume_localization.py @ git 8fbde36 — do not retune.
EPS = 1e-6
WICK_REJECTION_RATIO = 0.40
WICK_DOMINANCE_SPREAD = 0.35
CLOSE_LOWER = 0.40
CLOSE_UPPER = 0.60
RATIO_BODY = 0.5
RATIO_WICK = 0.7
ZONE_LOWER_WICK_LOW = 0.25
ZONE_LOWER_WICK_HIGH = 0.45
ZONE_UPPER_WICK_LOW = 0.55
ZONE_UPPER_WICK_HIGH = 0.80
MAX_RETENTION_ROWS = 5000

ENGINE_NAME = "volume_localization_engine_v1.py"
SOURCE_PARQUET = "candle_structure_memory.parquet"
OUTPUT_PARQUET = "volume_localization_memory.parquet"
ALGORITHM_VERSION = "volume_localization_v1@8fbde36"
SOURCE_TIMEFRAME = "M15"
BAR_SECONDS = 15 * 60

_REPO = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_PATH = _REPO / "data" / "cognition" / "candle_structure_memory.parquet"
DEFAULT_OUTPUT_PATH = _REPO / "data" / "cognition" / "volume_localization_memory.parquet"


def derive_rejection_flags(row: pd.Series) -> tuple[bool, bool]:
    spread = float(row["spread"])
    if spread <= 0:
        return False, False
    upper_wick = float(row["upper_wick"])
    lower_wick = float(row["lower_wick"])
    close_position = float(row["close_position"])
    uwr = upper_wick / (spread + EPS)
    lwr = lower_wick / (spread + EPS)
    lower_rej = lwr > WICK_REJECTION_RATIO and close_position > CLOSE_LOWER
    upper_rej = uwr > WICK_REJECTION_RATIO and close_position < CLOSE_UPPER
    return lower_rej, upper_rej


def localize_bar(row: pd.Series) -> dict[str, Any]:
    lower_rej, upper_rej = derive_rejection_flags(row)
    spread = float(row["spread"])
    low = float(row["low"])
    high = float(row["high"])
    open_price = float(row["open"])
    close_price = float(row["close"])
    volume = float(row["volume"])
    lower_wick = float(row["lower_wick"])
    upper_wick = float(row["upper_wick"])

    if lower_rej and lower_wick > spread * WICK_DOMINANCE_SPREAD:
        ratio = RATIO_WICK
        behavior = "localized_absorption"
        zone_low = low + lower_wick * ZONE_LOWER_WICK_LOW
        zone_high = low + lower_wick * ZONE_LOWER_WICK_HIGH
    elif upper_rej and upper_wick > spread * WICK_DOMINANCE_SPREAD:
        ratio = RATIO_WICK
        behavior = "localized_distribution"
        zone_low = high - upper_wick * (1.0 - ZONE_UPPER_WICK_LOW)
        zone_high = high - upper_wick * (1.0 - ZONE_UPPER_WICK_HIGH)
    else:
        ratio = RATIO_BODY
        behavior = "body_participation"
        zone_low = min(open_price, close_price)
        zone_high = max(open_price, close_price)

    elv = volume * ratio
    return {
        "timestamp": row["timestamp"],
        "estimated_local_volume": elv,
        "total_volume": volume,
        "localized_volume_ratio": ratio,
        "volume_concentration": elv / (volume + EPS),
        "behavior": behavior,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "zone_width": zone_high - zone_low,
        "lower_rejection": bool(lower_rej),
        "upper_rejection": bool(upper_rej),
    }


def resolve_localization_for_structure(
    localization: pd.DataFrame,
    structure_timestamp,
    *,
    live_v1: bool = True,
) -> dict[str, Any]:
    """Exact timestamp join helper for volume_response (fail-closed)."""
    out: dict[str, Any] = {
        "localization_join_status": "NO_LOCALIZATION_MATCH",
        "localization_source_timestamp": None,
        "localization_fresh": False,
        "row": None,
    }
    if localization is None or len(localization) == 0 or "timestamp" not in localization.columns:
        return out
    loc = localization.copy()
    loc["timestamp"] = pd.to_datetime(loc["timestamp"], utc=True, errors="coerce")
    target = pd.Timestamp(structure_timestamp)
    if target.tzinfo is None:
        target = target.tz_localize("UTC")
    else:
        target = target.tz_convert("UTC")
    matches = loc[loc["timestamp"] == target]
    if len(matches) == 0:
        tip = loc["timestamp"].dropna().max() if loc["timestamp"].notna().any() else None
        if live_v1 and tip is not None and tip < target:
            out["localization_join_status"] = "STALE_LOCALIZATION_MATCH"
            out["localization_source_timestamp"] = tip
        return out
    if len(matches) > 1:
        out["localization_join_status"] = "AMBIGUOUS_LOCALIZATION_MATCH"
        out["localization_source_timestamp"] = target
        return out
    row = matches.iloc[0]
    out["localization_join_status"] = "EXACT_FRESH_MATCH"
    out["localization_source_timestamp"] = target
    out["localization_fresh"] = True
    out["row"] = row
    return out


def _required_fields_present(row: pd.Series) -> bool:
    required = (
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "spread",
        "upper_wick",
        "lower_wick",
        "close_position",
    )
    return all(field in row.index and pd.notna(row[field]) for field in required)


def build_localization_frame(
    structure: pd.DataFrame,
    *,
    limit: int | None = None,
) -> pd.DataFrame:
    """Vector of completed-structure rows → localization rows (no live write)."""
    if structure is None or len(structure) == 0:
        return pd.DataFrame()
    frame = structure.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    if limit is not None and limit > 0:
        frame = frame.iloc[-int(limit) :]
    rows: list[dict[str, Any]] = []
    created = datetime.now(timezone.utc)
    tip = frame["timestamp"].iloc[-1] if len(frame) else None
    for _, row in frame.iterrows():
        if not _required_fields_present(row):
            continue
        payload = localize_bar(row)
        ts = pd.Timestamp(payload["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        payload["timestamp"] = ts
        payload["source_timeframe"] = SOURCE_TIMEFRAME
        payload["source_candle_close"] = ts + pd.Timedelta(seconds=BAR_SECONDS)
        payload["algorithm_version"] = ALGORITHM_VERSION
        payload["input_tip"] = tip
        payload["created_at"] = created
        # Compatible aliases for consumers that expect alternate names.
        payload["localized_behavior"] = payload["behavior"]
        payload["zone_lower"] = payload["zone_low"]
        payload["zone_upper"] = payload["zone_high"]
        rows.append(payload)
    out = pd.DataFrame(rows)
    if len(out):
        out = out.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
        out = out.reset_index(drop=True)
    return out


def _resolve_source_path() -> Path:
    try:
        from storage.path_registry import resolve_read

        return Path(resolve_read(SOURCE_PARQUET))
    except Exception:
        return DEFAULT_SOURCE_PATH


def _resolve_output_path() -> Path:
    # Intended production artifact (orphan already lives here).
    return DEFAULT_OUTPUT_PATH


def run(*, write: bool = True) -> int:
    print()
    print("VOLUME LOCALIZATION ENGINE V1")
    print()

    source_path = _resolve_source_path()
    if not source_path.exists():
        # Fallback through parquet_utils registry-aware reader
        structure = safe_read_parquet(SOURCE_PARQUET)
    else:
        structure = pd.read_parquet(source_path)

    if structure is None or len(structure) == 0:
        print("MISSING:", SOURCE_PARQUET)
        return 1

    structure = structure.copy()
    structure["timestamp"] = pd.to_datetime(structure["timestamp"], utc=True, errors="coerce")
    structure = structure.dropna(subset=["timestamp"]).sort_values("timestamp")
    latest = structure.iloc[-1]
    if not _required_fields_present(latest):
        print("INVALID INPUT: NaN in required candle_structure fields")
        return 1

    output_path = _resolve_output_path()
    memory = (
        pd.read_parquet(output_path)
        if output_path.exists()
        else pd.DataFrame()
    )
    if len(memory):
        memory["timestamp"] = pd.to_datetime(memory["timestamp"], utc=True, errors="coerce")
        latest_memory_ts = pd.Timestamp(memory["timestamp"].iloc[-1])
        bar_timestamp = pd.Timestamp(latest["timestamp"])
        if latest_memory_ts == bar_timestamp:
            print("NO NEW BAR — skip append")
            return 0

    # Append only the latest completed bar (legacy live contract).
    new_frame = build_localization_frame(structure.iloc[[-1]])
    if not len(new_frame):
        print("NO LOCALIZATION ROW PRODUCED")
        return 1

    if len(memory):
        combined = pd.concat([memory, new_frame], ignore_index=True)
        combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        if len(combined) > MAX_RETENTION_ROWS:
            combined = combined.iloc[-MAX_RETENTION_ROWS:].reset_index(drop=True)
    else:
        combined = new_frame

    if write:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_parquet_write(
            combined,
            str(output_path),
            validate=True,
            timestamp_col="timestamp",
            enforce_timestamp_integrity=True,
        )
        print("LOCALIZED BEHAVIOR:", new_frame.iloc[0]["behavior"])
        print(
            "ESTIMATED LOCAL VOLUME:",
            round(float(new_frame.iloc[0]["estimated_local_volume"]), 4),
        )
        print()
        print("MEMORY SAVED:", output_path)
        print()
    return 0


if __name__ == "__main__":
    import os
    import sys

    exit_code = run(write=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
