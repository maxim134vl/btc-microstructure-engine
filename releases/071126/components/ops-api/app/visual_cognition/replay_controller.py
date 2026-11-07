"""Visual cognition replay controller — cursor, event selection, payload assembly."""

from __future__ import annotations

from typing import Any

import pandas as pd

from visual_cognition.behavioral_overlay_engine import build_overlay_series
from visual_cognition.cognition_replay_builder import build_cognition_frame
from visual_cognition.cognition_timeline import build_cognition_timeline
from visual_cognition.colors import COGNITION_COLORS
from visual_cognition.mtf_auction_map import TIMEFRAMES, attach_cognition_to_bars, build_mtf_auction_map
from visual_cognition.ontology_transition_renderer import build_ontology_transitions
from visual_cognition.propagation_tracker import track_propagation
from visual_cognition.stage1_flow_renderer import build_stage1_flow
from parquet_utils import safe_read_parquet


def list_replay_events(*, lookback_days: int = 7) -> dict[str, Any]:
    cognition, _, _ = build_cognition_frame(lookback_days=lookback_days)
    timeline = build_cognition_timeline(cognition, lookback_days=lookback_days)
    return {
        "status": "OK" if timeline else "NO_EVENTS",
        "event_count": len(timeline),
        "events": timeline,
        "lookback_days": lookback_days,
    }


def _resolve_cursor(
    cognition: pd.DataFrame,
    timeline: list[dict[str, Any]],
    *,
    timestamp: str | None,
    event_index: int | None,
) -> pd.Timestamp:
    if event_index is not None:
        for event in timeline:
            if event.get("event_index") == event_index or event.get("timeline_index") == event_index:
                return pd.to_datetime(event["timestamp"])
    if timestamp:
        return pd.to_datetime(timestamp)
    if timeline:
        return pd.to_datetime(timeline[-1]["timestamp"])
    if len(cognition) > 0:
        return cognition["timestamp"].iloc[-1]
    return pd.Timestamp.utcnow()


def _cursor_indices(bars_by_tf: dict[str, list[dict[str, Any]]], cursor: pd.Timestamp) -> dict[str, int | None]:
    indices: dict[str, int | None] = {}
    for tf, bars in bars_by_tf.items():
        index = None
        for idx, bar in enumerate(bars):
            if pd.to_datetime(bar["timestamp"]) <= cursor:
                index = idx
        indices[tf] = index
    return indices


def build_replay_snapshot(
    *,
    lookback_days: int = 7,
    max_bars: int = 60,
    timestamp: str | None = None,
    event_index: int | None = None,
) -> dict[str, Any]:
    """Build full visual cognition replay payload."""

    cognition, candles, mtf_frames = build_cognition_frame(lookback_days=lookback_days)
    if len(candles) == 0:
        return {
            "status": "NO_DATA",
            "message": "No cognition memory available for replay.",
            "colors": COGNITION_COLORS,
        }

    timeline = build_cognition_timeline(cognition, lookback_days=lookback_days)
    cursor = _resolve_cursor(cognition, timeline, timestamp=timestamp, event_index=event_index)

    mtf_map_raw = build_mtf_auction_map(candles, cognition, max_bars=max_bars)
    mtf_map: dict[str, Any] = {}
    bars_by_tf: dict[str, list[dict[str, Any]]] = {}

    for tf in TIMEFRAMES:
        section = mtf_map_raw.get(tf, {})
        raw_bars = section.get("bars") or []
        merged_frame = attach_cognition_to_bars(mtf_frames.get(tf, pd.DataFrame()), cognition)
        enriched_bars = build_overlay_series(merged_frame, raw_bars)
        bars_by_tf[tf] = enriched_bars
        cursor_idx = None
        for idx, bar in enumerate(enriched_bars):
            if pd.to_datetime(bar["timestamp"]) <= cursor:
                cursor_idx = idx
        markers = [bar for bar in enriched_bars if bar.get("behaviors") and bar.get("primary_behavior") != "DORMANT"]
        mtf_map[tf] = {
            **section,
            "bars": enriched_bars,
            "cursor_index": cursor_idx,
            "event_markers": markers[-8:],
        }

    prior_cog = cognition[cognition["timestamp"] <= cursor]
    cognition_row = prior_cog.iloc[-1] if len(prior_cog) else cognition.iloc[-1]

    propagation = track_propagation(cognition, mtf_frames, cursor)
    flow = build_stage1_flow(cognition_row, propagation)

    transitions = safe_read_parquet("state_transition_memory.parquet")
    ontology_markers = build_ontology_transitions(transitions)

    active_event = next(
        (event for event in timeline if pd.to_datetime(event["timestamp"]) == cursor),
        timeline[-1] if timeline else None,
    )

    return {
        "status": "OK",
        "cursor_timestamp": cursor.isoformat(),
        "event_index": active_event.get("event_index") if active_event else None,
        "timeline_index": active_event.get("timeline_index") if active_event else None,
        "lookback_days": lookback_days,
        "timeframes": list(TIMEFRAMES),
        "mtf_map": mtf_map,
        "cursor_indices": _cursor_indices(bars_by_tf, cursor),
        "cognition_flow": flow,
        "propagation": propagation,
        "timeline": timeline,
        "ontology_transitions": ontology_markers[-20:],
        "interpretation": active_event.get("label") if active_event else None,
        "colors": COGNITION_COLORS,
        "meta": {
            "cognition_rows": len(cognition),
            "candle_rows": len(candles),
            "timeline_events": len(timeline),
            "intermediate_events": sum(1 for event in timeline if event.get("source") == "stage2_5_intermediate"),
        },
    }
