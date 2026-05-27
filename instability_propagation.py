"""Instability propagation modeling across runtime cognition layers."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pandas as pd

PROPAGATION_LAYERS = [
    "alignment",
    "reinforcement",
    "persistence",
    "contradiction",
    "entropy",
    "regime",
]

INSTABILITY_EXPORT_COLUMNS = [
    "instability_origin",
    "instability_propagation_chain",
    "instability_persistence",
    "cascade_severity",
]


def _layer_signal(snapshot: Dict[str, Any], layer: str) -> float:
    if layer == "alignment":
        monoculture = float(snapshot.get("alignment_monoculture_score", 0.0))
        alignment = float(snapshot.get("alignment_component", 1.0))
        return max(0.0, monoculture - 0.5) + max(0.0, alignment - 1.15) * 0.5

    if layer == "reinforcement":
        return max(
            0.0,
            float(snapshot.get("reinforcement_acceleration", 0.0)) * 2.0,
            float(snapshot.get("reinforcement_component", 0.0)) - 0.65,
        )

    if layer == "persistence":
        duration = float(snapshot.get("persistence_duration", 0.0))
        component = float(snapshot.get("persistence_component", 0.0))
        if duration < 2 and component > 0.35:
            return component * 0.6
        return 0.0

    if layer == "contradiction":
        return float(snapshot.get("conflict_density", 0.0))

    if layer == "entropy":
        entropy = float(snapshot.get("entropy_penalty", 0.0))
        raw = float(snapshot.get("raw_conviction", 0.0))
        if raw > 0.55 and entropy < 0.40:
            return (0.40 - entropy) * 1.2
        return max(0.0, entropy - 0.70) * 0.4

    if layer == "regime":
        return float(snapshot.get("regime_transition_probability", 0.0))

    return 0.0


def compute_instability_propagation(
    snapshot: Dict[str, Any],
    history: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    history = history if history is not None else pd.DataFrame()

    layer_scores = {
        layer: _layer_signal(snapshot, layer) for layer in PROPAGATION_LAYERS
    }
    ordered = sorted(
        layer_scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    origin = ordered[0][0] if ordered[0][1] > 0.05 else "none"
    chain: List[str] = [
        layer for layer, score in ordered if score > 0.08
    ]

    persistence = 0
    if len(history) > 0 and "cascade_severity" in history.columns:
        severities = pd.to_numeric(history["cascade_severity"], errors="coerce").dropna()
        for value in reversed(severities.tolist()):
            if value > 0.20:
                persistence += 1
            else:
                break

    cascade_severity = min(
        1.0,
        sum(layer_scores.values()) / max(len(PROPAGATION_LAYERS), 1),
    )
    if cascade_severity > 0.20:
        persistence += 1

    return {
        "instability_origin": origin,
        "instability_propagation_chain": "->".join(chain) if chain else "none",
        "instability_persistence": persistence,
        "cascade_severity": cascade_severity,
    }


def neutral_instability_exports() -> Dict[str, Any]:
    return {
        "instability_origin": "none",
        "instability_propagation_chain": "none",
        "instability_persistence": 0,
        "cascade_severity": 0.0,
    }
