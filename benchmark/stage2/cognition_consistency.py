"""Detect internal contradictions in Stage 2 reasoning."""

from __future__ import annotations

from typing import Any

import pandas as pd

CLIMAX_TRIGGERS = {"BUYING_CLIMAX", "SELLING_CLIMAX"}
EXHAUSTION_SYNTHESIS = {"LOCAL_EXHAUSTION", "INTERMEDIATE_REVERSAL", "STRUCTURAL_REVERSAL"}
BULLISH_REGIMES = {"ABSORPTION_RECOVERY", "ABSORPTION_REGIME"}
BEARISH_REGIMES = {"DISTRIBUTION_REGIME"}


def _parse_flags(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text or text in ("{}", "[]", "nan", "None"):
        return []
    if text.startswith("{"):
        return [part.strip().strip('"').strip("'") for part in text.replace("{", "").replace("}", "").split(",") if part.strip()]
    return [text]


def analyze_consistency(row: pd.Series) -> dict[str, Any]:
    issues: list[str] = []
    score = 0.0

    trigger = str(row.get("trigger_event") or "")
    synthesis = str(row.get("synthesis_state") or "")
    regime = str(row.get("auction_regime") or row.get("regime_state") or "")
    delta = row.get("delta")
    rank = str(row.get("structural_rank") or "")
    persistence = str(row.get("persistence") or "")

    if trigger in CLIMAX_TRIGGERS and synthesis not in EXHAUSTION_SYNTHESIS:
        issues.append("climax trigger without exhaustion/reversal synthesis")
        score += 0.35

    if trigger == "BUYING_CLIMAX" and regime in BULLISH_REGIMES:
        issues.append("bullish regime during buyer climax")
        score += 0.4

    if trigger == "SELLING_CLIMAX" and regime in BEARISH_REGIMES:
        issues.append("bearish regime during seller climax")
        score += 0.4

    if synthesis == "STRUCTURAL_REVERSAL" and rank == "LOW":
        issues.append("structural reversal claim with low structural rank")
        score += 0.25

    if synthesis == "LOCAL_EXHAUSTION" and persistence in ("H1_CONFIRMED", "M30_CONFIRMED"):
        issues.append("local exhaustion with high persistence label")
        score += 0.2

    if pd.notna(delta):
        if trigger == "BUYING_CLIMAX" and float(delta) > 0 and synthesis == "LOCAL_EXHAUSTION":
            pass
        elif trigger == "BUYING_CLIMAX" and float(delta) > 0 and "REVERSAL" not in synthesis:
            issues.append("buyer initiative persists without reversal framing")
            score += 0.15

    flags = _parse_flags(row.get("contradiction_flags"))
    clusters = _parse_flags(row.get("contradiction_clusters"))
    if flags:
        issues.extend(flags[:3])
        score += min(0.3, 0.1 * len(flags))

    if clusters:
        issues.append(f"contradiction cluster: {clusters[0]}")
        score += 0.15

    score = min(1.0, round(score, 3))
    if score >= 0.55:
        level = "HIGH"
    elif score >= 0.25:
        level = "MODERATE"
    else:
        level = "LOW"

    return {
        "contradiction_score": score,
        "contradiction_level": level,
        "contradiction_issues": issues,
        "internally_consistent": score < 0.25,
    }
