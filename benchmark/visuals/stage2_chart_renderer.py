"""Render Stage 2 reasoning validation charts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet

VERDICT_COLORS = {
    "CONFIRMED": "#22c55e",
    "PARTIAL": "#eab308",
    "FAILED": "#ef4444",
    "OVERCONFIDENT": "#f97316",
    "UNDERCONFIDENT": "#38bdf8",
    "CONTRADICTORY": "#a855f7",
    "NOISY_REASONING": "#fb7185",
    "CONTEXT_FAILURE": "#64748b",
    "FALSE_NARRATIVE": "#dc2626",
}


def render_reasoning_chart(
    event: dict[str, Any],
    *,
    output_path: Path,
    window_before: int = 20,
    window_after: int = 12,
) -> str | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    candles = safe_read_parquet("candle_structure_memory.parquet")
    if len(candles) == 0:
        return None

    candles = candles.copy()
    candles["timestamp"] = pd.to_datetime(candles["timestamp"])
    candles = candles.sort_values("timestamp").reset_index(drop=True)

    ts = pd.to_datetime(event["timestamp"])
    idx_list = candles.index[candles["timestamp"] == ts].tolist()
    if not idx_list:
        pos = int(candles["timestamp"].searchsorted(ts))
        if pos >= len(candles):
            return None
        idx = pos
    else:
        idx = idx_list[0]

    start = max(0, idx - window_before)
    end = min(len(candles), idx + window_after + 1)
    window = candles.iloc[start:end].copy()
    event_pos = idx - start
    event_row = window.iloc[event_pos]
    event_ts = event_row["timestamp"]

    fig, ax = plt.subplots(figsize=(13, 5.5), facecolor="#0a0f14")
    ax.set_facecolor("#0a0f14")

    for _, row in window.iterrows():
        color = "#22c55e" if row["close"] >= row["open"] else "#ef4444"
        ax.plot([row["timestamp"], row["timestamp"]], [row["low"], row["high"]], color=color, linewidth=1)
        ax.plot([row["timestamp"], row["timestamp"]], [row["open"], row["close"]], color=color, linewidth=4)

    ax.axvline(event_ts, color="#38bdf8", linestyle="--", linewidth=1.2, alpha=0.85)

    verdict = event.get("verdict", "PARTIAL")
    color = VERDICT_COLORS.get(verdict, "#94a3b8")
    stage1 = event.get("stage1_inputs") or []
    stage1_text = ", ".join(stage1[:3]) if isinstance(stage1, list) else str(stage1)
    label = (
        f"{verdict}\nS2: {str(event.get('stage2_interpretation', ''))[:48]}\n"
        f"S1: {stage1_text[:48]}\n{event.get('outcome', {}).get('move_pct', 0):+.2f}%"
    )
    ax.annotate(
        label,
        xy=(event_ts, float(event_row["high"])),
        xytext=(12, 24),
        textcoords="offset points",
        color=color,
        fontsize=8,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#111827", edgecolor=color),
    )

    ax.set_title(
        f"Stage 2 Reasoning #{event.get('event_index')} — {event.get('confidence_quality', '')}",
        color="#e2e8f0",
        fontsize=11,
    )
    ax.tick_params(colors="#64748b")
    for spine in ax.spines.values():
        spine.set_color("#1e293b")
    fig.autofmt_xdate()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="#0a0f14")
    plt.close(fig)
    return str(output_path)


def render_stage2_summary_chart(results: list[dict[str, Any]], output_path: Path) -> str | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if not results:
        return None

    verdicts: dict[str, int] = {}
    for row in results:
        verdicts[row["verdict"]] = verdicts.get(row["verdict"], 0) + 1

    fig, ax = plt.subplots(figsize=(9, 4.5), facecolor="#0a0f14")
    ax.set_facecolor("#0a0f14")
    labels = list(verdicts.keys())
    values = [verdicts[key] for key in labels]
    colors = [VERDICT_COLORS.get(key, "#64748b") for key in labels]
    ax.bar(labels, values, color=colors)
    ax.set_title("Stage 2 Reasoning Validation Verdicts", color="#e2e8f0")
    ax.tick_params(colors="#94a3b8", axis="x", rotation=25)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="#0a0f14")
    plt.close(fig)
    return str(output_path)
