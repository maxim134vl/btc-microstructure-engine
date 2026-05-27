"""Shared data loaders for Phase 3B stabilization analysis."""

from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd

from auction_climax_engine_v1 import process_auction_climax
from parquet_utils import safe_read_parquet


def load_candle_structure(path: Optional[str] = None) -> pd.DataFrame:
    frame = safe_read_parquet(path or "candle_structure_memory.parquet")
    if len(frame) == 0:
        return frame
    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def load_probabilistic(path: Optional[str] = None) -> pd.DataFrame:
    frame = safe_read_parquet(path or "probabilistic_auction_memory.parquet")
    if len(frame) == 0:
        return frame
    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def load_reinforcement(path: Optional[str] = None) -> pd.DataFrame:
    frame = safe_read_parquet(path or "auction_reinforcement_memory.parquet")
    if len(frame) == 0:
        return frame
    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def load_cognition(path: Optional[str] = None) -> pd.DataFrame:
    frame = safe_read_parquet(path or "runtime_cognition_memory.parquet")
    if len(frame) == 0:
        return frame
    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def load_climax_events(timeframe: str = "M15") -> pd.DataFrame:
    dataset = load_candle_structure()
    if len(dataset) == 0:
        return pd.DataFrame()
    result = process_auction_climax(dataset=dataset, timeframe=timeframe)
    return result.get("auction_states", pd.DataFrame())


def filter_events(events: pd.DataFrame, event_type: str) -> pd.DataFrame:
    if len(events) == 0 or "auction_event_type" not in events.columns:
        return events.iloc[0:0]
    return events[events["auction_event_type"] == event_type].copy()


def aggregate_event_metrics(
    events: pd.DataFrame,
    column: str,
    default: float = 0.0,
) -> float:
    if len(events) == 0 or column not in events.columns:
        return default
    series = pd.to_numeric(events[column], errors="coerce").dropna()
    if len(series) == 0:
        return default
    return float(series.mean())


def ensure_ontology_features(dataset: pd.DataFrame) -> pd.DataFrame:
    import numpy as np

    frame = dataset.copy()
    if "efficiency_decay" not in frame.columns and {"spread", "volume"}.issubset(frame.columns):
        directional_efficiency = frame["spread"].astype(float) / frame["volume"].astype(float)
        efficiency_mean = directional_efficiency.rolling(20, min_periods=1).mean()
        frame["efficiency_decay"] = directional_efficiency / efficiency_mean.replace(0, np.nan)
    if "close_position_ratio" not in frame.columns and {"close", "high", "low"}.issubset(frame.columns):
        frame["close_position_ratio"] = (
            (frame["close"] - frame["low"]) / (frame["high"] - frame["low"]).replace(0, np.nan)
        )
    if "upper_wick_ratio" not in frame.columns and {"upper_wick", "spread"}.issubset(frame.columns):
        frame["upper_wick_ratio"] = frame["upper_wick"].astype(float) / frame["spread"].astype(float)
    if "lower_wick_ratio" not in frame.columns and {"lower_wick", "spread"}.issubset(frame.columns):
        frame["lower_wick_ratio"] = frame["lower_wick"].astype(float) / frame["spread"].astype(float)
    if "range_position" not in frame.columns and {"close", "high", "low"}.issubset(frame.columns):
        rolling_high = frame["high"].rolling(50, min_periods=1).max()
        rolling_low = frame["low"].rolling(50, min_periods=1).min()
        frame["range_position"] = (frame["close"] - rolling_low) / (rolling_high - rolling_low).replace(0, np.nan)
    return frame


def split_sell_side(events: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    stopping = filter_events(events, "STOPPING_VOLUME")
    selling = filter_events(events, "SELLING_CLIMAX")
    return stopping, selling
