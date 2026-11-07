"""BUYING_CLIMAX exhaustion validation — observability only, no ontology rewrite."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from stabilization_data_utils import aggregate_event_metrics, ensure_ontology_features, filter_events

BUYING_EXPORT_COLUMNS = [
    "buying_exhaustion_quality",
    "upside_continuation_fragility",
    "breakout_failure_persistence",
    "upside_rejection_persistence",
    "upper_wick_asymmetry",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _ensure_ontology_features(dataset: pd.DataFrame) -> pd.DataFrame:
    return ensure_ontology_features(dataset)


def _compute_buying_post_metrics(
    dataset: pd.DataFrame,
    event_index: int,
    horizon: int = 5,
) -> Dict[str, float]:
    dataset = _ensure_ontology_features(dataset)
    future = dataset.iloc[event_index + 1 : event_index + 1 + horizon]
    if len(future) == 0:
        return {
            "continuation_failure": 0.0,
            "entropy_expansion": 0.0,
            "rejection_persistence": 0.0,
        }

    event_row = dataset.iloc[event_index]
    positive_delta_fail = (future["delta"].astype(float) <= 0).mean()
    event_decay = float(event_row.get("efficiency_decay", 0.0) or 0.0)
    if "efficiency_decay" in future.columns:
        decay_shift = future["efficiency_decay"].astype(float).mean() - event_decay
    else:
        decay_shift = 0.0
    upper_wick = float(event_row.get("upper_wick_ratio", 0.0))
    close_position = float(event_row.get("close_position_ratio", 0.5))

    return {
        "continuation_failure": float(positive_delta_fail),
        "entropy_expansion": _clamp(decay_shift, -1.0, 1.0),
        "rejection_persistence": _clamp(upper_wick * 0.55 + (1.0 - close_position) * 0.45),
    }


def analyze_buying_exhaustion(
    climax_events: pd.DataFrame,
    dataset: pd.DataFrame,
    horizon: int = 5,
) -> Dict[str, Any]:
    dataset = _ensure_ontology_features(dataset)
    buying = filter_events(climax_events, "BUYING_CLIMAX")
    if len(buying) == 0 or len(dataset) == 0:
        return neutral_buying_exports()

    metrics = []
    for _, event in buying.iterrows():
        if "timestamp" not in dataset.columns or "timestamp" not in event.index:
            continue
        matches = dataset.index[dataset["timestamp"] == event["timestamp"]]
        if len(matches) == 0:
            continue
        position = dataset.index.get_loc(matches[0])
        if isinstance(position, slice):
            continue
        metrics.append(_compute_buying_post_metrics(dataset, int(position), horizon=horizon))

    if not metrics:
        upper_wick = aggregate_event_metrics(buying, "upper_wick_ratio")
        return {
            "buying_exhaustion_quality": round(_clamp(upper_wick), 4),
            "upside_continuation_fragility": 0.0,
            "breakout_failure_persistence": 0.0,
            "upside_rejection_persistence": round(_clamp(upper_wick), 4),
            "upper_wick_asymmetry": round(_clamp(upper_wick), 4),
        }

    continuation_failure = float(np.mean([item["continuation_failure"] for item in metrics]))
    entropy_expansion = float(np.mean([item["entropy_expansion"] for item in metrics]))
    rejection_persistence = float(np.mean([item["rejection_persistence"] for item in metrics]))
    upper_wick = aggregate_event_metrics(buying, "upper_wick_ratio")

    exhaustion_quality = _clamp(
        continuation_failure * 0.35
        + max(0.0, entropy_expansion) * 0.25
        + rejection_persistence * 0.25
        + upper_wick * 0.15,
    )
    fragility = _clamp(
        continuation_failure * 0.40 + max(0.0, entropy_expansion) * 0.30 + upper_wick * 0.30,
    )

    return {
        "buying_exhaustion_quality": round(exhaustion_quality, 4),
        "upside_continuation_fragility": round(fragility, 4),
        "breakout_failure_persistence": round(continuation_failure, 4),
        "upside_rejection_persistence": round(rejection_persistence, 4),
        "upper_wick_asymmetry": round(_clamp(upper_wick), 4),
    }


def neutral_buying_exports() -> Dict[str, Any]:
    return {
        "buying_exhaustion_quality": 0.0,
        "upside_continuation_fragility": 0.0,
        "breakout_failure_persistence": 0.0,
        "upside_rejection_persistence": 0.0,
        "upper_wick_asymmetry": 0.0,
    }
