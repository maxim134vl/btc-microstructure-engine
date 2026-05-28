"""Analyze contradiction propagation across cognition chain."""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchmark.stage2.cognition_consistency import analyze_consistency


def analyze_contradiction_chain(
    row: pd.Series,
    *,
    stage1_verdict: str,
    alignment_level: str,
) -> dict[str, Any]:
    consistency = analyze_consistency(row)
    issues = list(consistency.get("contradiction_issues") or [])
    score = float(consistency.get("contradiction_score", 0.0))

    if stage1_verdict == "FALSE POSITIVE":
        issues.append("stage1 false positive propagated into reasoning chain")
        score = min(1.0, score + 0.2)

    if alignment_level == "LOW":
        issues.append("perception-reasoning misalignment")
        score = min(1.0, score + 0.25)

    flags = row.get("contradiction_flags")
    if pd.notna(flags) and str(flags) not in ("{}", "[]", "nan", ""):
        issues.append("probabilistic contradiction flags present")

    if score >= 0.55:
        propagation = "CASCADE"
        level = "HIGH"
    elif score >= 0.25:
        propagation = "PARTIAL"
        level = "MODERATE"
    else:
        propagation = "NONE"
        level = "LOW"

    return {
        "contradiction_score": round(score, 3),
        "contradiction_level": level,
        "contradiction_propagation": propagation,
        "contradiction_issues": issues,
        "contradiction_cascade": propagation == "CASCADE",
    }
