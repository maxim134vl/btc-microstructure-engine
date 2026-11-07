"""Track cognition metric evolution over time."""

from __future__ import annotations

from typing import Any

TRACKED_SERIES = [
    ("confidence_realism_score", "confidence_realism"),
    ("contradiction_pressure_score", "contradiction_pressure"),
    ("ontology_integrity_score", "ontology_integrity"),
    ("transition_stability_score", "transition_stability"),
    ("cognition_stability_score", "cognition_stability"),
    ("narrative_coherence", "narrative_coherence"),
    ("narrative_stability", "narrative_stability"),
    ("cognition_drift_frequency", "cognition_drift"),
    ("calibration_health_score", "calibration_effectiveness"),
    ("overconfident_rate", "confidence_inflation"),
]


def _extract(cycle: dict[str, Any], key: str) -> float | None:
    layers = cycle.get("layers") or {}
    for layer_data in layers.values():
        summary = layer_data.get("summary") or {}
        if key in summary and summary[key] is not None:
            return float(summary[key])
    conf = layers.get("conformance") or {}
    summary = conf.get("summary") or {}
    if key in summary and summary[key] is not None:
        return float(summary[key])
    return None


def build_evolution_timeline(history: list[dict[str, Any]]) -> dict[str, Any]:
    timeline: dict[str, list[dict[str, Any]]] = {alias: [] for _, alias in TRACKED_SERIES}

    for cycle in history:
        cid = cycle.get("cycle_id")
        ts = cycle.get("generated_at")
        for key, alias in TRACKED_SERIES:
            value = _extract(cycle, key)
            if value is not None:
                timeline[alias].append({"cycle_id": cid, "timestamp": ts, "value": value})

    trends: dict[str, str] = {}
    for alias, points in timeline.items():
        if len(points) < 2:
            trends[alias] = "insufficient_data"
            continue
        first = points[0]["value"]
        last = points[-1]["value"]
        lower_better = alias in ("cognition_drift", "confidence_inflation", "contradiction_pressure")
        if lower_better:
            trends[alias] = "improving" if last < first - 0.03 else "degrading" if last > first + 0.03 else "stable"
        else:
            trends[alias] = "improving" if last > first + 0.03 else "degrading" if last < first - 0.03 else "stable"

    return {"timeline": timeline, "trends": trends, "cycle_count": len(history)}
