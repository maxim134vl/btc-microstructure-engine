"""Validate IC_INITIATIVE_DETERIORATION against forward market evolution."""

from __future__ import annotations

from typing import Any


def validate_horizon(context: dict[str, Any]) -> dict[str, Any]:
    delta = context["delta"]
    forward = context["forward"]
    baseline = context["baseline"]

    if context["forward_candles"] < max(2, context["horizon"] // 4):
        return {
            "verdict": "PARTIAL",
            "false_positive": False,
            "early_warning": False,
            "note": "Insufficient forward candles for full horizon evaluation.",
            "signals": [],
        }

    weaken_signals = 0
    notes: list[str] = []

    if delta["initiative_strength"] <= -35:
        weaken_signals += 1
        notes.append("initiative strength declined")
    if delta["initiative_dominance"] <= -0.1:
        weaken_signals += 1
        notes.append("directional dominance faded")
    if forward["initiative_dominance"] <= baseline["initiative_dominance"] * 0.8:
        weaken_signals += 1
        notes.append("participation remained subdued")

    strengthen = 0
    if delta["initiative_strength"] >= 50 and delta["initiative_dominance"] >= 0.12:
        strengthen += 1
    if forward["initiative_dominance"] >= max(baseline["initiative_dominance"] * 1.15, 0.55):
        strengthen += 1

    if weaken_signals >= 2:
        return {
            "verdict": "CONFIRMED",
            "false_positive": False,
            "early_warning": False,
            "note": "; ".join(notes),
            "signals": notes,
        }

    if strengthen >= 2:
        return {
            "verdict": "FALSE_POSITIVE",
            "false_positive": True,
            "early_warning": False,
            "note": "Initiative strengthened contrary to deterioration narrative.",
            "signals": notes,
        }

    if weaken_signals >= 1:
        return {
            "verdict": "PARTIAL",
            "false_positive": False,
            "early_warning": False,
            "note": "; ".join(notes) or "Partial initiative weakening.",
            "signals": notes,
        }

    return {
        "verdict": "FAILED",
        "false_positive": False,
        "early_warning": False,
        "note": "No initiative deterioration observed forward.",
        "signals": [],
    }
