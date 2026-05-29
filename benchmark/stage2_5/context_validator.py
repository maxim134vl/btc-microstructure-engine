"""Forward market context metrics for Stage 2.5 validation horizons."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from parquet_utils import safe_read_parquet

VALIDATION_HORIZONS = (4, 8, 16)
BASELINE_BARS = 5


def load_candles() -> pd.DataFrame:
    frame = safe_read_parquet("candle_structure_memory.parquet")
    if len(frame) == 0:
        return frame
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    return frame.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


def find_event_index(candles: pd.DataFrame, ts: pd.Timestamp) -> int | None:
    matches = candles.index[candles["timestamp"] == ts].tolist()
    if matches:
        return int(matches[0])
    pos = int(candles["timestamp"].searchsorted(ts))
    if pos >= len(candles):
        return None
    return pos


def _slice_metrics(window: pd.DataFrame) -> dict[str, float]:
    if len(window) == 0:
        return {
            "continuation_quality": 0.0,
            "directional_efficiency": 0.0,
            "initiative_strength": 0.0,
            "initiative_dominance": 0.0,
            "sign_flips": 0.0,
            "directional_persistence": 0.0,
            "price_move": 0.0,
            "delta_sum": 0.0,
            "bars": 0.0,
        }

    deltas = window["delta"].astype(float)
    opens = window["open"].astype(float)
    closes = window["close"].astype(float)
    bar_dirs = np.sign(closes.values - opens.values)
    delta_dirs = np.sign(deltas.values)

    aligned = int(np.sum(bar_dirs == delta_dirs))
    continuation_quality = aligned / len(window)

    delta_sum = float(deltas.sum())
    price_move = float(closes.iloc[-1] - opens.iloc[0])
    abs_delta = float(np.abs(deltas).sum())
    directional_efficiency = abs(price_move) / max(abs_delta, 1.0)

    initiative_strength = float(np.abs(deltas).mean())
    initiative_dominance = abs(delta_sum) / max(abs_delta, 1.0)

    flips = 0
    for idx in range(1, len(delta_dirs)):
        if delta_dirs[idx] != 0 and delta_dirs[idx - 1] != 0 and delta_dirs[idx] != delta_dirs[idx - 1]:
            flips += 1
    sign_flips = flips / max(len(window) - 1, 1)

    streak = 1
    max_streak = 1
    for idx in range(1, len(delta_dirs)):
        if delta_dirs[idx] != 0 and delta_dirs[idx] == delta_dirs[idx - 1]:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 1
    directional_persistence = max_streak / len(window)

    return {
        "continuation_quality": round(continuation_quality, 4),
        "directional_efficiency": round(directional_efficiency, 4),
        "initiative_strength": round(initiative_strength, 2),
        "initiative_dominance": round(initiative_dominance, 4),
        "sign_flips": round(sign_flips, 4),
        "directional_persistence": round(directional_persistence, 4),
        "price_move": round(price_move, 2),
        "delta_sum": round(delta_sum, 2),
        "bars": float(len(window)),
    }


def build_event_context(candles: pd.DataFrame, event_idx: int, horizon: int) -> dict[str, Any]:
    """Baseline (pre-event) vs forward window metrics at a given horizon."""

    baseline_start = max(0, event_idx - BASELINE_BARS)
    baseline = candles.iloc[baseline_start:event_idx]
    forward_end = min(len(candles), event_idx + 1 + horizon)
    forward = candles.iloc[event_idx + 1 : forward_end]

    baseline_metrics = _slice_metrics(baseline)
    forward_metrics = _slice_metrics(forward)

    return {
        "horizon": horizon,
        "baseline": baseline_metrics,
        "forward": forward_metrics,
        "delta": {
            "continuation_quality": round(forward_metrics["continuation_quality"] - baseline_metrics["continuation_quality"], 4),
            "directional_efficiency": round(forward_metrics["directional_efficiency"] - baseline_metrics["directional_efficiency"], 4),
            "initiative_strength": round(forward_metrics["initiative_strength"] - baseline_metrics["initiative_strength"], 2),
            "initiative_dominance": round(forward_metrics["initiative_dominance"] - baseline_metrics["initiative_dominance"], 4),
            "sign_flips": round(forward_metrics["sign_flips"] - baseline_metrics["sign_flips"], 4),
            "directional_persistence": round(
                forward_metrics["directional_persistence"] - baseline_metrics["directional_persistence"], 4
            ),
        },
        "forward_candles": int(forward_metrics["bars"]),
    }


def build_multi_horizon_context(candles: pd.DataFrame, event_idx: int) -> dict[int, dict[str, Any]]:
    return {horizon: build_event_context(candles, event_idx, horizon) for horizon in VALIDATION_HORIZONS}
