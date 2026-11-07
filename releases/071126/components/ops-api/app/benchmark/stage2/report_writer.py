"""Forensic markdown reports for Stage 2 reasoning validation."""

from __future__ import annotations

from typing import Any


def render_event_block(event: dict[str, Any]) -> str:
    stage1_inputs = event.get("stage1_inputs") or []
    if isinstance(stage1_inputs, list):
        inputs_text = "\n".join(f"- {item}" for item in stage1_inputs) if stage1_inputs else "- (none recorded)"
    else:
        inputs_text = f"- {stage1_inputs}"

    lines = [
        "--------------------------------------------------",
        "",
        f"EVENT #{event.get('event_index', '?')}",
        "",
        "Timestamp:",
        f"{event.get('timestamp')}",
        "",
        "Stage 1 Inputs:",
        inputs_text,
        "",
        "Stage 2 Interpretation:",
        event.get("stage2_interpretation", "—"),
        "",
        "Observed Outcome:",
        event.get("observed_outcome", "—"),
        "",
        "Validation:",
        event.get("verdict", "—"),
        "",
        "Confidence Quality:",
        event.get("confidence_quality", "—"),
        "",
        "Narrative Coherence:",
        _coherence_label(event.get("narrative_coherence")),
        "",
        "Contradiction Score:",
        event.get("contradiction_level", "—"),
        "",
        "Context Integrity:",
        event.get("context_integrity", "—"),
        "",
        "Note:",
        event.get("validation_note", "—"),
        "",
    ]
    return "\n".join(lines)


def _coherence_label(value: Any) -> str:
    if value is None:
        return "—"
    score = float(value)
    if score >= 0.75:
        return "HIGH"
    if score >= 0.5:
        return "MODERATE"
    return "LOW"


def render_forensic_report(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    run_id: str,
) -> str:
    header = [
        "# Stage 2 Reasoning Validation Report",
        "",
        f"Run ID: `{run_id}`",
        "",
        "## Summary",
        "",
        f"- Events validated: **{summary.get('event_count', 0)}**",
        f"- Reasoning accuracy: **{summary.get('reasoning_accuracy', 0):.1%}**",
        f"- Probabilistic calibration: **{summary.get('probabilistic_calibration_quality', 0):.1%}**",
        f"- Narrative coherence: **{summary.get('narrative_coherence', 0):.1%}**",
        f"- Contradiction frequency: **{summary.get('contradiction_frequency', 0):.1%}**",
        f"- Overconfident rate: **{summary.get('overconfident_rate', 0):.1%}**",
        f"- Context failure rate: **{summary.get('context_failure_rate', 0):.1%}**",
        f"- Regime interpretation accuracy: **{summary.get('regime_interpretation_accuracy', 0):.1%}**",
        "",
        "### Verdict Distribution",
        "",
    ]

    for verdict, count in summary.get("verdict_distribution", {}).items():
        header.append(f"- {verdict}: {count}")

    header.extend(["", "## Reasoning Forensics", ""])
    body = "\n".join(render_event_block(event) for event in results)
    return "\n".join(header) + "\n" + body
