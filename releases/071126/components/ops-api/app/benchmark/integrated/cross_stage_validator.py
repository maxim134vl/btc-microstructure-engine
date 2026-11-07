"""Cross-stage validation and integrated verdict assignment."""

from __future__ import annotations

from typing import Any

STAGE1_OK = {"CONFIRMED", "PARTIAL"}
STAGE1_BAD = {"FAILED", "FALSE POSITIVE"}
STAGE2_OK = {"CONFIRMED", "PARTIAL"}
STAGE2_BAD = {"FAILED", "FALSE_NARRATIVE", "OVERCONFIDENT", "CONTRADICTORY", "NOISY_REASONING", "CONTEXT_FAILURE"}


def _stage1_ok(verdict: str) -> bool:
    return verdict in STAGE1_OK


def _stage2_ok(verdict: str) -> bool:
    return verdict in STAGE2_OK


def classify_failure_pattern(
    *,
    stage1_verdict: str,
    stage2_verdict: str,
    confidence_realism: str,
    alignment_level: str,
    contradiction_level: str,
) -> tuple[str, str]:
    s1_ok = _stage1_ok(stage1_verdict)
    s2_ok = _stage2_ok(stage2_verdict)
    s1_bad = stage1_verdict in STAGE1_BAD
    s2_bad = stage2_verdict in STAGE2_BAD

    if s1_ok and s2_bad:
        if stage2_verdict == "OVERCONFIDENT" or confidence_realism == "POOR":
            return "C", "Stage 1 weak/correct but Stage 2 overconfident — confidence pathology."
        if stage2_verdict == "CONTRADICTORY" or contradiction_level == "HIGH":
            return "D", "Stage 1 correct but Stage 2 contradictory — synthesis instability."
        return "A", "Stage 1 correct, Stage 2 wrong — reasoning defect."

    if s1_bad and s2_ok:
        return "B", "Stage 1 wrong, Stage 2 correct — compensation artifact."

    if s1_bad and s2_bad:
        return "E", "Stage 1 wrong, Stage 2 wrong — ontology/perception collapse."

    if not s1_ok and confidence_realism == "POOR":
        return "C", "Weak perception with overconfident reasoning."

    if alignment_level == "LOW":
        return "D", "Perception-reasoning misalignment — synthesis instability."

    return "OK", "Cross-stage cognition chain coherent."


def assign_root_cause(
    *,
    failure_pattern: str,
    stage1_verdict: str,
    stage2_verdict: str,
    confidence_realism: str,
    alignment_level: str,
    contradiction_propagation: str,
    context_integrity: str,
) -> str:
    if failure_pattern == "E":
        return "ontology/perception collapse"
    if failure_pattern == "A":
        return "reasoning failure"
    if failure_pattern == "B":
        return "compensation artifact (Stage 2 corrected bad perception)"
    if failure_pattern == "C":
        return "confidence inflation"
    if failure_pattern == "D":
        return "synthesis instability"
    if stage1_verdict in STAGE1_BAD:
        return "perception failure"
    if stage2_verdict in STAGE2_BAD:
        return "reasoning failure"
    if confidence_realism == "POOR":
        return "confidence inflation"
    if context_integrity == "CONTEXT_FAILURE":
        return "context corruption"
    if contradiction_propagation == "CASCADE":
        return "contradiction cascade"
    if alignment_level == "LOW":
        return "ontology mismatch"
    return "none"


