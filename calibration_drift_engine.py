"""Runtime calibration drift monitoring — warning-only, rolling baseline comparison."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pandas as pd

from calibration_diagnostics import SATURATION_THRESHOLD

DRIFT_EXPORT_COLUMNS = [
    "calibration_drift_score",
    "drift_components",
    "drift_direction",
    "drift_persistence_duration",
]

DRIFT_WARNING_THRESHOLD = 0.35
BASELINE_WINDOW = 50


def _safe_mean(series: pd.Series, default: float = 0.0) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) == 0:
        return default
    return float(values.mean())


def _consecutive_above(values: pd.Series, threshold: float) -> int:
    count = 0
    for value in reversed(values.tolist()):
        if float(value) > threshold:
            count += 1
        else:
            break
    return count


def compute_drift_components(
    baseline: pd.DataFrame,
    current: Dict[str, Any],
) -> Dict[str, float]:
    components: Dict[str, float] = {
        "alignment_dominance_creep": 0.0,
        "reinforcement_inflation_recurrence": 0.0,
        "entropy_suppression_weakening": 0.0,
        "contradiction_blindness": 0.0,
        "saturation_relapse": 0.0,
    }

    if len(baseline) == 0:
        return components

    current_alignment = float(current.get("alignment_component", 1.0))
    baseline_alignment = _safe_mean(baseline.get("alignment_component", pd.Series()))
    if baseline_alignment > 0:
        components["alignment_dominance_creep"] = max(
            0.0,
            (current_alignment - baseline_alignment) / baseline_alignment,
        )

    current_reinforcement = float(current.get("reinforcement_component", 0.0))
    baseline_reinforcement = _safe_mean(
        baseline.get("reinforcement_component", pd.Series())
    )
    components["reinforcement_inflation_recurrence"] = max(
        0.0,
        current_reinforcement - baseline_reinforcement,
    )

    current_entropy = float(current.get("entropy_penalty", 0.0))
    baseline_entropy = _safe_mean(baseline.get("entropy_penalty", pd.Series()))
    current_conviction = float(
        current.get(
            "raw_conviction",
            current.get("conviction_probability", 0.0),
        )
    )
    if current_conviction > 0.65 and current_entropy >= baseline_entropy:
        components["entropy_suppression_weakening"] = max(
            0.0,
            (current_entropy - baseline_entropy) / max(baseline_entropy, 1e-6),
        )

    current_conflict = float(current.get("conflict_density", 0.0))
    baseline_conflict = _safe_mean(baseline.get("conflict_density", pd.Series()))
    if current_conflict < baseline_conflict * 0.70 and current_conviction > 0.60:
        components["contradiction_blindness"] = max(
            0.0,
            baseline_conflict - current_conflict,
        )

    baseline_saturation = _safe_mean(
        (baseline.get("raw_conviction", baseline.get("conviction_probability", pd.Series())) > SATURATION_THRESHOLD).astype(float)
    )
    if current_conviction > SATURATION_THRESHOLD and baseline_saturation < 0.20:
        components["saturation_relapse"] = current_conviction - SATURATION_THRESHOLD

    return components


def compute_calibration_drift(
    probabilistic_history: pd.DataFrame,
    current_row: Dict[str, Any],
    baseline_window: int = BASELINE_WINDOW,
) -> Dict[str, Any]:
    if len(probabilistic_history) == 0:
        return {
            "calibration_drift_score": 0.0,
            "drift_components": json.dumps({}),
            "drift_direction": "stable",
            "drift_persistence_duration": 0,
        }

    baseline = probabilistic_history.tail(baseline_window)
    components = compute_drift_components(baseline, current_row)

    drift_score = sum(components.values()) / max(len(components), 1)
    drift_score = min(drift_score, 1.0)

    if drift_score > DRIFT_WARNING_THRESHOLD:
        direction = "degrading"
    elif drift_score > 0.15:
        direction = "elevated"
    else:
        direction = "stable"

    history_scores = []
    if "calibration_drift_score" in probabilistic_history.columns:
        history_scores = pd.to_numeric(
            probabilistic_history["calibration_drift_score"],
            errors="coerce",
        ).dropna()
    persistence = 0
    if len(history_scores) > 0:
        persistence = _consecutive_above(history_scores, DRIFT_WARNING_THRESHOLD)
    if drift_score > DRIFT_WARNING_THRESHOLD:
        persistence += 1

    return {
        "calibration_drift_score": drift_score,
        "drift_components": json.dumps(
            {key: round(value, 4) for key, value in components.items()}
        ),
        "drift_direction": direction,
        "drift_persistence_duration": persistence,
    }


def log_drift_warning(drift_result: Dict[str, Any]) -> None:
    if drift_result.get("drift_direction") in {"degrading", "elevated"}:
        print(
            "[RUNTIME WARNING] calibration drift "
            f"score={drift_result.get('calibration_drift_score'):.3f} "
            f"direction={drift_result.get('drift_direction')}"
        )
