"""Replay environment audit — must run before ontology density conclusions."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from stabilization_data_utils import load_candle_structure, load_probabilistic, load_reinforcement

ARCHITECTURE_REFERENCE = (
    "Full Trading System Architecture Stage1 Stage2 Ru V1.docx "
    "(authoritative — attach to repo if not present locally)"
)

ONTOLOGY_EVENT_CLASSES = (
    "BUYING_CLIMAX",
    "SELLING_CLIMAX",
    "STOPPING_VOLUME",
    "HIGH_AVERAGE_VOLUME",
)


def _infer_bar_interval(timestamps: pd.Series) -> Optional[str]:
    if len(timestamps) < 2:
        return None
    delta = timestamps.sort_values().diff().dropna().median()
    if pd.isna(delta):
        return None
    minutes = delta.total_seconds() / 60.0
    if abs(minutes - 15) < 1:
        return "M15"
    if abs(minutes - 5) < 1:
        return "M5"
    if abs(minutes - 60) < 2:
        return "H1"
    return f"{minutes:.0f}m"


def _volatility_profile(frame: pd.DataFrame) -> Dict[str, float]:
    if len(frame) == 0 or "spread" not in frame.columns:
        return {}
    spread = frame["spread"].astype(float)
    volume = frame["volume"].astype(float) if "volume" in frame.columns else pd.Series(dtype=float)
    returns = frame["close"].astype(float).pct_change().dropna() if "close" in frame.columns else pd.Series(dtype=float)
    profile = {
        "spread_mean": float(spread.mean()),
        "spread_p50": float(spread.median()),
        "spread_p90": float(spread.quantile(0.90)),
        "spread_zscore_mean": float(frame["spread_zscore"].mean()) if "spread_zscore" in frame.columns else 0.0,
    }
    if len(volume):
        profile["volume_mean"] = float(volume.mean())
        profile["volume_p90"] = float(volume.quantile(0.90))
    if len(returns):
        profile["return_std"] = float(returns.std())
        profile["return_abs_mean"] = float(returns.abs().mean())
    return profile


def _regime_mix(probabilistic: pd.DataFrame) -> Dict[str, Any]:
    if len(probabilistic) == 0 or "regime_state" not in probabilistic.columns:
        return {"available": False, "distribution": {}}
    counts = probabilistic["regime_state"].value_counts(normalize=True).round(4)
    return {
        "available": True,
        "distribution": counts.to_dict(),
        "dominant_regime": counts.index[0] if len(counts) else None,
    }


def build_replay_environment_profile(
    timeframe: str = "M15",
    probabilistic_sample: int = 5000,
) -> Dict[str, Any]:
    """Profile the replay environment used by ontology/climax validation."""

    candles = load_candle_structure()
    probabilistic = load_probabilistic()
    reinforcement = load_reinforcement()

    profile: Dict[str, Any] = {
        "architecture_reference": ARCHITECTURE_REFERENCE,
        "replay_timeframe_metadata": timeframe,
        "datasets": {
            "candle_structure_memory.parquet": {
                "role": "Ontology/climax source of truth for replay",
                "rows": len(candles),
            },
            "probabilistic_auction_memory.parquet": {
                "role": "Runtime probabilistic export (NOT ontology denominator)",
                "rows": len(probabilistic),
            },
            "auction_reinforcement_memory.parquet": {
                "role": "Reinforcement context for replay suites",
                "rows": len(reinforcement),
            },
        },
    }

    if len(candles) == 0:
        profile["warning"] = "candle_structure empty — ontology replay invalid"
        return profile

    candles = candles.copy()
    candles["timestamp"] = pd.to_datetime(candles["timestamp"])
    candles = candles.sort_values("timestamp")

    inferred = _infer_bar_interval(candles["timestamp"])
    profile["inferred_bar_interval"] = inferred
    profile["replay_start"] = str(candles["timestamp"].min())
    profile["replay_end"] = str(candles["timestamp"].max())
    profile["replay_duration_hours"] = round(
        (candles["timestamp"].max() - candles["timestamp"].min()).total_seconds() / 3600,
        2,
    )
    profile["replay_duration_days"] = round(profile["replay_duration_hours"] / 24, 2)
    profile["candle_row_count"] = len(candles)

    profile["volatility_regime_mix"] = _volatility_profile(candles)

    if "range_position" in candles.columns:
        rp = candles["range_position"].astype(float)
        profile["trend_compression_distribution"] = {
            "low_range_lt_0.35": float((rp < 0.35).mean()),
            "mid_range_0.35_0.65": float(((rp >= 0.35) & (rp <= 0.65)).mean()),
            "high_range_gt_0.80": float((rp > 0.80).mean()),
        }

    prob_sample = probabilistic.tail(probabilistic_sample) if len(probabilistic) else probabilistic
    profile["probabilistic_regime_mix"] = _regime_mix(prob_sample)

    if len(probabilistic):
        probabilistic = probabilistic.copy()
        probabilistic["timestamp"] = pd.to_datetime(probabilistic["timestamp"])
        profile["probabilistic_timestamp_span"] = {
            "start": str(probabilistic["timestamp"].min()),
            "end": str(probabilistic["timestamp"].max()),
        }

    # Critical: detect invalid denominator comparisons
    if len(probabilistic) and len(candles):
        ratio = len(probabilistic) / max(len(candles), 1)
        profile["row_count_mismatch"] = {
            "probabilistic_to_candle_ratio": round(ratio, 2),
            "interpretation": (
                "probabilistic rows are runtime-loop exports; "
                "ontology events are per-candle classifications. "
                "Do NOT compare climax count to probabilistic row count."
            ),
            "is_misleading_denominator": ratio > 10,
        }

    profile["replay_environment_profile"] = True
    return profile


def export_replay_environment_profile(**kwargs) -> Dict[str, Any]:
    return build_replay_environment_profile(**kwargs)
