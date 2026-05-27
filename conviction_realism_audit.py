"""Generate conviction realism audit report from runtime parquet exports."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from calibration_diagnostics import analyze_realism

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(ROOT, "docs", "CONVICTION_REALISM_AUDIT.md")


def _format_distribution(title: str, distribution: Dict[str, Dict[str, float]]) -> str:
    lines = [f"### {title}", ""]
    if not distribution:
        lines.append("_No decomposition rows available._")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Component | Mean Share | Median Share | P90 Share | Max Share |")
    lines.append("|-----------|------------|--------------|-----------|-----------|")
    for component, stats in sorted(distribution.items()):
        lines.append(
            f"| `{component}` | {stats['mean_share']:.3f} | "
            f"{stats['median_share']:.3f} | {stats['p90_share']:.3f} | "
            f"{stats['max_share']:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_frequency(title: str, frequency: Dict[str, float]) -> str:
    lines = [f"### {title}", ""]
    if not frequency:
        lines.append("_No dominant component data._")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Component | Frequency |")
    lines.append("|-----------|-----------|")
    for component, share in sorted(
        frequency.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        lines.append(f"| `{component}` | {share:.3f} |")
    lines.append("")
    return "\n".join(lines)


def _verdict(metrics: Dict[str, Any]) -> str:
    saturation = metrics.get("conviction_saturation_frequency", 0.0) or 0.0
    alignment_ratio = metrics.get("alignment_dominance_ratio", 0.0) or 0.0
    entropy_fail = metrics.get("entropy_suppression_frequency", 0.0) or 0.0
    mean_conviction = metrics.get("mean_conviction_probability", 0.0) or 0.0

    overconfidence_signals = 0
    if saturation > 0.15:
        overconfidence_signals += 1
    if alignment_ratio > 0.35:
        overconfidence_signals += 1
    if entropy_fail > 0.25:
        overconfidence_signals += 1
    if mean_conviction > 0.75:
        overconfidence_signals += 1

    if overconfidence_signals >= 3:
        return (
            "**Assessment:** Runtime exhibits **structural overconfidence** "
            "signals — conviction is frequently saturated while entropy "
            "suppression is weak and alignment dominates component share."
        )
    if overconfidence_signals >= 1:
        return (
            "**Assessment:** Runtime shows **mixed probabilistic behavior** — "
            "some overconfidence signals present but not uniformly dominant."
        )
    return (
        "**Assessment:** Runtime currently behaves **within expected "
        "probabilistic spread** on available sample — continue monitoring "
        "via replay validation before calibration changes."
    )


def render_audit_report(metrics: Dict[str, Any]) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()

    sections = [
        "# CONVICTION REALISM AUDIT",
        "",
        f"**Generated:** {generated_at}  ",
        "**Phase:** 1A — Probabilistic Calibration Diagnostics  ",
        "**Scope:** Observability only — no calibration changes applied",
        "",
        "---",
        "",
        "## 1. Sample Coverage",
        "",
        f"- Probabilistic rows analyzed: **{metrics['probabilistic_rows_analyzed']}**",
        f"- Reinforcement rows analyzed: **{metrics['reinforcement_rows_analyzed']}**",
        f"- HIGH_CONVICTION belief rows: **{metrics['high_conviction_state_count']}**",
        "",
        "## 2. Component Contribution Distribution",
        "",
        _format_distribution(
            "Probabilistic Memory",
            metrics["probabilistic_component_distribution"],
        ),
        _format_distribution(
            "Reinforcement Memory",
            metrics["reinforcement_component_distribution"],
        ),
        "## 3. Dominant Component Frequency",
        "",
        _format_frequency(
            "Probabilistic Dominant Component",
            metrics["probabilistic_dominant_component_frequency"],
        ),
        _format_frequency(
            "Reinforcement Dominant Component",
            metrics["reinforcement_dominant_component_frequency"],
        ),
        "## 4. Required Diagnostic Metrics",
        "",
        "| Metric | Value | Interpretation |",
        "|--------|-------|----------------|",
        f"| Reinforcement persistence duration (est.) | "
        f"{metrics['reinforcement_persistence_duration_estimate']} | "
        f"Consecutive identical belief_state at tail |",
        f"| Entropy suppression frequency | "
        f"{metrics['entropy_suppression_frequency']:.3f} | "
        f"High conviction with low entropy penalty |",
        f"| Conviction saturation frequency | "
        f"{metrics['conviction_saturation_frequency']:.3f} | "
        f"Share of rows with conviction > 0.90 |",
        f"| Alignment dominance ratio | "
        f"{metrics['alignment_dominance_ratio']:.3f} | "
        f"Mean alignment share of decomposition mass |",
        f"| Mean conviction probability | "
        f"{metrics['mean_conviction_probability']:.3f} | "
        f"Central tendency of exported conviction |",
        f"| Mean entropy penalty | "
        f"{metrics['mean_entropy_penalty']:.3f} | "
        f"Belief-state entropy observability |",
        f"| Mean conflict penalty (probabilistic) | "
        f"{metrics['mean_conflict_penalty_probabilistic']:.3f} | "
        f"Conflict signal propagated from reinforcement |",
        "",
        "## 5. Component Focus",
        "",
        "### alignment_component",
        "Measures MTF alignment multiplier (probabilistic) or additive delta "
        "(reinforcement). High dominance suggests structural agreement is "
        "driving conviction more than conflict or entropy signals.",
        "",
        "### persistence_component",
        "Exports persistence score / additive persistence contribution. "
        "Low values with high conviction indicate weak persistence realism.",
        "",
        "### reinforcement_component",
        "Base reinforcement contribution before cognition multipliers. "
        "Rising tail values with saturation flags indicate reinforcement inflation.",
        "",
        "### entropy_penalty",
        "Shannon entropy of belief-state window (observability only). "
        "Low entropy with high conviction indicates entropy suppression failure.",
        "",
        "### conflict_penalty",
        "Conflict score propagated from reinforcement path. "
        "Low conflict with high conviction suggests contradiction density is under-expressed.",
        "",
        "## 6. Realism Verdict",
        "",
        _verdict(metrics),
        "",
        "## 7. Raw Metrics JSON",
        "",
        "```json",
        json.dumps(metrics, indent=2, default=str),
        "```",
        "",
        "---",
        "",
        "*Regenerate:* `venv/bin/python3 conviction_realism_audit.py`",
        "",
    ]

    return "\n".join(sections)


def run(
    reinforcement_path: str = "auction_reinforcement_memory.parquet",
    probabilistic_path: str = "probabilistic_auction_memory.parquet",
    output_path: str = OUTPUT_PATH,
) -> Dict[str, Any]:
    metrics = analyze_realism(
        reinforcement_path=reinforcement_path,
        probabilistic_path=probabilistic_path,
    )
    report = render_audit_report(metrics)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(report)

    print(f"Wrote {output_path}")
    return metrics


if __name__ == "__main__":
    run()
