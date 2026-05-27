"""Shared helpers for Phase 1A replay validation."""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from calibration_diagnostics import (
    build_diagnostic_exports,
    dominant_component,
)
from parquet_utils import safe_read_parquet

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_probabilistic(path: Optional[str] = None) -> pd.DataFrame:
    file_path = path or os.path.join(
        ROOT,
        "probabilistic_auction_memory.parquet",
    )
    frame = safe_read_parquet(file_path)
    if len(frame) == 0:
        return frame
    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def load_reinforcement(path: Optional[str] = None) -> pd.DataFrame:
    file_path = path or os.path.join(
        ROOT,
        "auction_reinforcement_memory.parquet",
    )
    frame = safe_read_parquet(file_path)
    if len(frame) == 0:
        return frame
    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def load_cognition(path: Optional[str] = None) -> pd.DataFrame:
    file_path = path or os.path.join(
        ROOT,
        "runtime_cognition_memory.parquet",
    )
    return safe_read_parquet(file_path)


def rows_with_decomposition(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "alignment_component",
        "reinforcement_component",
        "entropy_penalty",
    ]
    available = [column for column in columns if column in frame.columns]
    if not available:
        return frame.iloc[0:0]
    return frame.dropna(subset=available, how="all")


def replay_diagnostics_for_index(
    probabilistic: pd.DataFrame,
    reinforcement: pd.DataFrame,
    index: int,
) -> dict:
    current = probabilistic.iloc[index].to_dict()
    history = probabilistic.iloc[:index]
    window = reinforcement.tail(25)

    return build_diagnostic_exports(
        probabilistic_history=history,
        reinforcement_history=reinforcement,
        reinforcement_window=window,
        runtime_cognition={},
        current_row=current,
    )
