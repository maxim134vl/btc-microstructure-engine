"""Generate Phase 1B before/after calibration discipline comparison report."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd

from calibration_config import CalibrationSettings
from calibration_diagnostics import (
    SATURATION_THRESHOLD,
    build_diagnostic_exports,
    compute_saturation_metrics,
)
from calibration_discipline import apply_probabilistic_discipline

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(ROOT, "docs", "PHASE_1B_CALIBRATION_RESULTS.md")


def _conviction_column(frame: pd.DataFrame) -> str:
    if "raw_conviction" in frame.columns:
        return "raw_conviction"
    return "conviction_probability"


def compare_discipline_on_frame(
    probabilistic: pd.DataFrame,
    reinforcement: pd.DataFrame,
    settings: CalibrationSettings,
) -> Dict[str, Any]:
    conviction_column = _conviction_column(probabilistic)
    raw_values = []
    disciplined_values = []
    saturation_before = []
    saturation_after = []
    entropy_interactions = []

    for index in range(len(probabilistic)):
        row = probabilistic.iloc[index]
        history = probabilistic.iloc[:index]
        window = reinforcement.iloc[: max(index + 1, 1)].tail(25)

        raw = float(row.get(conviction_column, row.get("conviction_probability", 0.0)))
        snapshot = row.to_dict()
        snapshot["raw_conviction"] = raw

        diagnostics = build_diagnostic_exports(
            probabilistic_history=history,
            reinforcement_history=reinforcement.iloc[: max(index + 1, 1)],
            reinforcement_window=window,
            runtime_cognition={},
            current_row=snapshot,
        )

        discipline = apply_probabilistic_discipline(
            raw_conviction=raw,
            diagnostics=diagnostics,
            current_snapshot=snapshot,
            runtime_cognition={},
            probabilistic_history=history,
            settings=settings,
        )

        raw_values.append(raw)
        disciplined_values.append(float(discipline["disciplined_conviction"]))
        saturation_before.append(max(0.0, (raw - 0.5) / 0.5))
        saturation_after.append(
            max(0.0, (discipline["disciplined_conviction"] - 0.5) / 0.5)
        )
        entropy_interactions.append(float(discipline["entropy_interaction"]))

    raw_series = pd.Series(raw_values)
    disciplined_series = pd.Series(disciplined_values)

    return {
        "rows_compared": len(probabilistic),
        "mean_raw_conviction": float(raw_series.mean()),
        "mean_disciplined_conviction": float(disciplined_series.mean()),
        "mean_divergence": float((raw_series - disciplined_series).mean()),
        "max_divergence": float((raw_series - disciplined_series).max()),
        "saturation_frequency_before": float(
            (raw_series > SATURATION_THRESHOLD).mean()
        ),
        "saturation_frequency_after": float(
            (disciplined_series > SATURATION_THRESHOLD).mean()
        ),
        "mean_saturation_reduction": float(
            pd.Series(saturation_before).mean()
            - pd.Series(saturation_after).mean()
        ),
        "entropy_suppression_effectiveness": float(
            pd.Series(entropy_interactions).mean()
        ),
        "reinforcement_stability_proxy": float(
            disciplined_series.std() / max(raw_series.std(), 1e-6)
        ),
    }


def render_report(
    disabled_metrics: Dict[str, Any],
    enabled_metrics: Dict[str, Any],
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()

    return "\n".join(
        [
            "# PHASE 1B CALIBRATION RESULTS",
            "",
            f"**Generated:** {generated_at}  ",
            "**Phase:** 1B — Controlled Probabilistic Discipline  ",
            "**Default runtime:** discipline flags OFF (backward compatible)",
            "",
            "---",
            "",
            "## 1. Comparison Summary",
            "",
            "| Metric | Discipline OFF | Discipline ON | Delta |",
            "|--------|----------------|---------------|-------|",
            f"| Mean conviction | {disabled_metrics['mean_disciplined_conviction']:.4f} | "
            f"{enabled_metrics['mean_disciplined_conviction']:.4f} | "
            f"{enabled_metrics['mean_disciplined_conviction'] - disabled_metrics['mean_disciplined_conviction']:.4f} |",
            f"| Saturation frequency (>0.90) | {disabled_metrics['saturation_frequency_after']:.3f} | "
            f"{enabled_metrics['saturation_frequency_after']:.3f} | "
            f"{enabled_metrics['saturation_frequency_after'] - disabled_metrics['saturation_frequency_after']:.3f} |",
            f"| Mean saturation reduction | {disabled_metrics['mean_saturation_reduction']:.4f} | "
            f"{enabled_metrics['mean_saturation_reduction']:.4f} | "
            f"{enabled_metrics['mean_saturation_reduction'] - disabled_metrics['mean_saturation_reduction']:.4f} |",
            f"| Entropy interaction (mean) | {disabled_metrics['entropy_suppression_effectiveness']:.4f} | "
            f"{enabled_metrics['entropy_suppression_effectiveness']:.4f} | "
            f"{enabled_metrics['entropy_suppression_effectiveness'] - disabled_metrics['entropy_suppression_effectiveness']:.4f} |",
            f"| Reinforcement stability proxy | {disabled_metrics['reinforcement_stability_proxy']:.4f} | "
            f"{enabled_metrics['reinforcement_stability_proxy']:.4f} | "
            f"{enabled_metrics['reinforcement_stability_proxy'] - disabled_metrics['reinforcement_stability_proxy']:.4f} |",
            "",
            "## 2. Discipline ON Detail",
            "",
            f"- Rows compared: **{enabled_metrics['rows_compared']}**",
            f"- Mean raw vs disciplined divergence: **{enabled_metrics['mean_divergence']:.4f}**",
            f"- Max divergence: **{enabled_metrics['max_divergence']:.4f}**",
            "",
            "## 3. Rollout Guidance",
            "",
            "1. Keep `ENABLE_PROBABILISTIC_DISCIPLINE=false` in production until replay review passes.",
            "2. Enable discipline in replay/staging via environment flags.",
            "3. Set `USE_DISCIPLINED_CONVICTION_AT_RUNTIME=true` only after saturation reduction confirmed.",
            "4. Use `CALIBRATION_MODE=disciplined` before `sigmoid` for conservative rollout.",
            "",
            "## 4. Environment Flags",
            "",
            "```bash",
            "export ENABLE_PROBABILISTIC_DISCIPLINE=true",
            "export USE_DISCIPLINED_CONVICTION_AT_RUNTIME=true",
            "export CALIBRATION_MODE=disciplined   # raw | disciplined | sigmoid",
            "```",
            "",
            "## 5. Raw Metrics JSON",
            "",
            "### Discipline OFF",
            "",
            "```json",
            json.dumps(disabled_metrics, indent=2),
            "```",
            "",
            "### Discipline ON",
            "",
            "```json",
            json.dumps(enabled_metrics, indent=2),
            "```",
            "",
            "---",
            "",
            "*Regenerate:* `venv/bin/python3 phase_1b_calibration_results.py`",
            "",
        ]
    )


def run(
    probabilistic_path: str = "probabilistic_auction_memory.parquet",
    reinforcement_path: str = "auction_reinforcement_memory.parquet",
    output_path: str = OUTPUT_PATH,
    sample_size: int = 200,
) -> Dict[str, Any]:
    probabilistic = pd.read_parquet(probabilistic_path)
    reinforcement = pd.read_parquet(reinforcement_path)

    if "timestamp" in probabilistic.columns:
        probabilistic = probabilistic.sort_values("timestamp")

    subset = probabilistic.tail(sample_size)

    disabled_settings = CalibrationSettings(enable_probabilistic_discipline=False)
    enabled_settings = CalibrationSettings(
        enable_probabilistic_discipline=True,
        use_disciplined_conviction_at_runtime=True,
        calibration_mode="disciplined",
    )

    disabled_metrics = compare_discipline_on_frame(
        subset,
        reinforcement,
        disabled_settings,
    )
    enabled_metrics = compare_discipline_on_frame(
        subset,
        reinforcement,
        enabled_settings,
    )

    report = render_report(disabled_metrics, enabled_metrics)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(report)

    print(f"Wrote {output_path}")
    return {
        "discipline_off": disabled_metrics,
        "discipline_on": enabled_metrics,
    }


if __name__ == "__main__":
    run()
