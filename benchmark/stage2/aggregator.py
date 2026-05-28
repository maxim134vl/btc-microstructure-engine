"""Aggregate Stage 2 reasoning validation statistics."""

from __future__ import annotations

from collections import Counter
from typing import Any


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "event_count": 0,
            "verdict_distribution": {},
            "reasoning_accuracy": 0.0,
            "probabilistic_calibration_quality": 0.0,
            "contradiction_frequency": 0.0,
            "synthesis_stability": 0.0,
            "narrative_coherence": 0.0,
            "confidence_drift": 0.0,
            "regime_interpretation_accuracy": 0.0,
            "transition_logic_quality": 0.0,
            "overconfident_rate": 0.0,
            "context_failure_rate": 0.0,
        }

    verdicts = Counter(r["verdict"] for r in results)
    total = len(results)

    accurate_conf = sum(1 for r in results if r.get("confidence_quality") == "ACCURATE")
    overconf = sum(1 for r in results if r.get("confidence_quality") == "OVERCONFIDENT")
    high_contradiction = sum(1 for r in results if r.get("contradiction_level") == "HIGH")
    context_failures = sum(1 for r in results if r.get("context_integrity") == "CONTEXT_FAILURE")
    confirmed = sum(1 for r in results if r["verdict"] == "CONFIRMED")
    regime_hits = sum(
        1
        for r in results
        if r.get("bias_source") == "auction_regime" and r["verdict"] in ("CONFIRMED", "PARTIAL")
    )
    regime_events = sum(1 for r in results if r.get("bias_source") == "auction_regime")
    transition_hits = sum(
        1 for r in results if r.get("transition_state") and r["verdict"] in ("CONFIRMED", "PARTIAL")
    )
    transition_events = sum(1 for r in results if r.get("transition_state"))

    coherence_values = [float(r.get("narrative_coherence", 0.0)) for r in results]

    return {
        "event_count": total,
        "verdict_distribution": dict(verdicts),
        "reasoning_accuracy": round(confirmed / total, 4),
        "probabilistic_calibration_quality": round(accurate_conf / total, 4),
        "contradiction_frequency": round(high_contradiction / total, 4),
        "synthesis_stability": round(
            sum(1 for r in results if r.get("synthesis_verdict") == "CONFIRMED") / total,
            4,
        ),
        "narrative_coherence": round(sum(coherence_values) / total, 4),
        "confidence_drift": round(overconf / total, 4),
        "regime_interpretation_accuracy": round(regime_hits / regime_events, 4) if regime_events else 0.0,
        "transition_logic_quality": round(transition_hits / transition_events, 4) if transition_events else 0.0,
        "overconfident_rate": round(overconf / total, 4),
        "context_failure_rate": round(context_failures / total, 4),
    }
