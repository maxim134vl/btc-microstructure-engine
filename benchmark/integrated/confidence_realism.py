"""Integrated confidence realism analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchmark.stage2.probabilistic_validator import validate_probabilistic


def analyze_confidence_realism(
    row: pd.Series,
    outcome: dict[str, Any],
    *,
    stage1_verdict: str,
    stage2_verdict: str,
) -> dict[str, Any]:
    probabilistic = validate_probabilistic(row, outcome)
    quality = probabilistic["confidence_quality"]
    score = probabilistic.get("confidence_score")

    if quality == "OVERCONFIDENT":
        realism = "POOR"
        note = "Confidence exceeded what forward market behavior justified."
    elif quality == "UNDERCONFIDENT":
        realism = "CONSERVATIVE"
        note = "Confidence was lower than market confirmation warranted."
    elif quality == "ACCURATE":
        realism = "GOOD"
        note = "Confidence appropriately matched market outcome."
    elif stage1_verdict == "CONFIRMED" and stage2_verdict in ("FAILED", "FALSE_NARRATIVE"):
        realism = "POOR"
        note = "Reasoning failed despite valid perception — confidence miscalibrated."
    else:
        realism = "NEUTRAL"
        note = probabilistic["calibration_note"]

    if score is not None and score >= 0.85 and stage2_verdict in ("PARTIAL", "FAILED", "OVERCONFIDENT"):
        realism = "POOR"
        note = f"High confidence ({score:.0%}) not supported by integrated chain outcome."

    return {
        "confidence_quality": quality,
        "confidence_realism": realism,
        "confidence_score": score,
        "confidence_note": note,
        **probabilistic,
    }
