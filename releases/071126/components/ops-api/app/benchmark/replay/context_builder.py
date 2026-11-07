"""Reconstruct market context at event time for replay."""

from __future__ import annotations

from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet


def build_event_context(timestamp: str, window: int = 10) -> dict[str, Any]:
    candles = safe_read_parquet("candle_structure_memory.parquet")
    if len(candles) == 0:
        return {"timestamp": timestamp, "window": []}

    candles = candles.copy()
    candles["timestamp"] = pd.to_datetime(candles["timestamp"])
    candles = candles.sort_values("timestamp").reset_index(drop=True)
    ts = pd.to_datetime(timestamp)
    idx = candles.index[candles["timestamp"] == ts]
    if len(idx) == 0:
        return {"timestamp": timestamp, "window": []}

    center = int(idx[0])
    slice_df = candles.iloc[max(0, center - window) : center + window + 1]
    return {
        "timestamp": timestamp,
        "center_index": center,
        "window": slice_df.to_dict(orient="records"),
    }
