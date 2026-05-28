"""Render ontology transition markers for visual replay."""

from __future__ import annotations

from typing import Any

import pandas as pd


def build_ontology_transitions(transitions: pd.DataFrame, *, limit: int = 100) -> list[dict[str, Any]]:
    """Extract non-stable state transitions for timeline overlays."""

    if len(transitions) == 0:
        return []

    frame = transitions.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")

    if "transition_state" in frame.columns:
        frame = frame[frame["transition_state"].notna()]
        frame = frame[frame["transition_state"] != "STABLE_STATE"]
    if "previous_state" in frame.columns and "current_state" in frame.columns:
        frame = frame[frame["previous_state"] != frame["current_state"]]

    markers: list[dict[str, Any]] = []
    for _, row in frame.tail(limit).iterrows():
        markers.append(
            {
                "timestamp": row["timestamp"].isoformat(),
                "transition_state": row.get("transition_state"),
                "previous_state": row.get("previous_state"),
                "current_state": row.get("current_state"),
                "previous_regime": row.get("previous_regime"),
                "current_regime": row.get("current_regime"),
                "label": f"{row.get('previous_state')} → {row.get('current_state')}",
            }
        )
    return markers
