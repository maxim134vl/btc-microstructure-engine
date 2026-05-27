"""Post-separation reinforcement redistribution analysis — observability only."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from stabilization_data_utils import (
    aggregate_event_metrics,
    load_probabilistic,
    load_reinforcement,
    split_sell_side,
)

REINFORCEMENT_EXPORT_COLUMNS = [
    "reinforcement_behavior_shift",
    "ontology_reinforcement_divergence",
    "reinforcement_stability_score",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def analyze_reinforcement_redistribution(
    climax_events: pd.DataFrame,
    probabilistic: pd.DataFrame | None = None,
    reinforcement: pd.DataFrame | None = None,
) -> Dict[str, Any]:
    probabilistic = probabilistic if probabilistic is not None else load_probabilistic()
    reinforcement = reinforcement if reinforcement is not None else load_reinforcement()

    stopping, selling = split_sell_side(climax_events)

    stopping_reinforcement = aggregate_event_metrics(
        stopping,
        "reinforcement_component",
        default=aggregate_event_metrics(probabilistic, "reinforcement_component"),
    )
    selling_reinforcement = aggregate_event_metrics(
        selling,
        "reinforcement_component",
        default=aggregate_event_metrics(probabilistic, "reinforcement_component"),
    )

    runtime_reinforcement = aggregate_event_metrics(
        probabilistic,
        "reinforcement_component",
    )
    runtime_tail_reinforcement = aggregate_event_metrics(
        probabilistic.tail(25),
        "reinforcement_component",
        default=runtime_reinforcement,
    )

    behavior_shift = stopping_reinforcement - selling_reinforcement
    divergence = abs(behavior_shift) / (max(stopping_reinforcement, selling_reinforcement, 0.05))

    concentration = 0.0
    if len(reinforcement) > 0 and "reinforcement_component" in reinforcement.columns:
        tail = reinforcement["reinforcement_component"].tail(25).astype(float)
        concentration = float(tail.max() / (tail.mean() + 1e-9)) if len(tail) else 0.0

    drift = abs(runtime_tail_reinforcement - runtime_reinforcement)
    stability = _clamp(1.0 - divergence * 0.35 - drift * 0.25 - max(0.0, concentration - 1.5) * 0.15)

    return {
        "reinforcement_behavior_shift": round(behavior_shift, 4),
        "ontology_reinforcement_divergence": round(_clamp(divergence), 4),
        "reinforcement_stability_score": round(stability, 4),
    }


def neutral_reinforcement_exports() -> Dict[str, Any]:
    return {
        "reinforcement_behavior_shift": 0.0,
        "ontology_reinforcement_divergence": 0.0,
        "reinforcement_stability_score": 1.0,
    }
