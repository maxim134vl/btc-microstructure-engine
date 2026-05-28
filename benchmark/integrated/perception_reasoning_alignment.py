"""Measure alignment between Stage 1 perception and Stage 2 reasoning."""

from __future__ import annotations

from typing import Any

import pandas as pd

PERCEPTION_TO_SYNTHESIS: dict[str, set[str]] = {
    "buying climax": {"local_exhaustion", "intermediate_reversal", "structural_reversal"},
    "selling climax": {"local_exhaustion", "intermediate_reversal", "structural_reversal"},
    "climax": {"local_exhaustion", "intermediate_reversal", "structural_reversal"},
    "stopping": {"intermediate_reversal", "structural_reversal"},
    "stopping volume": {"intermediate_reversal", "structural_reversal"},
    "seller initiative": {"local_exhaustion", "intermediate_reversal"},
    "buyer initiative": {"local_exhaustion", "intermediate_reversal"},
}


def _normalize_inputs(inputs: list[str] | Any) -> set[str]:
    if not isinstance(inputs, list):
        return {str(inputs).lower()}
    return {str(item).lower() for item in inputs}


def analyze_alignment(row: pd.Series, stage1_verdict: str) -> dict[str, Any]:
    inputs = _normalize_inputs(row.get("stage1_inputs") or [])
    synthesis = str(row.get("synthesis_state") or "").replace("_", " ").lower()
    trigger = str(row.get("trigger_event") or "").replace("_", " ").lower()

    if not synthesis:
        return {
            "alignment_score": 0.0,
            "alignment_level": "UNKNOWN",
            "alignment_note": "No Stage 2 synthesis to align with perception.",
            "used_stage1_correctly": stage1_verdict in ("CONFIRMED", "PARTIAL"),
        }

    expected: set[str] = set()
    for item in inputs:
        expected |= PERCEPTION_TO_SYNTHESIS.get(item, set())
    if trigger:
        expected |= PERCEPTION_TO_SYNTHESIS.get(trigger, set())

    if not expected:
        score = 0.5 if synthesis else 0.0
        level = "PARTIAL" if score >= 0.4 else "LOW"
        return {
            "alignment_score": score,
            "alignment_level": level,
            "alignment_note": "Generic perception-to-reasoning linkage.",
            "used_stage1_correctly": score >= 0.4,
        }

    hit = synthesis in expected
    score = 1.0 if hit else 0.35 if any(part in synthesis for part in expected) else 0.15

    if hit and stage1_verdict == "CONFIRMED":
        level = "HIGH"
        note = "Stage 2 built coherent interpretation from Stage 1 perception."
    elif hit:
        level = "MEDIUM"
        note = "Reasoning aligned with perception though Stage 1 validation was weak."
    elif score >= 0.35:
        level = "MEDIUM"
        note = "Partial alignment between perception inputs and synthesis."
    else:
        level = "LOW"
        note = "Stage 2 synthesis poorly aligned with Stage 1 perception."

    return {
        "alignment_score": round(score, 3),
        "alignment_level": level,
        "alignment_note": note,
        "used_stage1_correctly": hit and stage1_verdict in ("CONFIRMED", "PARTIAL"),
    }
