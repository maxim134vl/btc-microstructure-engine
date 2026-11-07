"""Generate cross-regime calibration stability analysis report."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd

from calibration_stability import (
    metrics_by_regime,
    unstable_regimes,
    walk_forward_epochs,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(ROOT, "docs", "CROSS_REGIME_CALIBRATION_ANALYSIS.md")


def _format_regime_table(metrics: Dict[str, Dict[str, float]]) -> str:
    lines = [
        "| Regime | Rows | Mean Conviction | Saturation Freq | Entropy Effectiveness | Conflict Density | Reinforcement Persistence |",
        "|--------|------|-----------------|-----------------|----------------------|------------------|---------------------------|",
    ]
    for regime, values in sorted(metrics.items()):
        lines.append(
            f"| `{regime}` | {int(values.get('rows', 0))} | "
            f"{values.get('mean_conviction', 0.0):.3f} | "
            f"{values.get('saturation_frequency', 0.0):.3f} | "
            f"{values.get('entropy_suppression_effectiveness', 0.0):.3f} | "
            f"{values.get('mean_conflict_density', 0.0):.3f} | "
            f"{values.get('reinforcement_persistence', 0.0):.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_walk_forward_table(epochs: list) -> str:
    if not epochs:
        return "_Insufficient history for walk-forward epochs._\n"

    lines = [
        "| Epoch | Stability Score | Regime Drift | Conviction Drift | Entropy Drift | Reinforcement Drift |",
        "|-------|-----------------|--------------|------------------|---------------|---------------------|",
    ]
    for epoch in epochs[-10:]:
        lines.append(
            f"| {epoch.get('walk_forward_epoch', 0)} | "
            f"{epoch.get('calibration_stability_score', 0.0):.3f} | "
            f"{epoch.get('regime_drift_score', 0.0):.3f} | "
            f"{epoch.get('conviction_drift', 0.0):.3f} | "
            f"{epoch.get('entropy_drift', 0.0):.3f} | "
            f"{epoch.get('reinforcement_drift', 0.0):.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_report(
    metrics: Dict[str, Dict[str, float]],
    epochs: list,
    sample_rows: int,
) -> str:
    unstable = unstable_regimes(metrics)
    generated_at = datetime.now(timezone.utc).isoformat()
    mean_stability = (
        sum(epoch.get("calibration_stability_score", 0.0) for epoch in epochs)
        / max(len(epochs), 1)
    )

    return "\n".join(
        [
            "# CROSS-REGIME CALIBRATION ANALYSIS",
            "",
            f"**Generated:** {generated_at}  ",
            "**Phase:** 2A — Cross-Regime Robustness & Calibration Stability  ",
            "**Scope:** Robustness engineering — no ontology or threshold changes",
            "",
            "---",
            "",
            "## 1. Sample Coverage",
            "",
            f"- Probabilistic rows analyzed: **{sample_rows}**",
            f"- Walk-forward epochs: **{len(epochs)}**",
            f"- Mean calibration stability score: **{mean_stability:.3f}**",
            "",
            "## 2. Conviction & Calibration Metrics by Regime",
            "",
            _format_regime_table(metrics),
            "## 3. Unstable Regime Detection",
            "",
            "Regimes flagged when saturation frequency > 0.25, entropy effectiveness < 0.50, "
            "or mean conflict density > 0.45.",
            "",
            f"**Unstable regimes:** {', '.join(f'`{r}`' for r in unstable) if unstable else '_None detected on sample._'}",
            "",
            "## 4. Walk-Forward Robustness",
            "",
            _format_walk_forward_table(epochs),
            "## 5. Interpretation",
            "",
            "This report identifies where disciplined cognition remains stable across "
            "changing market structure versus where calibration degrades. High regime drift "
            "with low stability scores indicates cross-regime fragility requiring further "
            "monitoring before any runtime default changes.",
            "",
            "## 6. Raw Metrics JSON",
            "",
            "```json",
            json.dumps(
                {
                    "regime_metrics": metrics,
                    "walk_forward_epochs": epochs[-10:],
                    "unstable_regimes": unstable,
                },
                indent=2,
            ),
            "```",
            "",
            "---",
            "",
            "*Regenerate:* `venv/bin/python3 cross_regime_calibration_analysis.py`",
            "",
        ]
    )


def run(
    probabilistic_path: str = "probabilistic_auction_memory.parquet",
    output_path: str = OUTPUT_PATH,
    sample_size: int = 500,
) -> Dict[str, Any]:
    frame = pd.read_parquet(probabilistic_path)
    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp")

    subset = frame.tail(sample_size)
    metrics = metrics_by_regime(subset)
    epochs = walk_forward_epochs(subset)

    report = render_report(metrics, epochs, len(subset))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(report)

    print(f"Wrote {output_path}")
    return {
        "regime_metrics": metrics,
        "walk_forward_epochs": epochs,
        "sample_rows": len(subset),
    }


if __name__ == "__main__":
    run()
