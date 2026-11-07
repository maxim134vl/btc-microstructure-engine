"""Combine Stage 2 validation modules into per-event verdicts."""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchmark.stage2.cognition_consistency import analyze_consistency
from benchmark.stage2.context_integrity import analyze_context_integrity
from benchmark.stage2.probabilistic_validator import validate_probabilistic
from benchmark.stage2.reasoning_extractor import reasoning_context
from benchmark.stage2.synthesis_validator import validate_synthesis


def _combine_verdict(
    synthesis_verdict: str,
    confidence_quality: str,
    contradiction_level: str,
    context_integrity: str,
    synthesis_state: str | None,
) -> tuple[str, str]:
    if contradiction_level == "HIGH":
        return "CONTRADICTORY", "Internal reasoning conflicts detected."

    if context_integrity == "CONTEXT_FAILURE":
        return "CONTEXT_FAILURE", "Stage 2 narrative poorly supported by Stage 1 inputs."

    if confidence_quality == "OVERCONFIDENT" and synthesis_verdict in ("FAILED", "FALSE_NARRATIVE"):
        return "OVERCONFIDENT", "High confidence reasoning contradicted by market."

    if confidence_quality == "UNDERCONFIDENT" and synthesis_verdict == "CONFIRMED":
        return "UNDERCONFIDENT", "Market confirmed narrative but confidence was too low."

    if synthesis_verdict == "FALSE_NARRATIVE":
        return "FALSE_NARRATIVE", "Stage 2 narrative contradicted by market behavior."

    if synthesis_verdict == "FAILED":
        if synthesis_state == "LOCAL_EXHAUSTION":
            return "NOISY_REASONING", "Local exhaustion narrative may have overfit noise."
        return "FAILED", synthesis_verdict

    if synthesis_verdict == "PARTIAL":
        return "PARTIAL", "Partial market confirmation of Stage 2 reasoning."

    if synthesis_verdict == "CONFIRMED":
        return "CONFIRMED", "Stage 2 reasoning confirmed by forward market behavior."

    return "PARTIAL", "Incomplete reasoning validation."


def validate_reasoning_events(events: pd.DataFrame, *, horizon: int = 11) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for _, row in events.iterrows():
        synthesis = validate_synthesis(row, horizon=horizon)
        outcome = synthesis["outcome"]
        probabilistic = validate_probabilistic(row, outcome)
        consistency = analyze_consistency(row)
        context = analyze_context_integrity(row)

        verdict, note = _combine_verdict(
            synthesis["synthesis_verdict"],
            probabilistic["confidence_quality"],
            consistency["contradiction_level"],
            context["context_integrity"],
            str(row.get("synthesis_state")) if pd.notna(row.get("synthesis_state")) else None,
        )

        bias_spec = synthesis["bias_spec"]
        results.append(
            {
                "event_index": int(row.get("event_index", 0)),
                "timestamp": str(row["timestamp"]),
                "stage1_inputs": row.get("stage1_inputs", []),
                "stage2_interpretation": row.get("stage2_interpretation"),
                "observed_outcome": synthesis["observed_outcome"],
                "verdict": verdict,
                "validation_note": note,
                "synthesis_verdict": synthesis["synthesis_verdict"],
                "confidence_quality": probabilistic["confidence_quality"],
                "confidence_score": probabilistic["confidence_score"],
                "calibration_note": probabilistic["calibration_note"],
                "narrative_coherence": synthesis["narrative_coherence"],
                "contradiction_score": consistency["contradiction_score"],
                "contradiction_level": consistency["contradiction_level"],
                "contradiction_issues": consistency["contradiction_issues"],
                "context_integrity": context["context_integrity"],
                "context_score": context["context_score"],
                "context_note": context["context_note"],
                "bias_source": bias_spec.get("source"),
                "bias_label": bias_spec.get("narrative"),
                "transition_state": row.get("transition_state"),
                "outcome": outcome,
                "context": reasoning_context(row),
            }
        )

    return results
