"""Render Stage 2.5 calibration reports."""

from __future__ import annotations

from typing import Any


def render_calibration_markdown(assessment: dict[str, Any], *, run_id: str) -> str:
    lines = [
        "# Stage 2.5 Intermediate Cognition Calibration Report",
        "",
        f"Run ID: `{run_id}`",
        "",
        f"Overall status: **{assessment.get('overall_status', 'UNKNOWN')}**",
        f"Benchmark runs in window: **{assessment.get('run_count', 0)}**",
        f"Latest benchmark: `{assessment.get('latest_run_id', '—')}`",
        "",
        "## Overall Metric Trends",
        "",
    ]

    for metric, trend in (assessment.get("overall_trends") or {}).items():
        current = trend.get("current")
        previous = trend.get("previous")
        direction = trend.get("trend", "unknown")
        cur_text = f"{current:.1%}" if isinstance(current, (int, float)) else "—"
        prev_text = f"{previous:.1%}" if isinstance(previous, (int, float)) else "—"
        lines.append(f"- **{metric}**: {cur_text} (prev {prev_text}) · trend **{direction}**")

    lines.extend(["", "## Per-State Calibration", ""])
    for state, block in (assessment.get("states") or {}).items():
        lines.extend(
            [
                f"### {state}",
                "",
                f"- Status: **{block.get('status')}**",
                f"- Events (latest run): {block.get('event_count', 0)}",
                "",
            ]
        )
        for metric, trend in (block.get("trends") or {}).items():
            current = trend.get("current")
            direction = trend.get("trend", "unknown")
            cur_text = f"{current:.1%}" if isinstance(current, (int, float)) else "—"
            lines.append(f"  - {metric}: {cur_text} · {direction}")
        lines.append("")

    evolution = assessment.get("evolution_context") or {}
    conformance = assessment.get("conformance_context") or {}
    lines.extend(
        [
            "## External Context",
            "",
            f"- Evolution trust: {evolution.get('trust_level', '—')}",
            f"- Evolution regression: {evolution.get('regression_verdict', '—')}",
            f"- Conformance health: {conformance.get('cognition_health', '—')}",
            f"- Calibration health score: {conformance.get('calibration_health_score', '—')}",
            "",
            "## Status Definitions",
            "",
            "- **VERIFIED** — high precision/confirmation, low false positives, stable or improving trends",
            "- **STABLE** — acceptable quality, no multi-metric degradation",
            "- **DEGRADING** — one or more metrics trending worse",
            "- **NEEDS_CALIBRATION** — below quality thresholds or external pressure from evolution/conformance",
            "",
        ]
    )
    return "\n".join(lines)


def build_calibration_snapshot(assessment: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "overall_status": assessment.get("overall_status"),
        "overall_metrics": assessment.get("overall_metrics"),
        "overall_trends": assessment.get("overall_trends"),
        "states": assessment.get("states"),
        "evolution_context": assessment.get("evolution_context"),
        "conformance_context": assessment.get("conformance_context"),
        "external_pressure": assessment.get("external_pressure"),
        "sources": assessment.get("sources"),
        "latest_run_id": assessment.get("latest_run_id"),
        "latest_generated_at": assessment.get("latest_generated_at"),
        "run_count": assessment.get("run_count"),
    }
