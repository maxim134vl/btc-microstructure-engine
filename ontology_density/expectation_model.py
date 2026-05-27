"""Expected ontology-event density by timeframe — architecture-aligned baselines."""

from __future__ import annotations

from typing import Any, Dict

# Baselines derived from in-repo architecture docs (ONTOLOGY_REFINEMENT_MODEL,
# EFFORT_RESULT_SEMANTICS, CANONICAL_RUNTIME_MAP) pending external docx attachment.
# These are per-CANDLE rates on structure memory, not per probabilistic row.

TIMEFRAME_DENSITY_EXPECTATION: Dict[str, Dict[str, Any]] = {
    "M15": {
        "reference": "Stage 1 structure + Stage 2 climax path (M15 default replay TF)",
        "total_climax_rate_per_candle": {"typical_min": 0.01, "typical_max": 0.08},
        "by_class_per_candle": {
            "BUYING_CLIMAX": {"typical_min": 0.002, "typical_max": 0.025},
            "SELLING_CLIMAX": {"typical_min": 0.002, "typical_max": 0.020},
            "STOPPING_VOLUME": {"typical_min": 0.003, "typical_max": 0.030},
            "HIGH_AVERAGE_VOLUME": {"typical_min": 0.005, "typical_max": 0.040},
        },
        "notes": (
            "Climax labels are sparse by design; grey zone (0.85–1.20 efficiency_decay) "
            "withholds ambiguous sell-side classification per Phase 3A architecture."
        ),
    },
    "M5": {
        "reference": "Higher bar count — expect lower per-bar rate, similar absolute frequency",
        "total_climax_rate_per_candle": {"typical_min": 0.005, "typical_max": 0.05},
        "by_class_per_candle": {
            "BUYING_CLIMAX": {"typical_min": 0.001, "typical_max": 0.015},
            "SELLING_CLIMAX": {"typical_min": 0.001, "typical_max": 0.012},
            "STOPPING_VOLUME": {"typical_min": 0.002, "typical_max": 0.020},
            "HIGH_AVERAGE_VOLUME": {"typical_min": 0.003, "typical_max": 0.025},
        },
    },
}


def build_timeframe_density_expectation(timeframe: str = "M15") -> Dict[str, Any]:
    tf = timeframe if timeframe in TIMEFRAME_DENSITY_EXPECTATION else "M15"
    model = TIMEFRAME_DENSITY_EXPECTATION[tf].copy()
    model["timeframe"] = tf
    model["ontology_event_expectation_model"] = True
    return model


def build_ontology_event_expectation_model(timeframe: str = "M15") -> Dict[str, Any]:
    return build_timeframe_density_expectation(timeframe)
