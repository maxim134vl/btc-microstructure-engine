"""Regime-transition survival analysis for adversarial robustness."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

TRACKED_TRANSITIONS: List[Tuple[str, str]] = [
    ("TREND_EXPANSION", "TREND_EXHAUSTION"),
    ("COMPRESSION", "VOLATILITY_EXPANSION"),
    ("LIQUIDATION_EVENT", "ABSORPTION_RECOVERY"),
    ("BALANCED_AUCTION", "TREND_EXPANSION"),
]

SURVIVAL_EXPORT_COLUMNS = [
    "transition_pair",
    "transition_survival_score",
    "transition_conviction_lag",
    "transition_reinforcement_destabilization",
    "transition_contradiction_escalation",
    "transition_entropy_sensitivity",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def detect_active_transition(
    history: pd.DataFrame,
    current_regime: str,
) -> Tuple[str, str]:
    if len(history) == 0 or "regime_state" not in history.columns:
        return ("UNKNOWN", current_regime)

    previous = str(history.iloc[-1].get("regime_state", "UNKNOWN"))
    return (previous, current_regime)


def compute_transition_survival(
    snapshot: Dict[str, Any],
    history: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    history = history if history is not None else pd.DataFrame()
    current_regime = str(snapshot.get("regime_state", "BALANCED_AUCTION"))
    previous_regime, next_regime = detect_active_transition(history, current_regime)

    transition_pair = f"{previous_regime}->{next_regime}"
    matched = (previous_regime, next_regime) in TRACKED_TRANSITIONS

    conviction_lag = float(snapshot.get("conviction_adaptation_lag", 0.0))
    reinforcement_destabilization = max(
        0.0,
        float(snapshot.get("reinforcement_instability_score", 0.0)),
        float(snapshot.get("reinforcement_acceleration", 0.0)),
    )
    contradiction_escalation = float(
        snapshot.get("contradiction_escalation_score", 0.0)
    )
    entropy_sensitivity = abs(
        float(snapshot.get("entropy_interaction", 0.0))
    ) + float(snapshot.get("uncertainty_escalation", 0.0))

    penalty = (
        min(1.0, conviction_lag * 0.25)
        + min(1.0, reinforcement_destabilization * 0.30)
        + min(1.0, contradiction_escalation * 0.25)
        + min(1.0, entropy_sensitivity * 0.20)
    )
    survival_score = _clamp(1.0 - penalty)

    if not matched:
        survival_score = max(survival_score, 0.75)

    return {
        "transition_pair": transition_pair,
        "transition_survival_score": survival_score,
        "transition_conviction_lag": conviction_lag,
        "transition_reinforcement_destabilization": reinforcement_destabilization,
        "transition_contradiction_escalation": contradiction_escalation,
        "transition_entropy_sensitivity": entropy_sensitivity,
    }


def neutral_survival_exports() -> Dict[str, Any]:
    return {
        "transition_pair": "none",
        "transition_survival_score": 1.0,
        "transition_conviction_lag": 0.0,
        "transition_reinforcement_destabilization": 0.0,
        "transition_contradiction_escalation": 0.0,
        "transition_entropy_sensitivity": 0.0,
    }
