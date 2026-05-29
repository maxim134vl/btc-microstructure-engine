"""Validate IC_CONTINUATION_WEAKENING against forward market evolution."""

from __future__ import annotations

from typing import Any


def _confirmation_signals(context: dict[str, Any]) -> tuple[int, list[str]]:
    delta = context["delta"]
    forward = context["forward"]
    baseline = context["baseline"]
    notes: list[str] = []
    signals = 0

    if delta["continuation_quality"] <= -0.08:
        signals += 1
        notes.append("continuation quality declined")
    elif forward["continuation_quality"] <= 0.45:
        signals += 1
        notes.append("continuation quality remained weak")

    if delta["directional_efficiency"] <= -0.015:
        signals += 1
        notes.append("directional efficiency deteriorated")
    elif forward["directional_efficiency"] < baseline["directional_efficiency"] * 0.85:
        signals += 1
        notes.append("directional efficiency below baseline")

    if delta["initiative_strength"] <= -40:
        signals += 1
        notes.append("initiative strength weakened")
    elif delta["initiative_dominance"] <= -0.08:
        signals += 1
        notes.append("directional participation declined")

    return signals, notes


def _resumption_signals(context: dict[str, Any]) -> tuple[int, list[str]]:
    delta = context["delta"]
    forward = context["forward"]
    notes: list[str] = []
    signals = 0

    if delta["continuation_quality"] >= 0.12 and forward["continuation_quality"] >= 0.65:
        signals += 1
        notes.append("efficient continuation resumed")
    if delta["directional_efficiency"] >= 0.02 and forward["directional_efficiency"] >= 0.08:
        signals += 1
        notes.append("directional efficiency recovered")
    if delta["initiative_dominance"] >= 0.12 and forward["initiative_dominance"] >= 0.55:
        signals += 1
        notes.append("initiative dominance returned")

    return signals, notes


def validate_horizon(context: dict[str, Any]) -> dict[str, Any]:
    """Score a single horizon for continuation weakening narrative."""

    if context["forward_candles"] < max(2, context["horizon"] // 4):
        return {
            "verdict": "PARTIAL",
            "false_positive": False,
            "early_warning": False,
            "note": "Insufficient forward candles for full horizon evaluation.",
            "signals": [],
        }

    confirm, confirm_notes = _confirmation_signals(context)
    resume, resume_notes = _resumption_signals(context)

    if confirm >= 2 and resume == 0:
        return {
            "verdict": "CONFIRMED",
            "false_positive": False,
            "early_warning": False,
            "note": "; ".join(confirm_notes),
            "signals": confirm_notes,
        }

    if resume >= 2:
        return {
            "verdict": "FAILED",
            "false_positive": False,
            "early_warning": False,
            "note": "Continuation resumed contrary to weakening narrative: " + "; ".join(resume_notes),
            "signals": resume_notes,
        }

    if confirm >= 1:
        return {
            "verdict": "PARTIAL",
            "false_positive": False,
            "early_warning": False,
            "note": "; ".join(confirm_notes) or "Weak continuation deterioration.",
            "signals": confirm_notes,
        }

    return {
        "verdict": "FAILED",
        "false_positive": False,
        "early_warning": False,
        "note": "No forward deterioration after continuation weakening call.",
        "signals": [],
    }
