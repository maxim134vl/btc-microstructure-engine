"""Aggregate Stage 2.5 validation statistics by state and overall."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

PHASE1_STATES = (
    "IC_CONTINUATION_WEAKENING",
    "IC_INITIATIVE_DETERIORATION",
    "IC_ROTATIONAL_PRESSURE",
)


def _state_metrics(events: list[dict[str, Any]]) -> dict[str, float]:
    if not events:
        return {
            "precision": 0.0,
            "confirmation_rate": 0.0,
            "false_positive_rate": 0.0,
            "early_warning_rate": 0.0,
            "average_horizon_to_confirmation": 0.0,
            "partial_rate": 0.0,
            "failed_rate": 0.0,
        }

    total = len(events)
    confirmed = sum(1 for e in events if e["verdict"] == "CONFIRMED")
    partial = sum(1 for e in events if e["verdict"] == "PARTIAL")
    failed = sum(1 for e in events if e["verdict"] == "FAILED")
    false_pos = sum(1 for e in events if e["verdict"] == "FALSE_POSITIVE" or e.get("false_positive"))
    early = sum(1 for e in events if e["verdict"] == "EARLY_WARNING" or e.get("early_warning"))

    horizons = [
        float(e["confirmation_horizon"])
        for e in events
        if e.get("confirmation_horizon") is not None and e["verdict"] in ("CONFIRMED", "EARLY_WARNING", "PARTIAL")
    ]

    positive_calls = confirmed + false_pos
    precision = confirmed / positive_calls if positive_calls else 0.0

    return {
        "precision": round(precision, 4),
        "confirmation_rate": round(confirmed / total, 4),
        "false_positive_rate": round(false_pos / total, 4),
        "early_warning_rate": round(early / total, 4),
        "average_horizon_to_confirmation": round(sum(horizons) / len(horizons), 2) if horizons else 0.0,
        "partial_rate": round(partial / total, 4),
        "failed_rate": round(failed / total, 4),
    }


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "event_count": 0,
            "verdict_distribution": {},
            "by_state": {},
            "precision": 0.0,
            "confirmation_rate": 0.0,
            "false_positive_rate": 0.0,
            "early_warning_rate": 0.0,
            "average_horizon_to_confirmation": 0.0,
            "narrative_confirmation_rate": 0.0,
        }

    verdicts = Counter(r["verdict"] for r in results)
    total = len(results)

    by_state: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[str(row.get("intermediate_state"))].append(row)

    for state in PHASE1_STATES:
        by_state[state] = {
            "event_count": len(grouped[state]),
            **_state_metrics(grouped[state]),
            "verdict_distribution": dict(Counter(r["verdict"] for r in grouped[state])),
        }

    overall = _state_metrics(results)
    narrative_hits = sum(1 for r in results if r["verdict"] in ("CONFIRMED", "EARLY_WARNING", "PARTIAL"))

    return {
        "event_count": total,
        "verdict_distribution": dict(verdicts),
        "by_state": by_state,
        **overall,
        "narrative_confirmation_rate": round(narrative_hits / total, 4),
    }
