"""Ontology integrity scoring from conformance results."""

from __future__ import annotations

from typing import Any

ONTOLOGY_METRICS = {
    "market_structure_coherence",
    "ontology_coherence",
    "narrative_coherence",
    "narrative_stability",
    "cross_stage_alignment",
    "contradiction_frequency",
    "contradiction_propagation",
}


def score_ontology_integrity(results: list[dict[str, Any]]) -> dict[str, Any]:
    ontology_rows = [r for r in results if r["metric"] in ONTOLOGY_METRICS]
    if not ontology_rows:
        return {"score": 0.5, "status": "UNKNOWN", "issues": []}

    confirmed = sum(1 for r in ontology_rows if r["verdict"] == "CONFIRMED")
    partial = sum(1 for r in ontology_rows if r["verdict"] == "PARTIAL")
    failed = sum(1 for r in ontology_rows if r["verdict"] not in ("CONFIRMED", "PARTIAL"))

    score = round((confirmed + partial * 0.5) / len(ontology_rows), 4)
    issues = [f"{r['metric']}: {r['verdict']}" for r in ontology_rows if r["verdict"] not in ("CONFIRMED", "PARTIAL")]

    if score >= 0.75:
        status = "INTACT"
    elif score >= 0.50:
        status = "STRAINED"
    else:
        status = "FRAGMENTED"

    return {
        "score": score,
        "status": status,
        "issues": issues,
        "metric_count": len(ontology_rows),
    }
