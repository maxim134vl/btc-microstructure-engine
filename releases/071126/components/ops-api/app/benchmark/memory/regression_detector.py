"""Detect cognition regressions and improvements across cycles."""

from __future__ import annotations

from typing import Any


IMPROVEMENT_METRICS = {
    "cognition_stability_score",
    "confidence_realism_score",
    "ontology_integrity_score",
    "transition_stability_score",
    "calibration_health_score",
    "confirmed_rate",
    "reasoning_accuracy",
    "fully_confirmed_rate",
    "cross_stage_alignment",
    "market_confirmation_rate",
    "narrative_coherence",
    "narrative_stability",
}

REGRESSION_IF_HIGHER = {
    "cognition_drift_frequency",
    "overconfident_rate",
    "contradiction_frequency",
    "contradiction_propagation",
    "false_positive_rate",
    "confidence_drift",
    "drift_severity_score",
}


def detect_regressions(comparison: dict[str, Any], trust: dict[str, Any]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    improvements = 0
    regressions = 0

    for row in comparison.get("comparisons") or []:
        metric = row["metric"]
        delta = row.get("delta_vs_previous")
        if delta is None:
            continue

        if metric in REGRESSION_IF_HIGHER:
            if delta > 0.05:
                regressions += 1
                events.append(
                    {
                        "type": "REGRESSION",
                        "metric": metric,
                        "label": row["label"],
                        "delta": delta,
                        "note": f"{row['label']} increased vs previous cycle.",
                    }
                )
            elif delta < -0.05:
                improvements += 1
                events.append(
                    {
                        "type": "IMPROVEMENT",
                        "metric": metric,
                        "label": row["label"],
                        "delta": delta,
                        "note": f"{row['label']} decreased — positive calibration effect.",
                    }
                )
        elif metric in IMPROVEMENT_METRICS:
            if delta < -0.05:
                regressions += 1
                events.append(
                    {
                        "type": "REGRESSION",
                        "metric": metric,
                        "label": row["label"],
                        "delta": delta,
                        "note": f"{row['label']} declined vs previous cycle.",
                    }
                )
            elif delta > 0.05:
                improvements += 1
                events.append(
                    {
                        "type": "IMPROVEMENT",
                        "metric": metric,
                        "label": row["label"],
                        "delta": delta,
                        "note": f"{row['label']} improved vs previous cycle.",
                    }
                )

    if trust.get("trust_level") in ("TOXIC", "ONTOLOGY_COLLAPSE", "CALIBRATION_COLLAPSE"):
        regressions += 1
        events.append(
            {
                "type": "REGRESSION",
                "metric": "trust_level",
                "label": "Trust classification",
                "delta": None,
                "note": f"Cycle classified as {trust.get('trust_level')}.",
            }
        )

    if regressions > improvements and regressions >= 2:
        verdict = "REGRESSION"
    elif improvements > regressions and improvements >= 2:
        verdict = "IMPROVEMENT"
    elif regressions == 0 and improvements == 0:
        verdict = "STABLE"
    else:
        verdict = "MIXED"

    return {
        "verdict": verdict,
        "improvement_count": improvements,
        "regression_count": regressions,
        "events": events,
    }
