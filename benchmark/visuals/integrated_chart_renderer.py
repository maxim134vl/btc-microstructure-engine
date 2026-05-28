"""Render integrated cognition replay charts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet

VERDICT_COLORS = {
    "FULLY_CONFIRMED": "#22c55e",
    "PARTIAL_CONFIRMATION": "#84cc16",
    "PERCEPTION_FAILURE": "#f97316",
    "REASONING_FAILURE": "#ef4444",
    "CONFIDENCE_FAILURE": "#fb7185",
    "CONTRADICTION_FAILURE": "#a855f7",
    "FALSE_NARRATIVE": "#dc2626",
    "SYNTHESIS_COLLAPSE": "#991b1b",
    "CONTEXT_BREAKDOWN": "#64748b",
    "ONTOLOGY_DRIFT": "#7c3aed",
}


def render_integrated_chart(
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

    fig, ax = plt.subplots(figsize=(14, 6), facecolor="#0a0f14")
    ax.set_facecolor("#0a0f14")

    for _, row in window.iterrows():
        color = "#22c55e" if row["close"] >= row["open"] else "#ef4444"
        ax.plot([row["timestamp"], row["timestamp"]], [row["low"], row["high"]], color=color, linewidth=1)
        ax.plot([row["timestamp"], row["timestamp"]], [row["open"], row["close"]], color=color, linewidth=4)

    ax.axvline(event_ts, color="#38bdf8", linestyle="--", linewidth=1.2, alpha=0.85)

    if event_pos + 1 < len(window):
        post = window.iloc[event_pos + 1 :]
        ax.plot(post["timestamp"], post["close"], color="#eab308", linewidth=1.5, alpha=0.8, label="post-event")

    verdict = event.get("integrated_verdict", "PARTIAL_CONFIRMATION")
    color = VERDICT_COLORS.get(verdict, "#94a3b8")

    stage1 = event.get("stage1_perception") or []
    s1_text = ", ".join(stage1[:2]) if isinstance(stage1, list) else str(stage1)
    label = (
        f"{verdict}\nS1: {event.get('stage1_verdict')} — {s1_text[:40]}\n"
        f"S2: {event.get('stage2_verdict')} — {str(event.get('stage2_interpretation', ''))[:40]}\n"
        f"Root: {event.get('root_cause', 'none')}\n"
        f"{event.get('outcome', {}).get('move_pct', 0):+.2f}%"
    )
    ax.annotate(
        label,
        xy=(event_ts, float(event_row["high"])),
        xytext=(14, 28),
        textcoords="offset points",
        color=color,
        fontsize=7.5,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#111827", edgecolor=color),
    )

    if event.get("contradiction_level") == "HIGH" and event_pos + 1 < len(window):
        post_ts = window.iloc[event_pos + 1]["timestamp"]
        ax.axvspan(event_ts, post_ts, alpha=0.08, color="#a855f7", label="contradiction zone")

    ax.set_title(
        f"Integrated Cognition #{event.get('event_index')} — {event.get('confidence_realism', '')}",
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


def render_integrated_summary_chart(results: list[dict[str, Any]], output_path: Path) -> str | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if not results:
        return None

    verdicts: dict[str, int] = {}
    for row in results:
        verdicts[row["integrated_verdict"]] = verdicts.get(row["integrated_verdict"], 0) + 1

    fig, ax = plt.subplots(figsize=(10, 4.5), facecolor="#0a0f14")
    ax.set_facecolor("#0a0f14")
    labels = list(verdicts.keys())
    values = [verdicts[key] for key in labels]
    colors = [VERDICT_COLORS.get(key, "#64748b") for key in labels]
    ax.bar(labels, values, color=colors)
    ax.set_title("Integrated Cognition Verdicts", color="#e2e8f0")
    ax.tick_params(colors="#94a3b8", axis="x", rotation=25)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="#0a0f14")
    plt.close(fig)
    return str(output_path)
