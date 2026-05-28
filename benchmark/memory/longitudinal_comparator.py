"""Compare current cognition cycle against historical memory."""

from __future__ import annotations

from typing import Any


def _metric_from_cycle(cycle: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        layers = cycle.get("layers") or {}
        for layer_data in layers.values():
            summary = layer_data.get("summary") or {}
            if key in summary and summary[key] is not None:
                return float(summary[key])
        conformance = layers.get("conformance") or {}
        summary = conformance.get("summary") or {}
        if key in summary and summary[key] is not None:
            return float(summary[key])
    return None


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def compare_longitudinal(current: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    if not history or len(history) < 2:
        return {
            "status": "BASELINE",
            "previous_cycle_id": None,
            "comparisons": [],
            "rolling_average": {},
            "message": "Insufficient history — establishing baseline.",
        }

    previous = history[-2] if history[-1].get("cycle_id") == current.get("cycle_id") else history[-1]
    prior_cycles = [c for c in history if c.get("cycle_id") != current.get("cycle_id")]

    metrics = [
        ("cognition_stability_score", "Cognition stability"),
        ("confidence_realism_score", "Confidence realism"),
        ("ontology_integrity_score", "Ontology integrity"),
        ("transition_stability_score", "Transition stability"),
        ("contradiction_pressure_score", "Contradiction pressure"),
        ("calibration_health_score", "Calibration health"),
        ("confirmed_rate", "Stage 1 confirmation"),
        ("reasoning_accuracy", "Reasoning accuracy"),
        ("cognition_drift_frequency", "Cognition drift"),
        ("overconfident_rate", "Overconfidence"),
    ]

    comparisons: list[dict[str, Any]] = []
    rolling: dict[str, float | None] = {}

    for key, label in metrics:
        current_val = _metric_from_cycle(current, key)
        previous_val = _metric_from_cycle(previous, key)
        historical_vals = [_metric_from_cycle(c, key) for c in prior_cycles]
        historical_vals = [v for v in historical_vals if v is not None]
        rolling[key] = round(_avg(historical_vals), 4) if historical_vals else None

        if current_val is None:
            continue

        delta_prev = None
        if previous_val is not None:
            delta_prev = round(current_val - previous_val, 4)

        delta_baseline = None
        if rolling[key] is not None:
            delta_baseline = round(current_val - rolling[key], 4)

        lower_is_better = key in ("cognition_drift_frequency", "overconfident_rate", "contradiction_pressure_score")
        trend = "stable"
        if delta_prev is not None:
            if lower_is_better:
                trend = "improving" if delta_prev < -0.03 else "degrading" if delta_prev > 0.03 else "stable"
            else:
                trend = "improving" if delta_prev > 0.03 else "degrading" if delta_prev < -0.03 else "stable"

        comparisons.append(
            {
                "metric": key,
                "label": label,
                "current": current_val,
                "previous": previous_val,
                "rolling_average": rolling[key],
                "delta_vs_previous": delta_prev,
                "delta_vs_baseline": delta_baseline,
                "trend": trend,
            }
        )

    best_stability = max(
        prior_cycles,
        key=lambda c: _metric_from_cycle(c, "cognition_stability_score") or 0.0,
        default=None,
    )
    worst_stability = min(
        prior_cycles,
        key=lambda c: _metric_from_cycle(c, "cognition_stability_score") or 1.0,
        default=None,
    )

    return {
        "status": "OK",
        "previous_cycle_id": previous.get("cycle_id"),
        "comparisons": comparisons,
        "rolling_average": rolling,
        "best_stability_cycle": best_stability.get("cycle_id") if best_stability else None,
        "worst_stability_cycle": worst_stability.get("cycle_id") if worst_stability else None,
        "history_length": len(history),
    }
