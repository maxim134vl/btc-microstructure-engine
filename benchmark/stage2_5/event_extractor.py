"""Extract Stage 2.5 intermediate cognition events for validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet

PHASE1_STATES = (
    "IC_CONTINUATION_WEAKENING",
    "IC_INITIATIVE_DETERIORATION",
    "IC_ROTATIONAL_PRESSURE",
)


def extract_intermediate_events(
    *,
    lookback_days: int | None = 7,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load intermediate cognition memory rows within the validation window."""

    frame = safe_read_parquet("intermediate_cognition_memory.parquet")
    if len(frame) == 0:
        return frame

    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    frame = frame[frame["intermediate_state"].isin(PHASE1_STATES)]

    if start is not None:
        frame = frame[frame["timestamp"] >= pd.Timestamp(start)]
    if end is not None:
        frame = frame[frame["timestamp"] <= pd.Timestamp(end)]

    if lookback_days is not None and start is None and end is None and len(frame) > 0:
        cutoff = frame["timestamp"].max() - pd.Timedelta(days=lookback_days)
        frame = frame[frame["timestamp"] >= cutoff]

    frame = frame.reset_index(drop=True)
    frame["event_index"] = range(1, len(frame) + 1)
    return frame


def event_narration(row: pd.Series) -> str:
    state = row.get("intermediate_state")
    severity = row.get("severity")
    anchor = row.get("anchor_stage2_state")
    reason = row.get("reason")
    return (
        f"Intermediate cognition: {state} ({severity}) anchored to {anchor}. "
        f"{reason or 'Context narration only — no trade signal.'}"
    )


def event_context(row: pd.Series) -> dict[str, Any]:
    return {
        "intermediate_state": row.get("intermediate_state"),
        "severity": row.get("severity"),
        "confidence": row.get("confidence"),
        "anchor_stage2_state": row.get("anchor_stage2_state"),
        "anchor_timestamp": row.get("anchor_timestamp"),
        "reason": row.get("reason"),
        "source_layers": row.get("source_layers"),
    }
