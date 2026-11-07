"""Ontology overlap matrix — identify remaining compression zones."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import pandas as pd

OVERLAP_EXPORT_COLUMNS = [
    "ontology_overlap_matrix",
    "semantic_overlap_score",
    "ontology_ambiguity_heatmap",
]

OVERLAP_PAIRS: List[Tuple[str, str]] = [
    ("BUYING_CLIMAX", "HIGH_AVERAGE_VOLUME"),
    ("HIGH_AVERAGE_VOLUME", "BALANCED_AUCTION"),
    ("STOPPING_VOLUME", "ABSORPTION_RECOVERY"),
    ("TREND_EXHAUSTION", "BUYING_CLIMAX"),
]

FEATURE_COLUMNS = [
    "efficiency_decay",
    "close_position_ratio",
    "lower_wick_ratio",
    "upper_wick_ratio",
    "range_position",
    "volume_percentile_50",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _feature_overlap(
    left: pd.DataFrame,
    right: pd.DataFrame,
) -> float:
    if len(left) == 0 or len(right) == 0:
        return 0.0

    overlaps = []
    for column in FEATURE_COLUMNS:
        if column not in left.columns or column not in right.columns:
            continue
        left_mean = float(left[column].astype(float).mean())
        right_mean = float(right[column].astype(float).mean())
        span = max(abs(left_mean), abs(right_mean), 0.05)
        overlaps.append(1.0 - _clamp(abs(left_mean - right_mean) / span))

    if not overlaps:
        return 0.0
    return float(sum(overlaps) / len(overlaps))


def _resolve_group(
    climax_events: pd.DataFrame,
    dataset: pd.DataFrame,
    probabilistic: pd.DataFrame,
    label: str,
) -> pd.DataFrame:
    if label in {"BALANCED_AUCTION", "ABSORPTION_RECOVERY", "TREND_EXHAUSTION"}:
        if len(probabilistic) == 0 or "regime_state" not in probabilistic.columns:
            return pd.DataFrame()
        timestamps = probabilistic.loc[
            probabilistic["regime_state"] == label,
            "timestamp",
        ]
        if len(timestamps) == 0 or len(dataset) == 0:
            return pd.DataFrame()
        return dataset[dataset["timestamp"].isin(timestamps)].copy()

    if len(climax_events) == 0:
        return pd.DataFrame()
    return climax_events[climax_events["auction_event_type"] == label].copy()


def build_overlap_matrix(
    climax_events: pd.DataFrame,
    dataset: pd.DataFrame,
    probabilistic: pd.DataFrame | None = None,
) -> Dict[str, Any]:
    probabilistic = probabilistic if probabilistic is not None else pd.DataFrame()

    matrix: Dict[str, float] = {}
    heatmap: Dict[str, float] = {}

    for left_label, right_label in OVERLAP_PAIRS:
        left = _resolve_group(climax_events, dataset, probabilistic, left_label)
        right = _resolve_group(climax_events, dataset, probabilistic, right_label)
        overlap = _feature_overlap(left, right)
        key = f"{left_label}|{right_label}"
        matrix[key] = round(overlap, 4)
        heatmap[left_label] = round(
            max(heatmap.get(left_label, 0.0), overlap),
            4,
        )
        heatmap[right_label] = round(
            max(heatmap.get(right_label, 0.0), overlap),
            4,
        )

    semantic_overlap = _clamp(
        sum(matrix.values()) / max(len(matrix), 1),
    )

    return {
        "ontology_overlap_matrix": json.dumps(matrix),
        "semantic_overlap_score": round(semantic_overlap, 4),
        "ontology_ambiguity_heatmap": json.dumps(heatmap),
    }


def neutral_overlap_exports() -> Dict[str, Any]:
    return {
        "ontology_overlap_matrix": json.dumps({}),
        "semantic_overlap_score": 0.0,
        "ontology_ambiguity_heatmap": json.dumps({}),
    }
