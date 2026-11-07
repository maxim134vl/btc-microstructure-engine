"""Aggregate integrated cognition metrics and drift analysis."""

from __future__ import annotations

from collections import Counter
from typing import Any


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return _empty_summary()

    total = len(results)
    verdicts = Counter(r["integrated_verdict"] for r in results)
    root_causes = Counter(r.get("root_cause", "none") for r in results if r.get("root_cause") != "none")

    s1_confirmed = sum(1 for r in results if r.get("stage1_verdict") == "CONFIRMED")
    s2_confirmed = sum(1 for r in results if r.get("stage2_verdict") == "CONFIRMED")
    fully_confirmed = verdicts.get("FULLY_CONFIRMED", 0)
    high_alignment = sum(1 for r in results if r.get("alignment_level") == "HIGH")
    good_confidence = sum(1 for r in results if r.get("confidence_realism") in ("GOOD", "CONSERVATIVE"))
    cascades = sum(1 for r in results if r.get("contradiction_propagation") == "CASCADE")
    drift_signals = sum(
        1
        for r in results
        if r.get("failure_pattern") in ("C", "D", "E")
        or r.get("integrated_verdict") in ("ONTOLOGY_DRIFT", "SYNTHESIS_COLLAPSE")
    )

    coherence_values = [float(r.get("narrative_coherence", 0.0)) for r in results]

    return {
        "event_count": total,
        "verdict_distribution": dict(verdicts),
        "root_cause_distribution": dict(root_causes),
        "perception_accuracy": round(s1_confirmed / total, 4),
        "reasoning_accuracy": round(s2_confirmed / total, 4),
        "cross_stage_alignment": round(high_alignment / total, 4),
        "confidence_realism": round(good_confidence / total, 4),
        "contradiction_propagation": round(cascades / total, 4),
        "synthesis_integrity": round(
            sum(1 for r in results if r.get("stage2_verdict") in ("CONFIRMED", "PARTIAL")) / total,
            4,
        ),
        "narrative_stability": round(sum(coherence_values) / total, 4),
        "ontology_coherence": round(
            (fully_confirmed + verdicts.get("PARTIAL_CONFIRMATION", 0) * 0.5) / total,
            4,
        ),
        "market_confirmation_rate": round(
            sum(1 for r in results if r.get("market_verdict") == "CONFIRMED") / total,
            4,
        ),
        "cognition_drift_frequency": round(drift_signals / total, 4),
        "fully_confirmed_rate": round(fully_confirmed / total, 4),
    }


def analyze_cognition_drift(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Rolling cognition health from integrated chain results."""

    if not results:
        return {"status": "NO_DATA", "health": "UNKNOWN", "signals": []}

    total = len(results)
    overconfident = sum(1 for r in results if r.get("confidence_realism") == "POOR")
    contradictions = sum(1 for r in results if r.get("contradiction_level") == "HIGH")
    misaligned = sum(1 for r in results if r.get("alignment_level") == "LOW")
    perception_failures = sum(1 for r in results if r.get("stage1_verdict") in ("FAILED", "FALSE POSITIVE"))
    reasoning_failures = sum(
        1 for r in results if r.get("stage2_verdict") in ("FAILED", "FALSE_NARRATIVE", "OVERCONFIDENT")
    )

    signals: list[str] = []
    if overconfident / total >= 0.4:
        signals.append("confidence inflation")
    if contradictions / total >= 0.3:
        signals.append("increasing contradictions")
    if misaligned / total >= 0.4:
        signals.append("narrative degradation")
    if perception_failures / total >= 0.4:
        signals.append("ontology fragmentation (perception)")
    if reasoning_failures / total >= 0.4:
        signals.append("transition instability (reasoning)")

    if len(signals) >= 3:
        health = "DEGRADED"
    elif len(signals) >= 1:
        health = "WATCH"
    else:
        health = "STABLE"

    return {
        "status": "OK",
        "health": health,
        "signals": signals,
        "overconfident_rate": round(overconfident / total, 4),
        "contradiction_rate": round(contradictions / total, 4),
        "misalignment_rate": round(misaligned / total, 4),
        "perception_failure_rate": round(perception_failures / total, 4),
        "reasoning_failure_rate": round(reasoning_failures / total, 4),
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "event_count": 0,
        "verdict_distribution": {},
        "root_cause_distribution": {},
        "perception_accuracy": 0.0,
        "reasoning_accuracy": 0.0,
        "cross_stage_alignment": 0.0,
        "confidence_realism": 0.0,
        "contradiction_propagation": 0.0,
        "synthesis_integrity": 0.0,
        "narrative_stability": 0.0,
        "ontology_coherence": 0.0,
        "market_confirmation_rate": 0.0,
        "cognition_drift_frequency": 0.0,
        "fully_confirmed_rate": 0.0,
    }
