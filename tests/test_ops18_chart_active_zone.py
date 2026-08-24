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


def test_foreign_context_end_does_not_close_newer_episode() -> None:
    events = [
        {
            "context_event_id": "CTX_old_start",
            "event_type": "CONTEXT_START",
            "timeframe": "M15",
            "direction": "LONG",
            "event_timestamp": "2026-08-13T16:30:00Z",
            "lifecycle_episode_id": "1015.0",
        },
        {
            "context_event_id": "CTX_new_start",
            "event_type": "CONTEXT_START",
            "timeframe": "M15",
            "direction": "LONG",
            "event_timestamp": "2026-08-14T18:00:00Z",
            "lifecycle_episode_id": "1023.0",
        },
        {
            "context_event_id": "CTX_stale_end",
            "event_type": "CONTEXT_END",
            "timeframe": "M15",
            "direction": "LONG",
            "event_timestamp": "2026-08-15T07:23:45.922207Z",
            "lifecycle_episode_id": "1015.0",
        },
    ]
    zones = build_context_zones_from_events(events)
    assert len(zones) == 2
    assert zones[0]["lifecycle_episode_id"] == "1015.0"
    assert zones[0]["active"] is False
    assert zones[1]["lifecycle_episode_id"] == "1023.0"
    assert zones[1]["active"] is True
    assert zones[1]["end_timestamp"] is None


def test_tip_reopens_zone_closed_by_stale_end() -> None:
    from timeframe_chart_truth import ensure_tip_active_context_zone

    zones = [
        {
            "timeframe": "M15",
            "direction": "LONG",
            "directional_state": "LONG_CONTEXT",
            "start_timestamp": "2026-08-14T18:00:00Z",
            "end_timestamp": "2026-08-15T07:23:45Z",
            "lifecycle_episode_id": "1023.0",
            "active": False,
            "lifecycle_state": "ACTIVE",
        }
    ]
    out = ensure_tip_active_context_zone(
        zones,
        tip_active="LONG_CONTEXT",
        tip_lifecycle="ACTIVE",
        tip_episode_id="1023",
        tip_timestamp="2026-08-15T08:15:00Z",
        timeframe="M15",
    )
    assert len(out) == 1
    assert out[0]["active"] is True
    assert out[0]["end_timestamp"] is None
    assert out[0].get("reopened_for_tip") is True


def test_visual_overlay_prefers_active_over_provisional_observe() -> None:
    directional, direction = _map_live1a_visual_context(
        "OBSERVE",
        "CHALLENGED",
        active_market_context="LONG_CONTEXT",
    )
    assert directional == "LONG_CONTEXT"
    assert direction == "LONG"


def test_zone_edges_use_source_bar_not_reused_origin() -> None:
    """FLIP events that reuse context-origin timestamps must still paint causally."""
    events = [
        {
            "context_event_id": "CTX_short",
            "event_type": "CONTEXT_FLIP",
            "timeframe": "M15",
            "direction": "SHORT",
            "event_timestamp": "2026-08-24T03:15:00Z",
            "zone_timestamp": "2026-08-24T03:45:00Z",
            "source_bar_timestamp": "2026-08-24T03:45:00Z",
            "lifecycle_episode_id": "548.0",
        },
        {
            "context_event_id": "CTX_long",
            "event_type": "CONTEXT_START",
            "timeframe": "M15",
            "direction": "LONG",
            # Origin stays at episode start; decision bar is later.
            "event_timestamp": "2026-08-23T22:15:00Z",
            "zone_timestamp": "2026-08-24T05:00:00Z",
            "source_bar_timestamp": "2026-08-24T05:00:00Z",
            "lifecycle_episode_id": "547.0",
        },
    ]
    zones = build_context_zones_from_events(events)
    assert len(zones) == 2
    assert zones[0]["direction"] == "SHORT"
    assert zones[0]["active"] is False
    assert zones[0]["end_timestamp"] == "2026-08-24T05:00:00Z"
    assert zones[1]["direction"] == "LONG"
    assert zones[1]["active"] is True
    assert zones[1]["start_timestamp"] == "2026-08-24T05:00:00Z"
    assert zones[1]["end_timestamp"] is None


def test_tip_reopen_closes_opposite_active_zone() -> None:
    from timeframe_chart_truth import ensure_tip_active_context_zone

    zones = [
        {
            "timeframe": "M15",
            "direction": "LONG",
            "directional_state": "LONG_CONTEXT",
            "start_timestamp": "2026-08-23T22:15:00Z",
            "end_timestamp": "2026-08-24T03:15:00Z",
            "lifecycle_episode_id": "547.0",
            "active": False,
            "lifecycle_state": "ACTIVE",
        },
        {
            "timeframe": "M15",
            "direction": "SHORT",
            "directional_state": "SHORT_CONTEXT",
            "start_timestamp": "2026-08-24T03:15:00Z",
            "end_timestamp": None,
            "lifecycle_episode_id": "548.0",
            "active": True,
            "lifecycle_state": "ACTIVE",
        },
    ]
    out = ensure_tip_active_context_zone(
        zones,
        tip_active="LONG_CONTEXT",
        tip_lifecycle="ACTIVE",
        tip_episode_id="547.0",
        tip_timestamp="2026-08-24T08:00:00Z",
        timeframe="M15",
    )
    actives = [z for z in out if z.get("active")]
    assert len(actives) == 1
    assert actives[0]["direction"] == "LONG"
    assert actives[0]["end_timestamp"] is None
    short = next(z for z in out if z["direction"] == "SHORT")
    assert short["active"] is False
    assert short["end_timestamp"] is not None
