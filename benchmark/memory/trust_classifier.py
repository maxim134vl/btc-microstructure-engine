"""Classify cognition trust levels for cycles and events."""

from __future__ import annotations

from typing import Any

TRUST_LEVELS = (
    "VERIFIED",
    "STABLE",
    "NOISY",
    "LOW_TRUST",
    "DEGRADED",
    "TOXIC",
    "ONTOLOGY_COLLAPSE",
    "CALIBRATION_COLLAPSE",
)


def classify_cycle_trust(cycle: dict[str, Any]) -> dict[str, Any]:
    layers = cycle.get("layers") or {}
    conformance = layers.get("conformance") or {}
    integrated = layers.get("integrated") or {}
    stage2 = layers.get("stage2") or {}

    summary = conformance.get("summary") or {}
    calibration = conformance.get("calibration") or {}
    drift = conformance.get("drift") or {}

    health = summary.get("cognition_health") or conformance.get("cognition_health")
    stability = float(summary.get("cognition_stability_score") or 0.0)
    overconfident = float((stage2.get("summary") or {}).get("overconfident_rate") or 0.0)
    drift_freq = float((integrated.get("summary") or {}).get("cognition_drift_frequency") or 0.0)
    cal_status = calibration.get("status")

    if cal_status == "CRITICAL" or summary.get("verdict_distribution", {}).get("CALIBRATION_COLLAPSE", 0) >= 2:
        level = "CALIBRATION_COLLAPSE"
    elif summary.get("verdict_distribution", {}).get("ONTOLOGY_DEGRADATION", 0) >= 2:
        level = "ONTOLOGY_COLLAPSE"
    elif health == "DEGRADED" or drift.get("severity") == "SEVERE":
        level = "TOXIC" if overconfident >= 0.7 or drift_freq >= 0.7 else "DEGRADED"
    elif health == "DRIFTING" or stability < 0.55:
        level = "LOW_TRUST" if overconfident >= 0.5 else "NOISY"
    elif stability >= 0.75 and health == "STABLE":
        level = "VERIFIED" if stability >= 0.85 else "STABLE"
    else:
        level = "STABLE"

    return {
        "trust_level": level,
        "cognition_health": health,
        "stability_score": stability,
        "overconfident_rate": overconfident,
        "drift_frequency": drift_freq,
    }


def classify_event_trust(event: dict[str, Any]) -> str:
    verdict = event.get("integrated_verdict") or event.get("verdict") or ""
    confidence = event.get("confidence_quality") or event.get("confidence_realism")
    contradiction = event.get("contradiction_level") or event.get("contradiction_propagation")

    if verdict in ("ONTOLOGY_DRIFT", "SYNTHESIS_COLLAPSE", "ONTOLOGY_DEGRADATION"):
        return "ONTOLOGY_COLLAPSE"
    if verdict in ("CONFIDENCE_FAILURE",) or confidence in ("POOR", "OVERCONFIDENT"):
        return "CALIBRATION_COLLAPSE"
    if verdict in ("CONTRADICTORY", "CONTRADICTION_FAILURE") or contradiction in ("HIGH", "CASCADE"):
        return "TOXIC"
    if verdict in ("FULLY_CONFIRMED", "CONFIRMED"):
        return "VERIFIED"
    if verdict in ("PARTIAL", "PARTIAL_CONFIRMATION"):
        return "STABLE"
    if verdict in ("FAILED", "FALSE_NARRATIVE", "REASONING_FAILURE", "PERCEPTION_FAILURE"):
        return "DEGRADED"
    return "NOISY"
