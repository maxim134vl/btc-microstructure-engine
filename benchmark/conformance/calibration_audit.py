"""Generate calibration guidance from conformance failures."""

from __future__ import annotations

from typing import Any


def build_calibration_audit(results: list[dict[str, Any]]) -> dict[str, Any]:
    recommendations: list[dict[str, Any]] = []
    seen: set[str] = set()

    priority_order = (
        "CALIBRATION_COLLAPSE",
        "SEVERE_DRIFT",
        "ONTOLOGY_DEGRADATION",
        "FAILED",
        "DRIFTING",
        "PARTIAL",
    )

    for verdict in priority_order:
        for row in results:
            if row["verdict"] != verdict:
                continue
            hint = row.get("calibration_hint")
            if not hint or hint in seen:
                continue
            seen.add(hint)
            recommendations.append(
                {
                    "priority": verdict,
                    "layer": row["layer"],
                    "metric": row["metric"],
                    "recommendation": hint,
                    "evidence": row.get("note"),
                    "observed_value": row.get("observed_value"),
                }
            )

    collapse = sum(1 for r in results if r["verdict"] == "CALIBRATION_COLLAPSE")
    severe = sum(1 for r in results if r["verdict"] == "SEVERE_DRIFT")

    if collapse >= 2:
        status = "CRITICAL"
    elif severe >= 2 or len(recommendations) >= 4:
        status = "NEEDS_REVIEW"
    elif recommendations:
        status = "ADVISORY"
    else:
        status = "STABLE"

    return {
        "status": status,
        "recommendation_count": len(recommendations),
        "recommendations": recommendations,
    }
