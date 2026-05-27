"""HIGH_AVERAGE_VOLUME semantic integrity analysis."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from stabilization_data_utils import aggregate_event_metrics, filter_events, load_probabilistic

HAV_EXPORT_COLUMNS = [
    "hav_semantic_density",
    "hav_behavioral_dispersion",
    "hav_ontology_ambiguity_score",
    "hav_contradiction_concentration",
    "hav_entropy_neutrality",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def analyze_hav_semantics(
    climax_events: pd.DataFrame,
    dataset: pd.DataFrame,
    probabilistic: pd.DataFrame | None = None,
) -> Dict[str, Any]:
    from stabilization_data_utils import ensure_ontology_features

    dataset = ensure_ontology_features(dataset)
    hav = filter_events(climax_events, "HIGH_AVERAGE_VOLUME")
    probabilistic = probabilistic if probabilistic is not None else load_probabilistic()

    if len(hav) == 0:
        return neutral_hav_exports()

    decay = hav["efficiency_decay"].astype(float)
    range_position = hav["range_position"].astype(float)
    dispersion = float(decay.std() + range_position.std()) / 2.0 if len(hav) > 1 else 0.0

    grey_overlap = 0.0
    if len(dataset) > 0 and "efficiency_decay" in dataset.columns:
        full_decay = dataset["efficiency_decay"].astype(float)
        grey = ((full_decay >= 0.85) & (full_decay <= 1.20)).mean()
        hav_grey = ((decay >= 0.85) & (decay <= 1.20)).mean() if len(decay) else 0.0
        grey_overlap = float(hav_grey / (grey + 1e-9)) if grey > 0 else float(hav_grey)

    semantic_density = _clamp(len(hav) / max(len(climax_events), 1))
    contradiction = aggregate_event_metrics(probabilistic, "conflict_density")
    entropy_neutrality = 1.0 - abs(aggregate_event_metrics(hav, "efficiency_decay") - 1.0)
    ambiguity = _clamp(
        semantic_density * 0.30
        + dispersion * 0.25
        + grey_overlap * 0.25
        + contradiction * 0.20,
    )

    return {
        "hav_semantic_density": round(semantic_density, 4),
        "hav_behavioral_dispersion": round(_clamp(dispersion), 4),
        "hav_ontology_ambiguity_score": round(ambiguity, 4),
        "hav_contradiction_concentration": round(_clamp(contradiction), 4),
        "hav_entropy_neutrality": round(_clamp(entropy_neutrality), 4),
    }


def neutral_hav_exports() -> Dict[str, Any]:
    return {
        "hav_semantic_density": 0.0,
        "hav_behavioral_dispersion": 0.0,
        "hav_ontology_ambiguity_score": 0.0,
        "hav_contradiction_concentration": 0.0,
        "hav_entropy_neutrality": 1.0,
    }
