"""Shared helpers for Phase 3A ontology replay validation."""

from __future__ import annotations

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from auction_climax_engine_v1 import process_auction_climax  # noqa: E402
from parquet_utils import safe_read_parquet  # noqa: E402


def load_candle_structure(path: str | None = None) -> pd.DataFrame:
    file_path = path or "candle_structure_memory.parquet"
    frame = safe_read_parquet(file_path)
    if len(frame) == 0:
        return frame
    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def run_climax(timeframe: str = "M15") -> pd.DataFrame:
    dataset = load_candle_structure()
    if len(dataset) == 0:
        return pd.DataFrame()
    result = process_auction_climax(dataset=dataset, timeframe=timeframe)
    return result["auction_states"]


def filter_events(frame: pd.DataFrame, event_type: str) -> pd.DataFrame:
    if len(frame) == 0 or "auction_event_type" not in frame.columns:
        return frame.iloc[0:0]
    return frame[frame["auction_event_type"] == event_type].copy()


__all__ = ["ROOT", "load_candle_structure", "run_climax", "filter_events"]
