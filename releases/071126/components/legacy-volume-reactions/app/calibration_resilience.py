"""Calibration resilience metrics under adversarial instability."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

RESILIENCE_EXPORT_COLUMNS = [
    "resilience_score",
    "adversarial_stability_score",
    "probabilistic_recovery_rate",
    "instability_decay_half_life",
    "stress_sensitivity_score",
    "adversarial_diagnostics_active",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _estimate_half_life(values: pd.Series) -> float:
    positive = values[values > 0]
    if len(positive) < 2:
        return float("nan")

    ratios = positive.iloc[1:].values / positive.iloc[:-1].values
    ratios = ratios[(ratios > 0) & (ratios < 1)]
    if len(ratios) == 0:
        return float("nan")
    mean_ratio = float(np.mean(ratios))
    if mean_ratio <= 0 or mean_ratio >= 1:
        return float("nan")
    return float(-1.0 / np.log(mean_ratio))


def compute_resilience_metrics(
    snapshot: Dict[str, Any],
    history: Optional[pd.DataFrame] = None,
    failure_exports: Optional[Dict[str, Any]] = None,
    stress_sensitivity: float = 0.0,
    active: bool = False,
) -> Dict[str, Any]:
    history = history if history is not None else pd.DataFrame()
    failure_exports = failure_exports or {}

    fragility = float(failure_exports.get("probabilistic_fragility_score", 0.0))
    cascade = float(snapshot.get("cascade_severity", 0.0))
    stability = float(snapshot.get("calibration_stability_score", 1.0))
    survival = float(snapshot.get("transition_survival_score", 1.0))

    adversarial_stability = _clamp(
        stability * 0.40
        + survival * 0.30
        + (1.0 - fragility) * 0.30
    )

    recovery_rate = 0.0
    if len(history) >= 3 and "probabilistic_fragility_score" in history.columns:
        fragilities = pd.to_numeric(
            history["probabilistic_fragility_score"],
            errors="coerce",
        ).dropna()
        if len(fragilities) >= 2:
            recovery_rate = max(
                0.0,
                float(fragilities.iloc[-2] - fragilities.iloc[-1]),
            )

    cascade_series = pd.Series(dtype=float)
    if len(history) > 0 and "cascade_severity" in history.columns:
        cascade_series = pd.to_numeric(
            history["cascade_severity"],
            errors="coerce",
        ).dropna()
    half_life = _estimate_half_life(cascade_series.tail(20))
    if np.isnan(half_life):
        half_life = 0.0

    resilience_score = _clamp(
        adversarial_stability * 0.45
        + (1.0 - cascade) * 0.25
        + min(1.0, recovery_rate * 2.0) * 0.20
        + (1.0 - stress_sensitivity) * 0.10
    )

    return {
        "resilience_score": resilience_score,
        "adversarial_stability_score": adversarial_stability,
        "probabilistic_recovery_rate": _clamp(recovery_rate),
        "instability_decay_half_life": float(half_life),
        "stress_sensitivity_score": _clamp(stress_sensitivity),
        "adversarial_diagnostics_active": active,
    }


def neutral_resilience_exports() -> Dict[str, Any]:
    return {
        "resilience_score": 1.0,
        "adversarial_stability_score": 1.0,
        "probabilistic_recovery_rate": 0.0,
        "instability_decay_half_life": 0.0,
        "stress_sensitivity_score": 0.0,
        "adversarial_diagnostics_active": False,
    }
