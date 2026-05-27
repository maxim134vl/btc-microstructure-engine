"""Full ontology topology audit — Phase 4A freeze candidate analysis."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pandas as pd

from ontology_overlap_matrix import build_overlap_matrix
from stabilization_data_utils import (
    ensure_ontology_features,
    load_candle_structure,
    load_climax_events,
    load_probabilistic,
    load_reinforcement,
    split_sell_side,
)

TOPOLOGY_EXPORT_COLUMNS = [
    "ontology_topology_map",
    "ontology_compression_zones",
    "semantic_stability_index",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _event_counts(events: pd.DataFrame) -> Dict[str, int]:
    if len(events) == 0 or "auction_event_type" not in events.columns:
        return {}
    return events["auction_event_type"].value_counts().to_dict()


def _grey_zone_rate(dataset: pd.DataFrame) -> float:
    if len(dataset) == 0 or "efficiency_decay" not in dataset.columns:
        return 0.0
    decay = dataset["efficiency_decay"].astype(float)
    return float(((decay >= 0.85) & (decay <= 1.20)).mean())


def _identify_compression_zones(
    events: pd.DataFrame,
    overlap: Dict[str, Any],
    probabilistic: pd.DataFrame,
) -> List[str]:
    zones: List[str] = []

    counts = _event_counts(events)
    hav_count = counts.get("HIGH_AVERAGE_VOLUME", 0)
    buying_count = counts.get("BUYING_CLIMAX", 0)
    total = max(sum(counts.values()), 1)

    if hav_count / total > 0.35:
        zones.append("HIGH_AVERAGE_VOLUME_OVERFLOW")
    if float(overlap.get("semantic_overlap_score", 0.0)) > 0.35:
        zones.append("CROSS_CLASS_FEATURE_OVERLAP")
    if _grey_zone_rate(load_candle_structure()) > 0.25:
        zones.append("EFFORT_RESULT_GREY_ZONE_EXPANSION")

    if len(probabilistic) > 0 and "regime_state" in probabilistic.columns:
        regime_counts = probabilistic["regime_state"].value_counts(normalize=True)
        if float(regime_counts.get("TREND_EXHAUSTION", 0.0)) > 0.40:
            zones.append("TREND_EXHAUSTION_CONCENTRATION")

    stopping, selling = split_sell_side(events)
    if len(stopping) == 0 and len(selling) == 0 and total > 0:
        zones.append("SELL_SIDE_EVENT_SPARSITY")
    if buying_count == 0 and hav_count > 0:
        zones.append("UPSIDE_SEMANTIC_AMBIGUITY")

    return zones


def build_ontology_topology_audit(
    climax_events: pd.DataFrame | None = None,
    dataset: pd.DataFrame | None = None,
    probabilistic: pd.DataFrame | None = None,
    reinforcement: pd.DataFrame | None = None,
) -> Dict[str, Any]:
    climax_events = climax_events if climax_events is not None else load_climax_events()
    dataset = ensure_ontology_features(
        dataset if dataset is not None else load_candle_structure()
    )
    probabilistic = probabilistic if probabilistic is not None else load_probabilistic()
    reinforcement = reinforcement if reinforcement is not None else load_reinforcement()

    overlap = build_overlap_matrix(climax_events, dataset, probabilistic=probabilistic)
    compression_zones = _identify_compression_zones(climax_events, overlap, probabilistic)

    stopping, selling = split_sell_side(climax_events)
    topology = {
        "event_counts": _event_counts(climax_events),
        "grey_zone_rate": round(_grey_zone_rate(dataset), 4),
        "reinforcement_concentration": round(
            float(reinforcement["reinforcement_component"].tail(25).mean())
            if len(reinforcement) > 0 and "reinforcement_component" in reinforcement.columns
            else 0.0,
            4,
        ),
        "contradiction_concentration": round(
            float(probabilistic["conflict_density"].tail(25).mean())
            if len(probabilistic) > 0 and "conflict_density" in probabilistic.columns
            else 0.0,
            4,
        ),
        "entropy_divergence_proxy": round(
            float(stopping["post_climax_entropy_shift"].mean())
            - float(selling["post_climax_entropy_shift"].mean())
            if len(stopping) > 0 and len(selling) > 0
            and "post_climax_entropy_shift" in stopping.columns
            else 0.0,
            4,
        ),
        "overlap_pairs": json.loads(overlap.get("ontology_overlap_matrix", "{}")),
    }

    stability = _clamp(
        1.0
        - float(overlap.get("semantic_overlap_score", 0.0)) * 0.35
        - len(compression_zones) * 0.08
        - _grey_zone_rate(dataset) * 0.20,
    )

    return {
        "ontology_topology_map": json.dumps(topology),
        "ontology_compression_zones": "|".join(compression_zones) if compression_zones else "NONE",
        "semantic_stability_index": round(stability, 4),
    }


def neutral_topology_exports() -> Dict[str, Any]:
    return {
        "ontology_topology_map": json.dumps({}),
        "ontology_compression_zones": "NONE",
        "semantic_stability_index": 1.0,
    }
