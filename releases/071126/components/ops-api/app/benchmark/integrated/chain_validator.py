"""Validate complete cognition chains end-to-end."""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchmark.integrated.confidence_realism import analyze_confidence_realism
from benchmark.integrated.contradiction_chain import analyze_contradiction_chain
from benchmark.integrated.cross_stage_validator import validate_cross_stage
from benchmark.integrated.outcome_validator import validate_outcome
from benchmark.integrated.perception_reasoning_alignment import analyze_alignment
from benchmark.stage1.event_extractor import event_to_interpretation
from benchmark.stage1.forward_validator import _detect_bias, _score_verdict
from benchmark.stage2.cognition_consistency import analyze_consistency
from benchmark.stage2.context_integrity import analyze_context_integrity
from benchmark.stage2.probabilistic_validator import validate_probabilistic
from benchmark.stage2.synthesis_validator import validate_synthesis
from benchmark.stage2.validator import _combine_verdict


def _validate_stage1_perception(row: pd.Series, outcome: dict[str, Any]) -> dict[str, Any]:
    bias_spec = _detect_bias(row)
    interpretation = event_to_interpretation(row)

    if bias_spec is None:
        verdict, false_positive, note = "PARTIAL", False, "No explicit Stage 1 bias to validate."
    else:
        delta = float(row["delta"]) if pd.notna(row.get("delta")) else None
        verdict, false_positive, note = _score_verdict(bias_spec["bias"], outcome, delta)

    return {
        "stage1_verdict": verdict,
        "stage1_interpretation": interpretation,
        "stage1_note": note,
        "stage1_false_positive": false_positive,
    }


def validate_integrated_chains(chains: list[dict[str, Any]], *, horizon: int = 11) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for chain in chains:
        row = chain["row"]
        outcome_result = validate_outcome(row, horizon=horizon)
        outcome = outcome_result["outcome"]

        stage1 = _validate_stage1_perception(row, outcome)
        synthesis = validate_synthesis(row, horizon=horizon)
        context = analyze_context_integrity(row)
        consistency = analyze_consistency(row)
        probabilistic = validate_probabilistic(row, outcome)
        stage2_verdict, stage2_note = _combine_verdict(
            synthesis["synthesis_verdict"],
            probabilistic["confidence_quality"],
            consistency["contradiction_level"],
            context["context_integrity"],
            str(row.get("synthesis_state")) if pd.notna(row.get("synthesis_state")) else None,
        )

        alignment = analyze_alignment(row, stage1["stage1_verdict"])
        confidence = analyze_confidence_realism(
            row,
            outcome,
            stage1_verdict=stage1["stage1_verdict"],
            stage2_verdict=stage2_verdict,
        )
        contradiction = analyze_contradiction_chain(
            row,
            stage1_verdict=stage1["stage1_verdict"],
            alignment_level=alignment["alignment_level"],
        )

        cross = validate_cross_stage(
            stage1_verdict=stage1["stage1_verdict"],
            stage2_verdict=stage2_verdict,
            market_verdict=outcome_result["market_verdict"],
            confidence_realism=confidence["confidence_realism"],
            alignment_level=alignment["alignment_level"],
            contradiction_level=contradiction["contradiction_level"],
            contradiction_propagation=contradiction["contradiction_propagation"],
            context_integrity=context["context_integrity"],
            narrative_coherence=float(synthesis.get("narrative_coherence", 0.0)),
        )

        results.append(
            {
                "event_index": chain["event_index"],
                "timestamp": chain["timestamp"],
                "stage1_perception": chain["stage1_perception"],
                "stage1_perception_text": chain["stage1_perception_text"],
                "stage1_verdict": stage1["stage1_verdict"],
                "stage1_note": stage1["stage1_note"],
                "stage2_interpretation": chain["stage2_interpretation"],
                "stage2_verdict": stage2_verdict,
                "stage2_note": stage2_note,
                "observed_outcome": outcome_result["observed_outcome"],
                "market_verdict": outcome_result["market_verdict"],
                "integrated_verdict": cross["integrated_verdict"],
                "integrated_note": cross["integrated_note"],
                "root_cause": cross["root_cause"],
                "failure_pattern": cross["failure_pattern"],
                "failure_pattern_note": cross["failure_pattern_note"],
                "confidence_realism": confidence["confidence_realism"],
                "confidence_quality": confidence["confidence_quality"],
                "confidence_score": confidence["confidence_score"],
                "confidence_note": confidence["confidence_note"],
                "narrative_coherence": synthesis["narrative_coherence"],
                "narrative_coherence_label": cross["narrative_coherence_label"],
                "alignment_score": alignment["alignment_score"],
                "alignment_level": alignment["alignment_level"],
                "alignment_note": alignment["alignment_note"],
                "used_stage1_correctly": alignment["used_stage1_correctly"],
                "contradiction_score": contradiction["contradiction_score"],
                "contradiction_level": contradiction["contradiction_level"],
                "contradiction_propagation": contradiction["contradiction_propagation"],
                "contradiction_issues": contradiction["contradiction_issues"],
                "context_integrity": context["context_integrity"],
                "outcome": outcome,
                "context": chain["context"],
            }
        )

    return results
