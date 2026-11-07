"""Cross-regime calibration stability, walk-forward robustness, and transition analysis."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from calibration_diagnostics import SATURATION_THRESHOLD
from regime_segmentation import REGIME_STATES, infer_regime_segmentation

STABILITY_EXPORT_COLUMNS = [
    "walk_forward_epoch",
    "calibration_stability_score",
    "regime_drift_score",
    "entropy_transition_type",
    "conviction_adaptation_lag",
    "contradiction_duration",
    "contradiction_escalation_score",
    "unresolved_contradiction_score",
    "reinforcement_instability_score",
]

ENTROPY_TRANSITIONS = [
    "LOW_TO_HIGH_ENTROPY",
    "COMPRESSION_TO_EXPANSION",
    "EXHAUSTION_TO_REVERSAL",
    "LIQUIDATION_TO_ABSORPTION",
    "STABLE_ENTROPY",
]

WALK_FORWARD_TRAIN = 200
WALK_FORWARD_FORWARD = 50


def _conviction_column(frame: pd.DataFrame) -> str:
    if "raw_conviction" in frame.columns:
        return "raw_conviction"
    return "conviction_probability"


def label_regime_column(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if "regime_state" in output.columns:
        return output

    regimes = []
    for index in range(len(output)):
        row = output.iloc[index]
        history = output.iloc[:index]
        inferred = infer_regime_segmentation(
            snapshot=row.to_dict(),
            runtime_cognition={},
            probabilistic_history=history,
        )
        regimes.append(inferred["regime_state"])

    output["regime_state"] = regimes
    return output


def metrics_by_regime(frame: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    labeled = label_regime_column(frame)
    conviction_col = _conviction_column(labeled)
    results: Dict[str, Dict[str, float]] = {}

    for regime in REGIME_STATES:
        subset = labeled[labeled["regime_state"] == regime]
        if len(subset) == 0:
            continue

        conviction = pd.to_numeric(subset[conviction_col], errors="coerce")
        entropy = pd.to_numeric(subset.get("entropy_penalty"), errors="coerce")
        conflict = pd.to_numeric(subset.get("conflict_density"), errors="coerce")
        reinforcement = pd.to_numeric(
            subset.get("reinforcement_component"),
            errors="coerce",
        )

        high_conviction = conviction > 0.70
        low_entropy = entropy <= 0.35
        entropy_fail = (high_conviction & low_entropy).mean() if len(subset) else 0.0

        persistence = 0.0
        if "belief_state" in subset.columns:
            persistence = float(
                (subset["belief_state"] == "HIGH_CONVICTION").mean()
            )

        results[regime] = {
            "rows": float(len(subset)),
            "mean_conviction": float(conviction.mean()),
            "saturation_frequency": float((conviction > SATURATION_THRESHOLD).mean()),
            "entropy_suppression_effectiveness": float(1.0 - entropy_fail),
            "mean_conflict_density": float(conflict.mean()) if conflict.notna().any() else 0.0,
            "reinforcement_persistence": persistence
            if persistence
            else float(reinforcement.mean()) if reinforcement.notna().any() else 0.0,
        }

    return results


def detect_entropy_transition(
    current_row: Dict[str, Any],
    history: pd.DataFrame,
    runtime_cognition: Optional[Dict[str, Any]] = None,
) -> str:
    runtime_cognition = runtime_cognition or {}
    if len(history) < 2 or "entropy_penalty" not in history.columns:
        return "STABLE_ENTROPY"

    entropy = pd.to_numeric(history["entropy_penalty"], errors="coerce").dropna()
    if len(entropy) < 2:
        return "STABLE_ENTROPY"

    delta = float(entropy.iloc[-1] - entropy.iloc[-2])
    current_entropy = float(current_row.get("entropy_penalty", entropy.iloc[-1]))
    synthesis = str(runtime_cognition.get("synthesis_state", "NONE"))
    regime = str(current_row.get("regime_state", ""))
    absorption = float(current_row.get("absorption_probability", 0.0))

    if delta > 0.08 and current_entropy > 0.45:
        return "LOW_TO_HIGH_ENTROPY"

    if regime == "COMPRESSION" and delta > 0.05:
        return "COMPRESSION_TO_EXPANSION"

    if synthesis == "LOCAL_EXHAUSTION" and delta > 0.04:
        return "EXHAUSTION_TO_REVERSAL"

    if regime == "LIQUIDATION_EVENT" and absorption > 0.45:
        return "LIQUIDATION_TO_ABSORPTION"

    return "STABLE_ENTROPY"


def compute_contradiction_persistence(
    history: pd.DataFrame,
    current_row: Dict[str, Any],
) -> Dict[str, Any]:
    flags = str(current_row.get("contradiction_flags", ""))
    active = len(flags.split("|")) if flags else 0
    current_density = float(current_row.get("conflict_density", 0.0))

    duration = 0
    escalation = 0.0
    if len(history) > 0 and "conflict_density" in history.columns:
        densities = pd.to_numeric(history["conflict_density"], errors="coerce").dropna()
        for value in reversed(densities.tolist()):
            if value > 0.20:
                duration += 1
            else:
                break
        if active > 0:
            duration += 1
        if len(densities) >= 2:
            escalation = float(densities.iloc[-1] - densities.iloc[-2])

    unresolved = current_density * (1.0 + 0.15 * duration)
    if active >= 3:
        unresolved *= 1.10

    return {
        "contradiction_duration": duration,
        "contradiction_escalation_score": max(0.0, escalation),
        "unresolved_contradiction_score": min(unresolved, 1.0),
    }


def compute_transition_stability(
    history: pd.DataFrame,
    current_row: Dict[str, Any],
    runtime_cognition: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    runtime_cognition = runtime_cognition or {}
    entropy_transition = detect_entropy_transition(
        current_row,
        history,
        runtime_cognition,
    )

    conviction_col = _conviction_column(history) if len(history) else "conviction_probability"
    adaptation_lag = 0.0
    if len(history) >= 3 and conviction_col in history.columns:
        conviction = pd.to_numeric(history[conviction_col], errors="coerce").dropna()
        entropy = pd.to_numeric(history.get("entropy_penalty"), errors="coerce").dropna()
        if len(conviction) >= 3 and len(entropy) >= 3:
            conviction_delta = float(conviction.diff().tail(2).mean())
            entropy_delta = float(entropy.diff().tail(2).mean())
            if abs(entropy_delta) > 0.03:
                adaptation_lag = abs(conviction_delta / entropy_delta)

    reinforcement_instability = 0.0
    if "reinforcement_component" in history.columns and len(history) >= 3:
        reinforcement = pd.to_numeric(
            history["reinforcement_component"],
            errors="coerce",
        ).dropna()
        if len(reinforcement) >= 3:
            reinforcement_instability = float(reinforcement.tail(3).std())

    contradiction = compute_contradiction_persistence(history, current_row)

    return {
        "entropy_transition_type": entropy_transition,
        "conviction_adaptation_lag": adaptation_lag,
        "reinforcement_instability_score": reinforcement_instability,
        **contradiction,
    }


def walk_forward_epochs(
    frame: pd.DataFrame,
    train_window: int = WALK_FORWARD_TRAIN,
    forward_window: int = WALK_FORWARD_FORWARD,
) -> List[Dict[str, Any]]:
    labeled = label_regime_column(frame)
    conviction_col = _conviction_column(labeled)
    epochs: List[Dict[str, Any]] = []

    if len(labeled) < train_window + forward_window:
        train = labeled.iloc[:-1] if len(labeled) > 1 else labeled
        forward = labeled.iloc[-1:]
        epoch_index = 0
    else:
        epoch_index = 0
        for start in range(0, len(labeled) - train_window - forward_window + 1, forward_window):
            train = labeled.iloc[start : start + train_window]
            forward = labeled.iloc[
                start + train_window : start + train_window + forward_window
            ]
            epochs.append(
                _summarize_walk_forward_epoch(
                    train,
                    forward,
                    conviction_col,
                    epoch_index,
                )
            )
            epoch_index += 1
        return epochs

    epochs.append(
        _summarize_walk_forward_epoch(
            train,
            forward,
            conviction_col,
            epoch_index,
        )
    )
    return epochs


def _summarize_walk_forward_epoch(
    train: pd.DataFrame,
    forward: pd.DataFrame,
    conviction_col: str,
    epoch_index: int,
) -> Dict[str, Any]:
    train_conviction = pd.to_numeric(train[conviction_col], errors="coerce").dropna()
    forward_conviction = pd.to_numeric(forward[conviction_col], errors="coerce").dropna()
    train_entropy = pd.to_numeric(train.get("entropy_penalty"), errors="coerce").dropna()
    forward_entropy = pd.to_numeric(forward.get("entropy_penalty"), errors="coerce").dropna()
    train_conflict = pd.to_numeric(train.get("conflict_density"), errors="coerce").dropna()
    forward_conflict = pd.to_numeric(forward.get("conflict_density"), errors="coerce").dropna()

    conviction_drift = 0.0
    if len(train_conviction) and len(forward_conviction):
        conviction_drift = abs(float(forward_conviction.mean()) - float(train_conviction.mean()))

    entropy_drift = 0.0
    if len(train_entropy) and len(forward_entropy):
        entropy_drift = abs(float(forward_entropy.mean()) - float(train_entropy.mean()))

    reinforcement_drift = 0.0
    if "reinforcement_component" in train.columns:
        train_r = pd.to_numeric(train["reinforcement_component"], errors="coerce").dropna()
        forward_r = pd.to_numeric(forward["reinforcement_component"], errors="coerce").dropna()
        if len(train_r) and len(forward_r):
            reinforcement_drift = abs(float(forward_r.mean()) - float(train_r.mean()))

    contradiction_persistence = 0.0
    if len(train_conflict) and len(forward_conflict):
        contradiction_persistence = float(forward_conflict.mean())

    regime_drift = 0.0
    if "regime_state" in train.columns and "regime_state" in forward.columns:
        train_modes = train["regime_state"].value_counts(normalize=True)
        forward_modes = forward["regime_state"].value_counts(normalize=True)
        shared = set(train_modes.index).union(set(forward_modes.index))
        divergence = sum(
            abs(train_modes.get(regime, 0.0) - forward_modes.get(regime, 0.0))
            for regime in shared
        )
        regime_drift = divergence / 2.0

    degradation = (
        conviction_drift * 0.35
        + entropy_drift * 0.20
        + reinforcement_drift * 0.20
        + contradiction_persistence * 0.15
        + regime_drift * 0.10
    )
    stability_score = max(0.0, 1.0 - min(degradation, 1.0))

    return {
        "walk_forward_epoch": epoch_index,
        "calibration_stability_score": stability_score,
        "regime_drift_score": regime_drift,
        "conviction_drift": conviction_drift,
        "entropy_drift": entropy_drift,
        "reinforcement_drift": reinforcement_drift,
        "contradiction_persistence": contradiction_persistence,
        "calibration_degradation": degradation,
    }


def compute_runtime_stability_exports(
    probabilistic_history: pd.DataFrame,
    current_row: Dict[str, Any],
    runtime_cognition: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    runtime_cognition = runtime_cognition or {}
    transition = compute_transition_stability(
        probabilistic_history,
        current_row,
        runtime_cognition,
    )

    epochs = walk_forward_epochs(probabilistic_history)
    if epochs:
        latest_epoch = epochs[-1]
    else:
        latest_epoch = {
            "walk_forward_epoch": 0,
            "calibration_stability_score": 1.0,
            "regime_drift_score": 0.0,
        }

    return {
        "walk_forward_epoch": int(latest_epoch["walk_forward_epoch"]),
        "calibration_stability_score": latest_epoch["calibration_stability_score"],
        "regime_drift_score": latest_epoch["regime_drift_score"],
        **transition,
    }


def unstable_regimes(metrics: Dict[str, Dict[str, float]]) -> List[str]:
    unstable = []
    for regime, values in metrics.items():
        if values.get("saturation_frequency", 0.0) > 0.25:
            unstable.append(regime)
            continue
        if values.get("entropy_suppression_effectiveness", 1.0) < 0.50:
            unstable.append(regime)
            continue
        if values.get("mean_conflict_density", 0.0) > 0.45:
            unstable.append(regime)
    return unstable
