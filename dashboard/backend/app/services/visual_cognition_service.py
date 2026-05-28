"""Dashboard service — Visual Cognition replay (Stage 1 MTF)."""

from __future__ import annotations

from typing import Any

from visual_cognition.replay_controller import build_replay_snapshot, list_replay_events


async def get_visual_cognition_snapshot(
    *,
    lookback_days: int = 7,
    max_bars: int = 60,
    timestamp: str | None = None,
    event_index: int | None = None,
) -> dict[str, Any]:
    return build_replay_snapshot(
        lookback_days=lookback_days,
        max_bars=max_bars,
        timestamp=timestamp,
        event_index=event_index,
    )


async def get_visual_cognition_events(*, lookback_days: int = 7) -> dict[str, Any]:
    return list_replay_events(lookback_days=lookback_days)
