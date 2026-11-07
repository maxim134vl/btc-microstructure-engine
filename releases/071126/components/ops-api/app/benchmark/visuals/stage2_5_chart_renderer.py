"""Render Stage 2.5 intermediate cognition validation charts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet

VERDICT_COLORS = {
    "CONFIRMED": "#22c55e",
    "PARTIAL": "#eab308",
    "FAILED": "#ef4444",
    "FALSE_POSITIVE": "#f97316",
    "EARLY_WARNING": "#6366f1",
}


def render_stage2_5_summary_chart(results: list[dict[str, Any]], output_path: Path) -> str | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if not results:
        return None

    counts: dict[str, int] = {}
    for row in results:
        verdict = row.get("verdict", "PARTIAL")
        counts[verdict] = counts.get(verdict, 0) + 1

    labels = list(counts.keys())
    values = [counts[label] for label in labels]
    colors = [VERDICT_COLORS.get(label, "#94a3b8") for label in labels]

    fig, ax = plt.subplots(figsize=(10, 5), facecolor="#0a0f14")
    ax.set_facecolor("#0a0f14")
    ax.bar(labels, values, color=colors)
    ax.set_title("Stage 2.5 Intermediate Cognition Verdicts", color="#e2e8f0")
    ax.tick_params(colors="#94a3b8")
    for spine in ax.spines.values():
        spine.set_color("#334155")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(output_path)


def render_intermediate_event_chart(
    event: dict[str, Any],
    *,
    output_path: Path,
    window_before: int = 16,
    window_after: int = 18,
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
    label = (
        f"{verdict}\n{event.get('intermediate_state', '')}\n"
        f"anchor: {event.get('context', {}).get('anchor_stage2_state', '—')}"
    )
    ax.annotate(
        label,
        xy=(event_ts, float(event_row["high"])),
        xytext=(10, 20),
        textcoords="offset points",
        color=color,
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "#111827", "edgecolor": color, "alpha": 0.9},
    )

    ax.set_title("Stage 2.5 Intermediate Cognition Event", color="#e2e8f0", fontsize=11)
    ax.tick_params(axis="x", colors="#64748b", rotation=20)
    ax.tick_params(axis="y", colors="#64748b")
    for spine in ax.spines.values():
        spine.set_color("#334155")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(output_path)
