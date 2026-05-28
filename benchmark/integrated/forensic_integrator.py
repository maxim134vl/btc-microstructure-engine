"""Integrated forensic report generation."""

from __future__ import annotations

from typing import Any


def render_chain_block(chain: dict[str, Any]) -> str:
    stage1_inputs = chain.get("stage1_perception") or []
    inputs_text = "\n".join(f"- {item}" for item in stage1_inputs) if stage1_inputs else "- (none recorded)"

    lines = [
        "--------------------------------------------------",
        "",
        f"EVENT #{chain.get('event_index', '?')}",
        "",
        "Stage 1 Perception:",
        inputs_text,
        "",
        "Stage 1 Validation:",
        chain.get("stage1_verdict", "—"),
        "",
        "Stage 2 Interpretation:",
        chain.get("stage2_interpretation", "—"),
        "",
        "Stage 2 Validation:",
        chain.get("stage2_verdict", "—"),
        "",
        "Observed Outcome:",
        chain.get("observed_outcome", "—"),
        "",
        "Integrated Verdict:",
        chain.get("integrated_verdict", "—"),
        "",
        "Root Cause:",
        chain.get("root_cause", "—"),
        "",
        "Failure Pattern:",
        f"{chain.get('failure_pattern', '—')} — {chain.get('failure_pattern_note', '')}",
        "",
        "Confidence Realism:",
        chain.get("confidence_realism", "—"),
        "",
        "Narrative Coherence:",
        chain.get("narrative_coherence_label", "—"),
        "",
        "Cross-Stage Alignment:",
        chain.get("alignment_level", "—"),
        "",
        "Contradiction Propagation:",
        chain.get("contradiction_propagation", "—"),
        "",
        "Note:",
        chain.get("integrated_note", "—"),
        "",
    ]
    return "\n".join(lines)


def render_integrated_report(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    drift: dict[str, Any],
    *,
    run_id: str,
) -> str:
    header = [
        "# Integrated Cognition Validation Report",
        "",
        f"Run ID: `{run_id}`",
        "",
        "## End-to-End Summary",
        "",
        f"- Cognition chains validated: **{summary.get('event_count', 0)}**",
        f"- Fully confirmed: **{summary.get('fully_confirmed_rate', 0):.1%}**",
        f"- Perception accuracy: **{summary.get('perception_accuracy', 0):.1%}**",
        f"- Reasoning accuracy: **{summary.get('reasoning_accuracy', 0):.1%}**",
        f"- Cross-stage alignment: **{summary.get('cross_stage_alignment', 0):.1%}**",
        f"- Confidence realism: **{summary.get('confidence_realism', 0):.1%}**",
        f"- Market confirmation: **{summary.get('market_confirmation_rate', 0):.1%}**",
        f"- Cognition drift frequency: **{summary.get('cognition_drift_frequency', 0):.1%}**",
        "",
        "### Integrated Verdict Distribution",
        "",
    ]

    for verdict, count in summary.get("verdict_distribution", {}).items():
        header.append(f"- {verdict}: {count}")

    header.extend(["", "### Root Cause Distribution", ""])
    for cause, count in summary.get("root_cause_distribution", {}).items():
        header.append(f"- {cause}: {count}")

    header.extend(
        [
            "",
            "## Cognition Drift Analysis",
            "",
            f"- Health: **{drift.get('health', 'UNKNOWN')}**",
            f"- Signals: {', '.join(drift.get('signals', [])) or 'none'}",
            "",
            "## Full Cognition Chain Forensics",
            "",
        ]
    )

    body = "\n".join(render_chain_block(chain) for chain in results)
    return "\n".join(header) + "\n" + body
