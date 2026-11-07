"""Validate IC_ROTATIONAL_PRESSURE against forward market evolution."""

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

    rotation_signals = 0
    notes: list[str] = []

    if delta["sign_flips"] >= 0.08:
        rotation_signals += 1
        notes.append("sign alternation increased")
    elif forward["sign_flips"] >= 0.35:
        rotation_signals += 1
        notes.append("two-sided delta behavior persisted")

    if delta["directional_persistence"] <= -0.12:
        rotation_signals += 1
        notes.append("directional persistence declined")
    elif forward["directional_persistence"] <= baseline["directional_persistence"] * 0.75:
        rotation_signals += 1
        notes.append("persistence remained low")

    if forward["initiative_dominance"] <= 0.45 and baseline["initiative_dominance"] >= 0.35:
        rotation_signals += 1
        notes.append("balanced two-sided auction behavior")

    trend_resume = 0
    if (
        forward["directional_persistence"] >= max(baseline["directional_persistence"] * 1.2, 0.55)
        and forward["initiative_dominance"] >= 0.6
        and delta["sign_flips"] <= 0
    ):
        trend_resume += 1
    if abs(forward["price_move"]) > abs(baseline["price_move"]) * 1.5 and forward["initiative_dominance"] >= 0.55:
        trend_resume += 1

    if rotation_signals >= 2:
        return {
            "verdict": "CONFIRMED",
            "false_positive": False,
            "early_warning": False,
            "note": "; ".join(notes),
            "signals": notes,
        }

    if trend_resume >= 1 and rotation_signals == 0:
        return {
            "verdict": "FALSE_POSITIVE",
            "false_positive": True,
            "early_warning": False,
            "note": "Directional continuation resumed — rotational call not supported.",
            "signals": notes,
        }

    if rotation_signals >= 1:
        return {
            "verdict": "PARTIAL",
            "false_positive": False,
            "early_warning": False,
            "note": "; ".join(notes) or "Partial rotational confirmation.",
            "signals": notes,
        }

    return {
        "verdict": "FAILED",
        "false_positive": False,
        "early_warning": False,
        "note": "No rotational behavior confirmation forward.",
        "signals": [],
    }
