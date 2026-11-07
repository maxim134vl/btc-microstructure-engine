"""Ontology drift detection — warning-only, no auto-correction."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from ontology_config import get_ontology_settings
from ontology_refinement import detect_overlap_violations

DRIFT_EXPORT_COLUMNS = [
    "ontology_drift_score",
    "ontology_stability_score",
    "semantic_fragility_score",
    "grey_zone_expansion_rate",
    "reinforcement_asymmetry_creep",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def detect_ontology_drift(
    climax_events: pd.DataFrame,
    dataset: pd.DataFrame,
    reinforcement_exports: Dict[str, Any],
    contradiction_exports: Dict[str, Any],
    overlap_score: float,
) -> Dict[str, Any]:
    settings = get_ontology_settings()

    grey_zone_rate = 0.0
    if len(dataset) > 0 and "efficiency_decay" in dataset.columns:
        decay = dataset["efficiency_decay"].astype(float)
        grey = (decay >= settings.grey_zone_low) & (decay <= settings.grey_zone_high)
        grey_zone_rate = float(grey.mean())

    overlap_violations = []
    required_overlap_columns = {
        "volume_percentile_50",
        "spread_percentile_50",
        "delta",
        "efficiency_decay",
        "range_position",
    }
    if required_overlap_columns.issubset(dataset.columns):
        overlap_violations = detect_overlap_violations(dataset)
    collapse_recurrence = _clamp(len(overlap_violations) / max(len(dataset), 1) * 10.0)

    reinforcement_creep = _clamp(
        abs(float(reinforcement_exports.get("reinforcement_behavior_shift", 0.0)))
        + float(reinforcement_exports.get("ontology_reinforcement_divergence", 0.0)) * 0.5,
    )
    contradiction_inflation = _clamp(
        float(contradiction_exports.get("contradiction_redistribution_score", 0.0)),
    )

    drift_score = _clamp(
        collapse_recurrence * 0.25
        + grey_zone_rate * 0.20
        + reinforcement_creep * 0.20
        + contradiction_inflation * 0.20
        + overlap_score * 0.15,
    )
    stability_score = _clamp(1.0 - drift_score)
    fragility = _clamp(
        drift_score * 0.55
        + (1.0 - float(reinforcement_exports.get("reinforcement_stability_score", 1.0))) * 0.25
        + (1.0 - float(contradiction_exports.get("contradiction_resolution_quality", 1.0))) * 0.20,
    )

    return {
        "ontology_drift_score": round(drift_score, 4),
        "ontology_stability_score": round(stability_score, 4),
        "semantic_fragility_score": round(fragility, 4),
        "grey_zone_expansion_rate": round(grey_zone_rate, 4),
        "reinforcement_asymmetry_creep": round(reinforcement_creep, 4),
    }


def neutral_drift_exports() -> Dict[str, Any]:
    return {
        "ontology_drift_score": 0.0,
        "ontology_stability_score": 1.0,
        "semantic_fragility_score": 0.0,
        "grey_zone_expansion_rate": 0.0,
        "reinforcement_asymmetry_creep": 0.0,
    }
