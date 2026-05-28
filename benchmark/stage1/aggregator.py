"""Aggregate cognitive validation statistics."""

from __future__ import annotations

from collections import Counter
from typing import Any


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "event_count": 0,
            "verdict_distribution": {},
            "initiative_accuracy": 0.0,
            "climax_confirmation_rate": 0.0,
            "stopping_quality_rate": 0.0,
            "transition_stability": 0.0,
            "probabilistic_consistency": 0.0,
            "false_positive_rate": 0.0,
            "confirmed_rate": 0.0,
            "follow_through_strong_rate": 0.0,
            "market_structure_coherence": 0.0,
        }

    verdicts = Counter(r["verdict"] for r in results)
    total = len(results)
    confirmed = verdicts.get("CONFIRMED", 0)
    false_pos = sum(1 for r in results if r.get("false_positive"))

    climax_events = [r for r in results if _is_climax(r)]
    stopping_events = [r for r in results if _is_stopping(r)]
    initiative_events = [r for r in results if r.get("bias_source") == "delta"]

    strong_ft = sum(
        1 for r in results if r.get("outcome", {}).get("follow_through") == "STRONG"
    )

    return {
        "event_count": total,
        "verdict_distribution": dict(verdicts),
        "initiative_accuracy": _rate(initiative_events, "CONFIRMED"),
        "climax_confirmation_rate": _rate(climax_events, "CONFIRMED"),
        "stopping_quality_rate": _rate(stopping_events, "CONFIRMED"),
        "transition_stability": _rate(
            [r for r in results if r.get("context", {}).get("transition_state")],
            "CONFIRMED",
        ),
        "probabilistic_consistency": _rate(
            [r for r in results if "Regime:" in r.get("interpretation", "")],
            "CONFIRMED",
        ),
        "false_positive_rate": round(false_pos / total, 4),
        "confirmed_rate": round(confirmed / total, 4),
        "follow_through_strong_rate": round(strong_ft / total, 4),
        "market_structure_coherence": round(
            (confirmed + verdicts.get("PARTIAL", 0) * 0.5) / total,
            4,
        ),
    }


def _rate(events: list[dict[str, Any]], verdict: str) -> float:
    if not events:
        return 0.0
    hits = sum(1 for e in events if e["verdict"] == verdict)
    return round(hits / len(events), 4)


def _is_climax(row: dict[str, Any]) -> bool:
    ctx = row.get("context", {})
    text = row.get("interpretation", "").lower()
    return any(
        x in text or str(ctx.get(k, "")).upper().find("CLIMAX") >= 0
        for k, x in [("climax_state", "climax"), ("trigger_event", "climax")]
    )


def _is_stopping(row: dict[str, Any]) -> bool:
    ctx = row.get("context", {})
    return (
        str(ctx.get("volume_event", "")) == "STOPPING_VOLUME"
        or "stopping" in row.get("interpretation", "").lower()
    )
