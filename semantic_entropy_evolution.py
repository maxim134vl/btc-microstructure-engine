"""Semantic entropy evolution divergence — STOPPING vs SELLING."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from stabilization_data_utils import aggregate_event_metrics, split_sell_side

ENTROPY_EVOLUTION_EXPORT_COLUMNS = [
    "entropy_decay_rate",
    "entropy_compression_duration",
    "post_event_entropy_persistence",
    "entropy_recovery_velocity",
    "entropy_divergence_score",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def analyze_entropy_evolution_divergence(
    climax_events: pd.DataFrame,
) -> Dict[str, Any]:
    stopping, selling = split_sell_side(climax_events)

    stopping_decay = aggregate_event_metrics(stopping, "post_climax_entropy_shift")
    selling_decay = aggregate_event_metrics(selling, "post_climax_entropy_shift")
    stopping_stabilization = aggregate_event_metrics(stopping, "stabilization_duration")
    selling_stabilization = aggregate_event_metrics(selling, "stabilization_duration")
    stopping_persistence = aggregate_event_metrics(stopping, "absorption_persistence_score")
    selling_persistence = aggregate_event_metrics(selling, "absorption_persistence_score")
    stopping_recovery = aggregate_event_metrics(stopping, "inventory_transfer_quality")
    selling_recovery = aggregate_event_metrics(selling, "inventory_transfer_quality")

    decay_rate = stopping_decay - selling_decay
    compression_duration = stopping_stabilization - selling_stabilization
    persistence = stopping_persistence - selling_persistence
    recovery_velocity = stopping_recovery - selling_recovery

    divergence = _clamp(
        abs(decay_rate) * 0.30
        + max(0.0, compression_duration) * 0.10
        + abs(persistence) * 0.30
        + abs(recovery_velocity) * 0.30,
    )

    return {
        "entropy_decay_rate": round(decay_rate, 4),
        "entropy_compression_duration": round(compression_duration, 4),
        "post_event_entropy_persistence": round(persistence, 4),
        "entropy_recovery_velocity": round(recovery_velocity, 4),
        "entropy_divergence_score": round(divergence, 4),
    }


def neutral_entropy_evolution_exports() -> Dict[str, Any]:
    return {
        "entropy_decay_rate": 0.0,
        "entropy_compression_duration": 0.0,
        "post_event_entropy_persistence": 0.0,
        "entropy_recovery_velocity": 0.0,
        "entropy_divergence_score": 0.0,
    }
