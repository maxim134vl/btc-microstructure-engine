"""Forensic markdown report writer."""

from __future__ import annotations

from typing import Any


def render_event_block(event: dict[str, Any]) -> str:
    outcome = event.get("outcome", {})
    lines = [
        "--------------------------------------------------",
        "",
        f"EVENT #{event.get('event_index', '?')}",
        "",
        "Timestamp:",
        f"{event.get('timestamp')}",
        "",
        "Stage 1 Interpretation:",
        event.get("interpretation", "—"),
        "",
        "Observed Outcome:",
        event.get("observed_outcome", "—"),
        "",
        "Validation:",
        event.get("verdict", "—"),
        "",
        "Follow-through:",
        outcome.get("follow_through", "—"),
        "",
        "False Positive:",
        "YES" if event.get("false_positive") else "NO",
        "",
        "Note:",
        event.get("validation_note", "—"),
        "",
    ]
    return "\n".join(lines)


def render_forensic_report(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    run_id: str,
) -> str:
    header = [
        "# Stage 1 Cognitive Validation Report",
        "",
        f"Run ID: `{run_id}`",
        "",
        "## Summary",
        "",
        f"- Events validated: **{summary.get('event_count', 0)}**",
        f"- Confirmed rate: **{summary.get('confirmed_rate', 0):.1%}**",
        f"- False positive rate: **{summary.get('false_positive_rate', 0):.1%}**",
        f"- Climax confirmation: **{summary.get('climax_confirmation_rate', 0):.1%}**",
        f"- Stopping quality: **{summary.get('stopping_quality_rate', 0):.1%}**",
        f"- Initiative accuracy: **{summary.get('initiative_accuracy', 0):.1%}**",
        f"- Market structure coherence: **{summary.get('market_structure_coherence', 0):.1%}**",
        "",
        "### Verdict Distribution",
        "",
    ]

    for verdict, count in summary.get("verdict_distribution", {}).items():
        header.append(f"- {verdict}: {count}")

    header.extend(["", "## Event Forensics", ""])

    body = "\n".join(render_event_block(event) for event in results)
    return "\n".join(header) + "\n" + body
