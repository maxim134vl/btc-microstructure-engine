"""Assemble cognition memory layers for visual replay."""

from __future__ import annotations

from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet


def _load(name: str) -> pd.DataFrame:
    frame = safe_read_parquet(name)
    if len(frame) == 0:
        return frame
    if "timestamp" in frame.columns:
        frame = frame.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.dropna(subset=["timestamp"])
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def _merge_asof(base: pd.DataFrame, other: pd.DataFrame, suffix: str) -> pd.DataFrame:
    if len(base) == 0 or len(other) == 0:
        return base
    left = base.sort_values("timestamp")
    right = other.sort_values("timestamp")
    overlap = set(left.columns) & set(right.columns) - {"timestamp"}
    if overlap:
        right = right.rename(columns={column: f"{column}{suffix}" for column in overlap})
    return pd.merge_asof(left, right, on="timestamp", direction="backward")


def build_cognition_frame(*, lookback_days: int = 7) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    """Load and merge Stage 1 cognition memory onto M15 candle base."""

    candles = _load("candle_structure_memory.parquet")
    if len(candles) == 0:
        return pd.DataFrame(), pd.DataFrame(), {}

    cutoff = candles["timestamp"].max() - pd.Timedelta(days=lookback_days)
    candles = candles[candles["timestamp"] >= cutoff].copy()

    cognition = candles[["timestamp", "open", "high", "low", "close", "volume", "delta"]].copy()

    for name, columns in {
        "volume_classification_memory.parquet": ["timestamp", "volume_class"],
        "volume_response_state.parquet": [
            "timestamp",
            "volume_event",
            "climax_state",
            "participation_state",
            "effort_result_state",
            "localized_behavior",
            "continuation_quality",
            "unfinished_auction",
        ],
        "runtime_cognition_memory.parquet": [
            "timestamp",
            "synthesis_state",
            "trigger_event",
            "persistence_score",
            "structural_rank",
            "alignment_score",
        ],
        "intermediate_cognition_memory.parquet": [
            "timestamp",
            "intermediate_state",
            "confidence",
            "severity",
            "anchor_stage2_state",
            "anchor_timestamp",
            "reason",
        ],
        "probabilistic_auction_memory.parquet": ["timestamp", "auction_regime", "conviction_probability"],
    }.items():
        layer = _load(name)
        if len(layer) == 0:
            continue
        layer = layer[layer["timestamp"] >= cutoff]
        present = [column for column in columns if column in layer.columns]
        cognition = _merge_asof(cognition, layer[present], f"_{name[:4]}")

    transitions = _load("state_transition_memory.parquet")
    if len(transitions) > 0:
        transitions = transitions[transitions["timestamp"] >= cutoff]
        transition_cols = [column for column in ("timestamp", "transition_state", "previous_state", "current_state") if column in transitions.columns]
        cognition = _merge_asof(cognition, transitions[transition_cols], "_tr")

    from visual_cognition.mtf_auction_map import build_mtf_frames

    mtf_frames = build_mtf_frames(candles)
    return cognition, candles, mtf_frames
