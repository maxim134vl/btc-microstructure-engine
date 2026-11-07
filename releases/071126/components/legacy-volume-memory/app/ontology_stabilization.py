"""Phase 3B ontology stabilization orchestrator — warning-first, observability only."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from buying_exhaustion_validation import (
    BUYING_EXPORT_COLUMNS,
    analyze_buying_exhaustion,
    neutral_buying_exports,
)
from contradiction_redistribution import (
    CONTRADICTION_EXPORT_COLUMNS,
    analyze_contradiction_redistribution,
    neutral_contradiction_exports,
)
from hav_semantic_analysis import (
    HAV_EXPORT_COLUMNS,
    analyze_hav_semantics,
    neutral_hav_exports,
)
from ontology_drift_detection import (
    DRIFT_EXPORT_COLUMNS,
    detect_ontology_drift,
    neutral_drift_exports,
)
from ontology_overlap_matrix import (
    OVERLAP_EXPORT_COLUMNS,
    build_overlap_matrix,
    neutral_overlap_exports,
)
from ontology_transition_stability import (
    TRANSITION_EXPORT_COLUMNS,
    analyze_ontology_transition_stability,
    neutral_transition_exports,
)
from post_split_reinforcement_analysis import (
    REINFORCEMENT_EXPORT_COLUMNS,
    analyze_reinforcement_redistribution,
    neutral_reinforcement_exports,
)
from semantic_entropy_evolution import (
    ENTROPY_EVOLUTION_EXPORT_COLUMNS,
    analyze_entropy_evolution_divergence,
    neutral_entropy_evolution_exports,
)
from stabilization_config import (
    StabilizationSettings,
    get_stabilization_settings,
    stabilization_active,
)
from stabilization_data_utils import ensure_ontology_features, load_candle_structure, load_climax_events

STABILIZATION_EXPORT_COLUMNS = (
    REINFORCEMENT_EXPORT_COLUMNS
    + CONTRADICTION_EXPORT_COLUMNS
    + ENTROPY_EVOLUTION_EXPORT_COLUMNS
    + TRANSITION_EXPORT_COLUMNS
    + DRIFT_EXPORT_COLUMNS
    + BUYING_EXPORT_COLUMNS
    + HAV_EXPORT_COLUMNS
    + OVERLAP_EXPORT_COLUMNS
    + ["ontology_stabilization_active"]
)


def log_stabilization_warning(message: str) -> None:
    print(f"[STABILIZATION WARNING] {message}")


def build_ontology_stabilization_exports(
    snapshot: Dict[str, Any],
    runtime_cognition: Optional[Dict[str, Any]] = None,
    probabilistic_history: Optional[pd.DataFrame] = None,
    reinforcement_history: Optional[pd.DataFrame] = None,
    candle_history: Optional[pd.DataFrame] = None,
    climax_events: Optional[pd.DataFrame] = None,
    settings: Optional[StabilizationSettings] = None,
) -> Dict[str, Any]:
    settings = settings or get_stabilization_settings()
    runtime_cognition = runtime_cognition or {}
    probabilistic_history = (
        probabilistic_history if probabilistic_history is not None else pd.DataFrame()
    )
    reinforcement_history = (
        reinforcement_history if reinforcement_history is not None else pd.DataFrame()
    )
    candle_history = candle_history if candle_history is not None else load_candle_structure()
    candle_history = ensure_ontology_features(candle_history)
    climax_events = climax_events if climax_events is not None else load_climax_events()

    if not stabilization_active(settings):
        return {
            **neutral_reinforcement_exports(),
            **neutral_contradiction_exports(),
            **neutral_entropy_evolution_exports(),
            **neutral_transition_exports(),
            **neutral_drift_exports(),
            **neutral_buying_exports(),
            **neutral_hav_exports(),
            **neutral_overlap_exports(),
            "ontology_stabilization_active": False,
        }

    reinforcement_exports = analyze_reinforcement_redistribution(
        climax_events,
        probabilistic=probabilistic_history,
        reinforcement=reinforcement_history,
    )
    contradiction_exports = analyze_contradiction_redistribution(
        climax_events,
        probabilistic=probabilistic_history,
    )
    entropy_exports = analyze_entropy_evolution_divergence(climax_events)
    transition_exports = analyze_ontology_transition_stability(
        snapshot,
        probabilistic=probabilistic_history,
    )
    overlap_exports = build_overlap_matrix(
        climax_events,
        candle_history,
        probabilistic=probabilistic_history,
    )
    buying_exports = analyze_buying_exhaustion(climax_events, candle_history)
    hav_exports = analyze_hav_semantics(
        climax_events,
        candle_history,
        probabilistic=probabilistic_history,
    )
    drift_exports = detect_ontology_drift(
        climax_events,
        candle_history,
        reinforcement_exports,
        contradiction_exports,
        overlap_score=float(overlap_exports.get("semantic_overlap_score", 0.0)),
    )

    exports = {
        **reinforcement_exports,
        **contradiction_exports,
        **entropy_exports,
        **transition_exports,
        **drift_exports,
        **buying_exports,
        **hav_exports,
        **overlap_exports,
        "ontology_stabilization_active": True,
        "trigger_event": runtime_cognition.get("trigger_event"),
    }

    if settings.warn_on_drift:
        drift_score = float(exports.get("ontology_drift_score", 0.0))
        fragility = float(exports.get("semantic_fragility_score", 0.0))
        overlap = float(exports.get("semantic_overlap_score", 0.0))

        if drift_score >= settings.drift_warning_threshold:
            log_stabilization_warning(
                f"ontology_drift={drift_score:.3f} trigger={exports.get('trigger_event')}",
            )
        if fragility >= settings.fragility_warning_threshold:
            log_stabilization_warning(f"semantic_fragility={fragility:.3f}")
        if overlap >= settings.overlap_warning_threshold:
            log_stabilization_warning(f"semantic_overlap={overlap:.3f}")

    return exports
