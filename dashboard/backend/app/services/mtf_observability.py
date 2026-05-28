"""Read-only MTF aggregation for dashboard observability (mirrors runtime builder)."""

from __future__ import annotations

import numpy as np
import pandas as pd


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
