"""Validate Stage 1 inputs support Stage 2 conclusions."""

from __future__ import annotations

from typing import Any

import pandas as pd

SUPPORT_MAP: dict[str, set[str]] = {
    "LOCAL_EXHAUSTION": {"climax", "buying climax", "selling climax", "exhaustion", "buyer initiative", "seller initiative"},
    "INTERMEDIATE_REVERSAL": {"climax", "buying climax", "selling climax", "stopping", "reversal", "stopping volume"},
    "STRUCTURAL_REVERSAL": {"climax", "buying climax", "selling climax", "stopping", "reversal", "structural"},
}


def analyze_context_integrity(row: pd.Series) -> dict[str, Any]:
    inputs = row.get("stage1_inputs") or []
    if isinstance(inputs, str):
        inputs = [inputs]
    normalized = {str(item).lower() for item in inputs}
    synthesis = str(row.get("synthesis_state") or "")

    if not normalized:
        return {
            "context_integrity": "UNKNOWN",
            "context_score": 0.5,
            "context_note": "No Stage 1 inputs attached to reasoning event.",
        }

    if not synthesis:
        return {
            "context_integrity": "UNKNOWN",
            "context_score": 0.5,
            "context_note": "No Stage 2 synthesis to validate against inputs.",
        }

    expected = SUPPORT_MAP.get(synthesis, set())
    if not expected:
        overlap = len(normalized)
        score = min(1.0, overlap / 3.0)
        return {
            "context_integrity": "PARTIAL" if score >= 0.4 else "WEAK",
            "context_score": round(score, 3),
            "context_note": "Generic input context present.",
        }

    hits = normalized & expected
    score = len(hits) / max(len(expected), 1)
    trigger = str(row.get("trigger_event") or "").replace("_", " ").lower()
    if trigger and trigger in normalized:
        score = min(1.0, score + 0.2)

    if score >= 0.5:
        integrity = "HIGH"
        note = "Stage 1 observations support Stage 2 synthesis."
    elif score >= 0.25:
        integrity = "PARTIAL"
        note = "Stage 1 inputs partially support Stage 2 narrative."
    else:
        integrity = "CONTEXT_FAILURE"
        note = "Stage 2 reasoning weakly connected to Stage 1 observations."

    return {
        "context_integrity": integrity,
        "context_score": round(score, 3),
        "context_note": note,
        "supporting_inputs": sorted(hits),
    }
