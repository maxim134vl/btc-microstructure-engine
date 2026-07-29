"""OPS1.8 chart zone continues through provisional OBSERVE while journal START is open."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))

from timeframe_chart_truth import (  # noqa: E402
    build_context_zones_from_events,
    _map_live1a_visual_context,
)


def test_chart_zone_stays_open_without_context_end() -> None:
    events = [
        {
            "context_event_id": "CTX_d25",
            "event_type": "CONTEXT_START",
            "timeframe": "H4",
            "direction": "LONG",
            "event_timestamp": "2026-07-29T09:40:34.724226Z",
            "lifecycle_episode_id": "H4:prov:1",
            "context_price": 64690.19,
            "bar_anchor_time": "2026-07-29T08:00:00Z",
        }
    ]
    zones = build_context_zones_from_events(events)
    assert len(zones) == 1
    assert zones[0]["active"] is True
    assert zones[0]["end_timestamp"] is None
    assert zones[0]["direction"] == "LONG"


def test_visual_overlay_prefers_active_over_provisional_observe() -> None:
    directional, direction = _map_live1a_visual_context(
        "OBSERVE",
        "CHALLENGED",
        active_market_context="LONG_CONTEXT",
    )
    assert directional == "LONG_CONTEXT"
    assert direction == "LONG"