def assign_integrated_verdict(
    *,
    stage1_verdict: str,
    stage2_verdict: str,
    market_verdict: str,
    confidence_realism: str,
    alignment_level: str,
    contradiction_level: str,
    context_integrity: str,
    failure_pattern: str,
) -> tuple[str, str]:
    if failure_pattern == "E":
        return "ONTOLOGY_DRIFT", "Both perception and reasoning failed — ontology drift suspected."

    if context_integrity == "CONTEXT_FAILURE":
        return "CONTEXT_BREAKDOWN", "Stage 2 lost contextual integrity from Stage 1 inputs."

    if contradiction_level == "HIGH" or stage2_verdict == "CONTRADICTORY":
        return "CONTRADICTION_FAILURE", "Contradictions propagated through cognition chain."

    if stage2_verdict == "FALSE_NARRATIVE":
        return "FALSE_NARRATIVE", "Integrated narrative contradicted by market behavior."

    if confidence_realism == "POOR" or stage2_verdict == "OVERCONFIDENT":
        if _stage1_ok(stage1_verdict):
            return "CONFIDENCE_FAILURE", "Stage 1 perception valid but confidence/reasoning miscalibrated."
        return "CONFIDENCE_FAILURE", "Confidence exceeded market confirmation."

    if stage1_verdict in STAGE1_BAD and stage2_verdict in STAGE2_BAD:
        return "SYNTHESIS_COLLAPSE", "Full cognition chain collapsed."

    if stage1_verdict in STAGE1_BAD and _stage2_ok(stage2_verdict):
        return "PARTIAL_CONFIRMATION", "Reasoning compensated for perception weakness."

    if _stage1_ok(stage1_verdict) and stage2_verdict in STAGE2_BAD:
        return "REASONING_FAILURE", "Stage 1 perception correct but Stage 2 reasoning failed."

    if stage1_verdict in STAGE1_BAD:
        return "PERCEPTION_FAILURE", "Stage 1 perception failed."

    if stage2_verdict in STAGE2_BAD:
        return "REASONING_FAILURE", "Stage 2 reasoning failed."

    if (
        stage1_verdict == "CONFIRMED"
        and stage2_verdict == "CONFIRMED"
        and market_verdict == "CONFIRMED"
        and alignment_level == "HIGH"
        and confidence_realism in ("GOOD", "NEUTRAL", "CONSERVATIVE")
    ):
        return "FULLY_CONFIRMED", "Full cognition chain confirmed by market."

    if stage1_verdict in STAGE1_OK and stage2_verdict in STAGE2_OK:
        return "PARTIAL_CONFIRMATION", "Partial confirmation across perception, reasoning, and market."

    return "PARTIAL_CONFIRMATION", "Incomplete end-to-end cognition confirmation."


def validate_cross_stage(
    *,
    stage1_verdict: str,
    stage2_verdict: str,
    market_verdict: str,
    confidence_realism: str,
    alignment_level: str,
    contradiction_level: str,
    contradiction_propagation: str,
    context_integrity: str,
    narrative_coherence: float,
) -> dict[str, Any]:
    failure_pattern, pattern_note = classify_failure_pattern(
        stage1_verdict=stage1_verdict,
        stage2_verdict=stage2_verdict,
        confidence_realism=confidence_realism,
        alignment_level=alignment_level,
        contradiction_level=contradiction_level,
    )

    integrated_verdict, integrated_note = assign_integrated_verdict(
        stage1_verdict=stage1_verdict,
        stage2_verdict=stage2_verdict,
        market_verdict=market_verdict,
        confidence_realism=confidence_realism,
        alignment_level=alignment_level,
        contradiction_level=contradiction_level,
        context_integrity=context_integrity,
        failure_pattern=failure_pattern,
    )

    root_cause = assign_root_cause(
        failure_pattern=failure_pattern,
        stage1_verdict=stage1_verdict,
        stage2_verdict=stage2_verdict,
        confidence_realism=confidence_realism,
        alignment_level=alignment_level,
        contradiction_propagation=contradiction_propagation,
        context_integrity=context_integrity,
    )

    if narrative_coherence >= 0.75:
        coherence_label = "HIGH"
    elif narrative_coherence >= 0.5:
        coherence_label = "MEDIUM"
    else:
        coherence_label = "LOW"

    return {
        "failure_pattern": failure_pattern,
        "failure_pattern_note": pattern_note,
        "integrated_verdict": integrated_verdict,
        "integrated_note": integrated_note,
        "root_cause": root_cause,
        "narrative_coherence_label": coherence_label,
    }
