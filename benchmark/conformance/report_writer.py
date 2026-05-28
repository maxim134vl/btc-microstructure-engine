"""Forensic conformance and calibration reports."""

from __future__ import annotations

from typing import Any


def render_metric_block(row: dict[str, Any]) -> str:
    observed = row.get("observed_value")
    observed_text = f"{observed:.1%}" if observed is not None else "no data"
    drift = "SEVERE" if row["verdict"] == "SEVERE_DRIFT" else row["verdict"]

    lines = [
        "--------------------------------------------------",
        "",
        f"METRIC: {row['metric']} ({row['layer']})",
        "",
        "EXPECTED:",
        row.get("expected_description", "—"),
        "",
        "OBSERVED:",
        observed_text,
        "",
        "RESULT:",
        row.get("verdict", "—"),
        "",
        "DRIFT:",
        drift,
        "",
        "CALIBRATION IMPLICATION:",
        row.get("calibration_hint") or row.get("note", "—"),
        "",
    ]
    return "\n".join(lines)


def render_conformance_report(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    drift: dict[str, Any],
    calibration: dict[str, Any],
    ontology: dict[str, Any],
    *,
    run_id: str,
) -> str:
    header = [
        "# Cognition Conformance Backtest Report",
        "",
        f"Run ID: `{run_id}`",
        "",
        "## Architecture Conformance Summary",
        "",
        f"- Cognition health: **{summary.get('cognition_health')}** {summary.get('health_emoji', '')}",
        f"- Metrics evaluated: **{summary.get('metric_count', 0)}**",
        f"- Confirmed: **{summary.get('confirmed_count', 0)}**",
        f"- Failed / drift: **{summary.get('failed_count', 0)}** / **{summary.get('drifting_count', 0)}**",
        f"- Cognition stability: **{summary.get('cognition_stability_score', 0):.1%}**",
        f"- Ontology integrity: **{ontology.get('score', 0):.1%}** ({ontology.get('status')})",
        f"- Calibration health: **{summary.get('calibration_health_score', 0):.1%}**",
        f"- Drift severity: **{drift.get('severity', 'NONE')}**",
        "",
        "### Health Scores",
        "",
        f"- Confidence realism: **{summary.get('confidence_realism_score', 0):.1%}**",
        f"- Transition stability: **{summary.get('transition_stability_score', 0):.1%}**",
        f"- Contradiction pressure: **{summary.get('contradiction_pressure_score', 0):.1%}**",
        f"- Drift severity score: **{summary.get('drift_severity_score', 0):.1%}**",
        "",
        "### Drift Signals",
        "",
    ]
    for signal in drift.get("signals") or ["none"]:
        header.append(f"- {signal}")

    header.extend(["", "## Calibration Recommendations", ""])
    for item in calibration.get("recommendations") or []:
        header.append(f"- **[{item['priority']}]** {item['recommendation']}")
        header.append(f"  - Evidence: {item.get('evidence', '—')}")

    header.extend(["", "## Metric Conformance Forensics", ""])
    body = "\n".join(render_metric_block(row) for row in results)
    return "\n".join(header) + "\n" + body


def render_drift_report(drift: dict[str, Any], summary: dict[str, Any], *, run_id: str) -> str:
    lines = [
        "# Cognition Drift Report",
        "",
        f"Run ID: `{run_id}`",
        "",
        f"Severity: **{drift.get('severity', 'NONE')}**",
        f"Cognition health: **{summary.get('cognition_health')}**",
        "",
        "## Active Drift Signals",
        "",
    ]
    for signal in drift.get("signals") or ["none"]:
        lines.append(f"- {signal}")

    lines.extend(["", "## Drift Map", ""])
    for key, active in (drift.get("drift_map") or {}).items():
        lines.append(f"- {key}: {'YES' if active else 'no'}")
    return "\n".join(lines)
