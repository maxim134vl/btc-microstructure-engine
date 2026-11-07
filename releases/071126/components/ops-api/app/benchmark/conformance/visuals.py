"""Render conformance drift visual charts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

VERDICT_COLORS = {
    "CONFIRMED": "#22c55e",
    "PARTIAL": "#eab308",
    "FAILED": "#ef4444",
    "DRIFTING": "#f97316",
    "SEVERE_DRIFT": "#dc2626",
    "ONTOLOGY_DEGRADATION": "#7c3aed",
    "CALIBRATION_COLLAPSE": "#991b1b",
}


def render_conformance_chart(results: list[dict[str, Any]], output_path: Path) -> str | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if not results:
        return None

    labels = [f"{r['layer'][:2]}:{r['metric'][:14]}" for r in results]
    divergences = [float(r.get("divergence", 0.0)) for r in results]
    colors = [VERDICT_COLORS.get(r["verdict"], "#64748b") for r in results]

    fig, ax = plt.subplots(figsize=(12, max(4, len(results) * 0.35)), facecolor="#0a0f14")
    ax.set_facecolor("#0a0f14")
    ax.barh(labels, divergences, color=colors)
    ax.set_xlabel("Divergence from spec", color="#94a3b8")
    ax.set_title("Conformance Divergence by Metric", color="#e2e8f0")
    ax.tick_params(colors="#94a3b8")
    for spine in ax.spines.values():
        spine.set_color("#1e293b")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="#0a0f14")
    plt.close(fig)
    return str(output_path)


def render_health_chart(summary: dict[str, Any], output_path: Path) -> str | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    scores = {
        "Stability": summary.get("cognition_stability_score", 0),
        "Ontology": summary.get("ontology_integrity_score", 0),
        "Calibration": summary.get("calibration_health_score", 0),
        "Confidence": summary.get("confidence_realism_score", 0),
        "Transitions": summary.get("transition_stability_score", 0),
    }

    fig, ax = plt.subplots(figsize=(8, 4), facecolor="#0a0f14")
    ax.set_facecolor("#0a0f14")
    labels = list(scores.keys())
    values = [scores[k] for k in labels]
    colors = ["#22c55e" if v >= 0.6 else "#eab308" if v >= 0.4 else "#ef4444" for v in values]
    ax.bar(labels, values, color=colors)
    ax.set_ylim(0, 1)
    ax.set_title(f"Cognition Health — {summary.get('cognition_health', 'UNKNOWN')}", color="#e2e8f0")
    ax.tick_params(colors="#94a3b8")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, facecolor="#0a0f14")
    plt.close(fig)
    return str(output_path)
