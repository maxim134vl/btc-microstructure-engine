"""Regime-transition stability validation for post-split ontology."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

TRANSITION_EXPORT_COLUMNS = [
    "ontology_transition_stability",
    "transition_contradiction_escalation",
    "transition_reinforcement_destabilization",
    "transition_entropy_amplification",
]

TRACKED_REGIMES = frozenset(
    {
        "TREND_EXHAUSTION",
        "VOLATILITY_EXPANSION",
        "LIQUIDATION_EVENT",
        "ABSORPTION_RECOVERY",
    }
)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def analyze_ontology_transition_stability(
    snapshot: Dict[str, Any],
    probabilistic: pd.DataFrame | None = None,
) -> Dict[str, Any]:
    regime_state = str(snapshot.get("regime_state", "BALANCED_AUCTION"))
    transition_probability = float(snapshot.get("regime_transition_probability", 0.0))
    contradiction_escalation = float(snapshot.get("contradiction_escalation_score", 0.0))
    reinforcement_instability = float(
        snapshot.get("reinforcement_instability_score", 0.0),
    )
    entropy_transition = str(snapshot.get("entropy_transition_type", "STABLE"))

    entropy_amplification = 0.35 if entropy_transition == "LOW_TO_HIGH_ENTROPY" else 0.10
    if probabilistic is not None and len(probabilistic) > 0:
        if "entropy_penalty" in probabilistic.columns:
            tail = probabilistic["entropy_penalty"].tail(10).astype(float)
            if len(tail) >= 2:
                entropy_amplification = max(
                    entropy_amplification,
                    float(tail.diff().abs().mean()),
                )

    in_tracked = regime_state in TRACKED_REGIMES
    transition_stress = (
        transition_probability * 0.35
        + contradiction_escalation * 0.25
        + reinforcement_instability * 0.25
        + entropy_amplification * 0.15
    )
    if in_tracked:
        transition_stress *= 1.10

    stability = _clamp(1.0 - transition_stress)

    return {
        "ontology_transition_stability": round(stability, 4),
        "transition_contradiction_escalation": round(contradiction_escalation, 4),
        "transition_reinforcement_destabilization": round(reinforcement_instability, 4),
        "transition_entropy_amplification": round(entropy_amplification, 4),
    }


def neutral_transition_exports() -> Dict[str, Any]:
    return {
        "ontology_transition_stability": 1.0,
        "transition_contradiction_escalation": 0.0,
        "transition_reinforcement_destabilization": 0.0,
        "transition_entropy_amplification": 0.0,
    }
