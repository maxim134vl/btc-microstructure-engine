"""Forensic markdown reports for Stage 2.5 intermediate cognition validation."""

from __future__ import annotations

from typing import Any


def render_event_block(event: dict[str, Any]) -> str:
    horizons = event.get("horizons") or {}
    horizon_lines = []
    for key in sorted(horizons, key=lambda item: int(item)):
        item = horizons[key]
        horizon_lines.append(f"- +{key} bars: **{item.get('verdict')}** — {item.get('note', '—')}")

    ctx = event.get("context") or {}
    lines = [
        "--------------------------------------------------",
        "",
        f"EVENT #{event.get('event_index', '?')}",
        "",
        "Timestamp:",
        f"{event.get('timestamp')}",
        "",
        "Intermediate State:",
        f"{event.get('intermediate_state')}",
        "",
        "Stage 2 Anchor:",
        f"{ctx.get('anchor_stage2_state')} @ {ctx.get('anchor_timestamp')}",
        "",
        "Interpretation:",
        event.get("interpretation", "—"),
        "",
        "Observed Outcome:",
        event.get("observed_outcome", "—"),
        "",
        "Validation:",
        event.get("verdict", "—"),
        "",
        "Confirmation Horizon:",
        str(event.get("confirmation_horizon") or "—"),
        "",
        "Horizon Breakdown:",
        *(horizon_lines or ["- (none)"]),
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
    period: dict[str, Any] | None = None,
) -> str:
    header = [
        "# Stage 2.5 Intermediate Cognition Validation Report",
        "",
        f"Run ID: `{run_id}`",
        "",
    ]

    if period:
        header.extend(
            [
                f"Period: **{period.get('start')}** → **{period.get('end')}**",
                "",
            ]
        )

    header.extend(
        [
            "## Summary",
            "",
            f"- Events validated: **{summary.get('event_count', 0)}**",
            f"- Narrative confirmation rate: **{summary.get('narrative_confirmation_rate', 0):.1%}**",
            f"- Confirmation rate: **{summary.get('confirmation_rate', 0):.1%}**",
            f"- Precision: **{summary.get('precision', 0):.1%}**",
            f"- False positive rate: **{summary.get('false_positive_rate', 0):.1%}**",
            f"- Early warning rate: **{summary.get('early_warning_rate', 0):.1%}**",
            f"- Avg horizon to confirmation: **{summary.get('average_horizon_to_confirmation', 0)} bars**",
            "",
            "### Verdict Distribution",
            "",
        ]
    )

    for verdict, count in summary.get("verdict_distribution", {}).items():
        header.append(f"- {verdict}: {count}")

    header.extend(["", "### State-Specific Metrics", ""])
    for state, metrics in (summary.get("by_state") or {}).items():
        header.extend(
            [
                f"#### {state}",
                "",
                f"- Events: {metrics.get('event_count', 0)}",
                f"- Precision: {metrics.get('precision', 0):.1%}",
                f"- Confirmation rate: {metrics.get('confirmation_rate', 0):.1%}",
                f"- False positive rate: {metrics.get('false_positive_rate', 0):.1%}",
                f"- Early warning rate: {metrics.get('early_warning_rate', 0):.1%}",
                f"- Avg horizon to confirmation: {metrics.get('average_horizon_to_confirmation', 0)} bars",
                "",
            ]
        )

    header.extend(["", "## Intermediate Cognition Forensics", ""])
    body = "\n".join(render_event_block(event) for event in results)
    return "\n".join(header) + "\n" + body
