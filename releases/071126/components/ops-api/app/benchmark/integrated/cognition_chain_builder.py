"""Build full cognition chains: perception → reasoning → outcome context."""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchmark.stage1.event_extractor import event_to_interpretation
from benchmark.stage2.reasoning_extractor import extract_reasoning_events, reasoning_context


def _perception_summary(row: pd.Series) -> str:
    inputs = row.get("stage1_inputs") or []
    if isinstance(inputs, list) and inputs:
        return ", ".join(str(item) for item in inputs)
    return event_to_interpretation(row)


def build_cognition_chains(lookback_days: int = 7) -> list[dict[str, Any]]:
    """Return integrated cognition chain records anchored on Stage 2 reasoning events."""

    events = extract_reasoning_events(lookback_days=lookback_days)
    if len(events) == 0:
        return []

    chains: list[dict[str, Any]] = []
    for _, row in events.iterrows():
        inputs = row.get("stage1_inputs") or []
        chains.append(
            {
                "event_index": int(row.get("event_index", 0)),
                "timestamp": str(row["timestamp"]),
                "row": row,
                "stage1_perception": inputs if isinstance(inputs, list) else [str(inputs)],
                "stage1_perception_text": _perception_summary(row),
                "stage2_interpretation": row.get("stage2_interpretation"),
                "context": reasoning_context(row),
            }
        )
    return chains
