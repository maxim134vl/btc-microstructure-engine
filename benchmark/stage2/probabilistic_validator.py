"""Validate Stage 2 confidence and probabilistic calibration."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _confidence_value(row: pd.Series) -> float | None:
    for column in ("disciplined_conviction", "conviction_probability", "regime_confidence"):
        value = row.get(column)
        if pd.notna(value):
            return float(value)
    return None


def _expected_direction(row: pd.Series) -> str | None:
    distribution = row.get("distribution_probability")
    if pd.notna(distribution) and float(distribution) >= 0.55:
        return "down"
    absorption = row.get("absorption_probability")
    if pd.notna(absorption) and float(absorption) >= 0.55:
        return "up"
    regime = str(row.get("auction_regime") or row.get("regime_state") or "")
    if regime == "DISTRIBUTION_REGIME":
        return "down"
    if regime in ("ABSORPTION_RECOVERY", "ABSORPTION_REGIME"):
        return "up"
    synthesis = str(row.get("synthesis_state") or "")
    if synthesis in ("LOCAL_EXHAUSTION",):
        return "down"
    if synthesis in ("INTERMEDIATE_REVERSAL", "STRUCTURAL_REVERSAL"):
        return "reversal"
    return None


def validate_probabilistic(row: pd.Series, outcome: dict[str, Any]) -> dict[str, Any]:
    confidence = _confidence_value(row)
    expected = _expected_direction(row)
    move = outcome.get("move_pct", 0.0) / 100.0
    direction = outcome.get("direction", "flat")

    if confidence is None:
        return {
            "confidence_quality": "UNKNOWN",
            "confidence_score": None,
            "calibration_note": "No probabilistic confidence exported at event time.",
        }

    aligned = False
    if expected == "down":
        aligned = move <= -0.003 or direction == "down"
    elif expected == "up":
        aligned = move >= 0.003 or direction == "up"
    elif expected == "reversal":
        aligned = abs(move) >= 0.003
    else:
        aligned = abs(move) <= 0.015

    high_conf = confidence >= 0.7
    moderate_conf = confidence >= 0.45

    if high_conf and not aligned:
        quality = "OVERCONFIDENT"
        note = f"High confidence ({confidence:.0%}) contradicted by forward market."
    elif high_conf and aligned:
        quality = "ACCURATE"
        note = f"High confidence ({confidence:.0%}) matched market confirmation."
    elif moderate_conf and aligned:
        quality = "ACCURATE"
        note = f"Moderate confidence ({confidence:.0%}) appropriately calibrated."
    elif not moderate_conf and aligned and abs(move) >= 0.008:
        quality = "UNDERCONFIDENT"
        note = f"Confidence ({confidence:.0%}) was low relative to strong follow-through."
    elif not aligned:
        quality = "MISCALIBRATED"
        note = f"Confidence ({confidence:.0%}) did not match observed behavior."
    else:
        quality = "NEUTRAL"
        note = "Confidence level broadly consistent with weak follow-through."

    return {
        "confidence_quality": quality,
        "confidence_score": round(confidence, 4),
        "calibration_note": note,
        "expected_direction": expected,
        "confidence_aligned": aligned,
    }
