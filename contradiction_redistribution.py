"""Contradiction redistribution analysis after ontology separation."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from stabilization_data_utils import (
    aggregate_event_metrics,
    filter_events,
    load_probabilistic,
    split_sell_side,
)

CONTRADICTION_EXPORT_COLUMNS = [
    "contradiction_redistribution_score",
    "ontology_conflict_shift",
    "contradiction_resolution_quality",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def analyze_contradiction_redistribution(
    climax_events: pd.DataFrame,
    probabilistic: pd.DataFrame | None = None,
) -> Dict[str, Any]:
    probabilistic = probabilistic if probabilistic is not None else load_probabilistic()
    stopping, selling = split_sell_side(climax_events)

    stopping_conflict = aggregate_event_metrics(stopping, "conflict_density")
    selling_conflict = aggregate_event_metrics(selling, "conflict_density")
    runtime_conflict = aggregate_event_metrics(probabilistic, "conflict_density")
    unresolved = aggregate_event_metrics(
        probabilistic,
        "unresolved_contradiction_score",
    )
    escalation = aggregate_event_metrics(
        probabilistic,
        "contradiction_escalation_score",
    )

    conflict_shift = stopping_conflict - selling_conflict
    redistribution = _clamp(abs(conflict_shift) + escalation * 0.35)
    resolution_quality = _clamp(
        1.0
        - redistribution * 0.40
        - unresolved * 0.35
        - max(0.0, runtime_conflict - 0.35) * 0.25,
    )

    return {
        "contradiction_redistribution_score": round(redistribution, 4),
        "ontology_conflict_shift": round(conflict_shift, 4),
        "contradiction_resolution_quality": round(resolution_quality, 4),
    }


def neutral_contradiction_exports() -> Dict[str, Any]:
    return {
        "contradiction_redistribution_score": 0.0,
        "ontology_conflict_shift": 0.0,
        "contradiction_resolution_quality": 1.0,
    }
