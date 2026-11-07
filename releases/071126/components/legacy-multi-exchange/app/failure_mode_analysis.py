"""Probabilistic failure-mode detection — observability only."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pandas as pd

FAILURE_MODES = [
    "CONVICTION_COLLAPSE",
    "RUNAWAY_REINFORCEMENT",
    "ENTROPY_BLINDNESS",
    "CONTRADICTION_SUPPRESSION_FAILURE",
    "REGIME_TRANSITION_INSTABILITY",
    "CALIBRATION_DRIFT_ACCELERATION",
    "UNSTABLE_PERSISTENCE_INHERITANCE",
    "NONE",
]

FAILURE_EXPORT_COLUMNS = [
    "failure_mode",
    "failure_probability",
    "collapse_velocity",
    "instability_cluster",
    "probabilistic_fragility_score",
]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _conviction_column(frame: pd.DataFrame) -> str:
    if "disciplined_conviction" in frame.columns:
        return "disciplined_conviction"
    if "raw_conviction" in frame.columns:
        return "raw_conviction"
    return "conviction_probability"


def analyze_failure_modes(
    snapshot: Dict[str, Any],
    history: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    history = history if history is not None else pd.DataFrame()
    scores: Dict[str, float] = {mode: 0.0 for mode in FAILURE_MODES}

    raw = float(snapshot.get("raw_conviction", snapshot.get("conviction_probability", 0.0)))
    disciplined = float(snapshot.get("disciplined_conviction", raw))
    entropy = float(snapshot.get("entropy_penalty", 0.0))
    conflict = float(snapshot.get("conflict_density", 0.0))
    drift = float(snapshot.get("calibration_drift_score", 0.0))
    persistence_duration = float(snapshot.get("persistence_duration", 0.0))
    transition_probability = float(snapshot.get("regime_transition_probability", 0.0))

    collapse_velocity = 0.0
    if len(history) >= 2:
        column = _conviction_column(history)
        if column in history.columns:
            series = pd.to_numeric(history[column], errors="coerce").dropna()
            if len(series) >= 2:
                collapse_velocity = max(0.0, float(series.iloc[-2] - series.iloc[-1]))

    if collapse_velocity > 0.12 or (raw - disciplined) > 0.20:
        scores["CONVICTION_COLLAPSE"] = _clamp(
            collapse_velocity * 2.5 + max(0.0, raw - disciplined)
        )

    if snapshot.get("runaway_reinforcement") or snapshot.get("repeated_high_conviction"):
        scores["RUNAWAY_REINFORCEMENT"] = _clamp(
            float(snapshot.get("reinforcement_component", 0.0)) * 0.6
            + float(snapshot.get("reinforcement_acceleration", 0.0)) * 2.0
        )

    if raw > 0.60 and entropy < 0.35:
        scores["ENTROPY_BLINDNESS"] = _clamp((0.35 - entropy) * 1.5 + raw * 0.2)

    if snapshot.get("entropy_suppression_failure") or (conflict < 0.15 and raw > 0.65):
        scores["CONTRADICTION_SUPPRESSION_FAILURE"] = _clamp(
            (0.20 - conflict) * 2.0 + raw * 0.15
        )

    if transition_probability > 0.45 or float(snapshot.get("regime_drift_score", 0.0)) > 0.35:
        scores["REGIME_TRANSITION_INSTABILITY"] = _clamp(
            transition_probability * 0.6
            + float(snapshot.get("regime_drift_score", 0.0)) * 0.5
        )

    if drift > 0.25 or float(snapshot.get("drift_persistence_duration", 0.0)) > 2:
        scores["CALIBRATION_DRIFT_ACCELERATION"] = _clamp(
            drift * 0.8
            + float(snapshot.get("drift_persistence_duration", 0.0)) * 0.05
        )

    if persistence_duration < 2 and float(snapshot.get("persistence_component", 0.0)) > 0.45:
        scores["UNSTABLE_PERSISTENCE_INHERITANCE"] = _clamp(
            float(snapshot.get("persistence_component", 0.0)) * 0.5
            + (2.0 - persistence_duration) * 0.10
        )

    scores["NONE"] = 0.05
    failure_mode = max(scores, key=scores.get)
    if failure_mode == "NONE" and max(scores.values()) <= 0.05:
        failure_probability = 0.0
    else:
        failure_probability = _clamp(scores[failure_mode])

    active_modes = [
        mode for mode, score in scores.items() if mode != "NONE" and score > 0.15
    ]
    instability_cluster = json.dumps(active_modes)

    fragility = _clamp(
        failure_probability * 0.35
        + collapse_velocity * 0.25
        + conflict * 0.20
        + drift * 0.20
    )

    return {
        "failure_mode": failure_mode if failure_probability > 0.05 else "NONE",
        "failure_probability": failure_probability,
        "collapse_velocity": collapse_velocity,
        "instability_cluster": instability_cluster,
        "probabilistic_fragility_score": fragility,
    }


def neutral_failure_exports() -> Dict[str, Any]:
    return {
        "failure_mode": "NONE",
        "failure_probability": 0.0,
        "collapse_velocity": 0.0,
        "instability_cluster": json.dumps([]),
        "probabilistic_fragility_score": 0.0,
    }
