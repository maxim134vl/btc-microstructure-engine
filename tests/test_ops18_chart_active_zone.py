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


def test_observe_restart_does_not_stretch_abandoned_start() -> None:
    """H4 STARTs from OBSERVE must not glue into one LONG from Sep 8."""
    events = [
        {
            "context_event_id": "CTX_sep7_short",
            "event_type": "CONTEXT_START",
            "timeframe": "H4",
            "direction": "SHORT",
            "previous_context": "OBSERVE",
            "event_timestamp": "2026-09-07T15:31:27.627726Z",
            "lifecycle_episode_id": "H4:prov:2",
        },
        {
            "context_event_id": "CTX_sep8_long",
            "event_type": "CONTEXT_START",
            "timeframe": "H4",
            "direction": "LONG",
            "previous_context": "OBSERVE",
            "event_timestamp": "2026-09-08T00:40:41.889883Z",
            "lifecycle_episode_id": "H4:prov:6",
        },
        {
            "context_event_id": "CTX_sep9_long",
            "event_type": "CONTEXT_START",
            "timeframe": "H4",
            "direction": "LONG",
            "previous_context": "OBSERVE",
            "event_timestamp": "2026-09-09T16:31:48.327372Z",
            "lifecycle_episode_id": "H4:prov:8",
        },
        {
            "context_event_id": "CTX_sep10_start",
            "event_type": "CONTEXT_START",
            "timeframe": "H4",
            "direction": "LONG",
            "previous_context": "OBSERVE",
            "event_timestamp": "2026-09-10T01:08:39.450843Z",
            "lifecycle_episode_id": "H4:prov:2",
        },
        {
            "context_event_id": "CTX_sep10_end",
            "event_type": "CONTEXT_END",
            "timeframe": "H4",
            "direction": "LONG",
            "previous_context": "LONG_CONTEXT",
            "event_timestamp": "2026-09-10T04:00:00.038397Z",
            "lifecycle_episode_id": "H4:prov:2",
        },
    ]
    zones = build_context_zones_from_events(events)
    assert len(zones) == 1
    assert zones[0]["lifecycle_episode_id"] == "H4:prov:2"
    assert zones[0]["start_timestamp"] == "2026-09-10T01:08:39.450843Z"
    assert zones[0]["end_timestamp"] == "2026-09-10T04:00:00.038397Z"
    assert zones[0]["active"] is False
    assert zones[0]["end_reason"] == "CONTEXT_END"


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


def test_lifecycle_parquet_zones_are_tf_isolated_and_drop_observe() -> None:
    import pandas as pd
    from timeframe_chart_truth import build_context_zones_from_lifecycle_parquet

    frame = pd.DataFrame(
        [
            {
                "episode_id": 10,
                "timeframe": "M15",
                "active_market_context": "LONG_CONTEXT",
                "start_time": pd.Timestamp("2026-09-09T04:00:00Z"),
                "end_time": pd.Timestamp("2026-09-09T05:00:00Z"),
                "start_close": 78700.0,
                "end_lifecycle_state": "ACTIVE",
                "dominant_lifecycle_state": "ACTIVE",
                "end_reason": "confirmed opposite",
            },
            {
                "episode_id": 11,
                "timeframe": "M15",
                "active_market_context": "LONG_CONTEXT",
                "start_time": pd.Timestamp("2026-09-09T05:00:00Z"),
                "end_time": pd.Timestamp("2026-09-09T06:00:00Z"),
                "start_close": 78800.0,
                "end_lifecycle_state": "CHALLENGED",
                "dominant_lifecycle_state": "ACTIVE",
                "end_reason": "latest open lifecycle episode",
            },
            {
                "episode_id": 88,
                "timeframe": "M30",
                "active_market_context": "LONG_CONTEXT",
                "start_time": pd.Timestamp("2026-09-09T04:30:00Z"),
                "end_time": pd.Timestamp("2026-09-09T06:00:00Z"),
                "start_close": 78850.0,
                "end_lifecycle_state": "ACTIVE",
                "dominant_lifecycle_state": "ACTIVE",
                "end_reason": "latest open lifecycle episode",
            },
            {
                "episode_id": 57,
                "timeframe": "H1",
                "active_market_context": "OBSERVE",
                "start_time": pd.Timestamp("2026-09-08T19:30:00Z"),
                "end_time": pd.Timestamp("2026-09-09T06:00:00Z"),
                "start_close": 78400.0,
                "end_lifecycle_state": "NO_ACTIVE_CONTEXT",
                "dominant_lifecycle_state": "NO_ACTIVE_CONTEXT",
                "end_reason": "latest open lifecycle episode",
            },
        ]
    )
    window_start = pd.Timestamp("2026-09-02T00:00:00Z")
    window_end = pd.Timestamp("2026-09-09T06:30:00Z")
    m15 = build_context_zones_from_lifecycle_parquet(
        "M15", window_start=window_start, window_end=window_end, frame=frame
    )
    m30 = build_context_zones_from_lifecycle_parquet(
        "M30", window_start=window_start, window_end=window_end, frame=frame
    )
    h1 = build_context_zones_from_lifecycle_parquet(
        "H1", window_start=window_start, window_end=window_end, frame=frame
    )
    assert [z["lifecycle_episode_id"] for z in m15] == ["M15:10", "M15:11"]
    assert m15[0]["end_timestamp"] is not None
    assert m15[1]["end_timestamp"] is not None
    assert m15[1]["active"] is False
    assert [z["lifecycle_episode_id"] for z in m30] == ["M30:88"]
    assert h1 == []


def test_lifecycle_memory_zones_are_per_tf_and_collapse_runs() -> None:
    import pandas as pd
    from timeframe_chart_truth import build_context_zones_from_lifecycle_memory

    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "timeframe": "M15",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 10,
                "close": 100.0,
            },
            {
                "timestamp": pd.Timestamp("2026-09-09T04:15:00Z"),
                "timeframe": "M15",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 10,
                "close": 101.0,
            },
            {
                "timestamp": pd.Timestamp("2026-09-09T04:30:00Z"),
                "timeframe": "M15",
                "active_market_context": "OBSERVE",
                "lifecycle_state": "NO_ACTIVE_CONTEXT",
                "context_episode_id": 10,
                "close": 102.0,
            },
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "timeframe": "H4",
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 3,
                "close": 99.0,
            },
        ]
    )
    window_start = pd.Timestamp("2026-09-09T00:00:00Z")
    window_end = pd.Timestamp("2026-09-09T08:00:00Z")
    m15 = build_context_zones_from_lifecycle_memory(
        "M15", window_start=window_start, window_end=window_end, frame=frame
    )
    h4 = build_context_zones_from_lifecycle_memory(
        "H4", window_start=window_start, window_end=window_end, frame=frame
    )
    m30 = build_context_zones_from_lifecycle_memory(
        "M30", window_start=window_start, window_end=window_end, frame=frame
    )
    assert [z["lifecycle_episode_id"] for z in m15] == ["M15:10"]
    assert m15[0]["direction"] == "LONG"
    assert m15[0]["end_timestamp"] == "2026-09-09T04:30:00Z"
    assert m15[0]["active"] is False
    assert m15[0]["source"] == "market_context_lifecycle_memory"
    assert [z["lifecycle_episode_id"] for z in h4] == ["H4:3"]
    assert h4[0]["direction"] == "SHORT"
    assert h4[0]["active"] is True
    assert h4[0]["end_timestamp"] is None
    assert m30 == []


def test_untagged_lifecycle_memory_does_not_paint_h1() -> None:
    import pandas as pd
    from timeframe_chart_truth import build_context_zones_from_lifecycle_memory

    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 99,
            }
        ]
    )
    window_start = pd.Timestamp("2026-09-09T00:00:00Z")
    window_end = pd.Timestamp("2026-09-09T08:00:00Z")
    m15 = build_context_zones_from_lifecycle_memory(
        "M15", window_start=window_start, window_end=window_end, frame=frame
    )
    h1 = build_context_zones_from_lifecycle_memory(
        "H1", window_start=window_start, window_end=window_end, frame=frame
    )
    assert [z["lifecycle_episode_id"] for z in m15] == ["M15:99"]
    assert h1 == []


def test_lifecycle_memory_tip_is_scoped_per_tf() -> None:
    import pandas as pd
    from timeframe_chart_truth import load_lifecycle_memory_tip

    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "timeframe": "M15",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 10,
            },
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "timeframe": "H1",
                "active_market_context": "OBSERVE",
                "lifecycle_state": "NO_ACTIVE_CONTEXT",
                "context_episode_id": 2,
            },
        ]
    )
    m15 = load_lifecycle_memory_tip("M15", frame=frame)
    h1 = load_lifecycle_memory_tip("H1", frame=frame)
    assert m15["directional_state"] == "LONG_CONTEXT"
    assert m15["lifecycle_episode_id"] == "M15:10"
    assert h1["directional_state"] == "OBSERVE"
    assert h1["timeframe_direction"] == "NONE"


def test_lifecycle_parquet_zones_dedupe_snapshot_log() -> None:
    import pandas as pd
    from timeframe_chart_truth import build_context_zones_from_lifecycle_parquet

    frame = pd.DataFrame(
        [
            {
                "episode_id": 88,
                "timeframe": "M30",
                "active_market_context": "SHORT_CONTEXT",
                "start_time": pd.Timestamp("2026-09-09T02:00:00Z"),
                "end_time": pd.Timestamp("2026-09-09T03:00:00Z"),
                "start_close": 78500.0,
                "end_lifecycle_state": "CHALLENGED",
                "end_reason": "latest open lifecycle episode",
            },
            {
                "episode_id": 88,
                "timeframe": "M30",
                "active_market_context": "SHORT_CONTEXT",
                "start_time": pd.Timestamp("2026-09-09T02:00:00Z"),
                "end_time": pd.Timestamp("2026-09-09T03:30:00Z"),
                "start_close": 78500.0,
                "end_lifecycle_state": "CHALLENGED",
                "end_reason": "latest open lifecycle episode",
            },
            {
                "episode_id": 88,
                "timeframe": "M30",
                "active_market_context": "LONG_CONTEXT",
                "start_time": pd.Timestamp("2026-09-09T04:00:00Z"),
                "end_time": pd.Timestamp("2026-09-09T06:00:00Z"),
                "start_close": 78850.0,
                "end_lifecycle_state": "ACTIVE",
                "end_reason": "latest open lifecycle episode",
            },
        ]
    )
    zones = build_context_zones_from_lifecycle_parquet(
        "M30",
        window_start=pd.Timestamp("2026-09-02T00:00:00Z"),
        window_end=pd.Timestamp("2026-09-09T06:30:00Z"),
        frame=frame,
    )
    assert len(zones) == 2
    assert zones[0]["direction"] == "SHORT"
    assert zones[0]["end_timestamp"] == "2026-09-09T03:30:00Z"
    assert zones[1]["direction"] == "LONG"
    assert zones[1]["end_timestamp"] == "2026-09-09T06:00:00Z"
    assert zones[1]["active"] is False


def test_journal_entry_source_paints_journal_not_parquet() -> None:
    from timeframe_chart_truth import (
        build_context_zones_from_events,
        context_band_source,
        paper_entry_source,
        select_live_context_zones,
    )

    journal_zones = build_context_zones_from_events(
        [
            {
                "context_event_id": "CTX_h4_start",
                "event_type": "CONTEXT_START",
                "timeframe": "H4",
                "direction": "LONG",
                "event_timestamp": "2026-09-10T01:08:39.450843Z",
                "zone_timestamp": "2026-09-10T01:08:39.450843Z",
                "lifecycle_episode_id": "H4:prov:2",
            },
            {
                "context_event_id": "CTX_h4_end",
                "event_type": "CONTEXT_END",
                "timeframe": "H4",
                "direction": "LONG",
                "event_timestamp": "2026-09-10T04:00:00.038397Z",
                "zone_timestamp": "2026-09-10T04:00:00.038397Z",
                "lifecycle_episode_id": "H4:prov:2",
            },
        ]
    )
    parquet_zones = [
        {
            "timeframe": "H4",
            "direction": "SHORT",
            "directional_state": "SHORT_CONTEXT",
            "start_timestamp": "2026-09-09T12:00:00Z",
            "end_timestamp": "2026-09-10T00:00:00Z",
            "lifecycle_episode_id": "H4:27",
            "source": "market_context_lifecycle_episodes",
            "active": False,
        }
    ]
    painted = select_live_context_zones(
        live1b=True,
        entry_source="context_journal",
        journal_zones=journal_zones,
        parquet_zones=parquet_zones,
        parquet_available=True,
    )
    assert painted is journal_zones
    assert painted[0]["lifecycle_episode_id"] == "H4:prov:2"
    assert painted[0]["start_timestamp"] == "2026-09-10T01:08:39.450843Z"
    assert painted[0]["end_timestamp"] == "2026-09-10T04:00:00.038397Z"
    s41 = select_live_context_zones(
        live1b=True,
        entry_source="s41_command_bus",
        journal_zones=journal_zones,
        parquet_zones=parquet_zones,
        parquet_available=True,
    )
    assert s41 is parquet_zones
    assert context_band_source(live1b=True, entry_source="context_journal") == (
        "LIVE1A_INTRABAR_CONTEXT_JOURNAL"
    )
    assert context_band_source(live1b=True, entry_source="s41_command_bus") == (
        "market_context_lifecycle_episodes"
    )
    assert paper_entry_source() in {"context_journal", "s41_command_bus"}


def test_paper_entry_source_prefers_overlay(tmp_path, monkeypatch) -> None:
    from timeframe_chart_truth import paper_entry_source
    import timeframe_chart_truth as tct

    overlay = tmp_path / "overlay.json"
    config = tmp_path / "config.json"
    overlay.write_text('{"entry_source": "context_journal"}\n', encoding="utf-8")
    config.write_text('{"entry_source": "s41_command_bus"}\n', encoding="utf-8")
    monkeypatch.setattr(tct, "PAPER_EXECUTION_OVERLAY", overlay)
    monkeypatch.setattr(tct, "PAPER_EXECUTION_CONFIG", config)
    assert paper_entry_source() == "context_journal"


def test_observe_memory_does_not_fall_back_to_episode_long() -> None:
    import pandas as pd
    from timeframe_chart_truth import select_lifecycle_chart_zones

    memory = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "timeframe": "H1",
                "active_market_context": "OBSERVE",
                "lifecycle_state": "NO_ACTIVE_CONTEXT",
                "context_episode_id": 2,
            }
        ]
    )
    episode_zones = [
        {
            "timeframe": "H1",
            "direction": "LONG",
            "directional_state": "LONG_CONTEXT",
            "start_timestamp": "2026-09-09T00:00:00Z",
            "end_timestamp": "2026-09-09T04:00:00Z",
            "lifecycle_episode_id": "H1:99",
            "source": "market_context_lifecycle_episodes",
            "active": False,
        }
    ]
    assert (
        select_lifecycle_chart_zones(
            "H1",
            memory_zones=[],
            episode_zones=episode_zones,
            memory_frame=memory,
        )
        == []
    )
    assert select_lifecycle_chart_zones(
        "M30",
        memory_zones=[],
        episode_zones=episode_zones,
        memory_frame=memory,
    ) == episode_zones


def test_untagged_memory_covers_m15_only() -> None:
    import pandas as pd
    from timeframe_chart_truth import lifecycle_memory_covers_timeframe

    frame = pd.DataFrame(
        [{"timestamp": pd.Timestamp("2026-09-09T04:00:00Z"), "active_market_context": "LONG_CONTEXT"}]
    )
    assert lifecycle_memory_covers_timeframe("M15", frame=frame) is True
    assert lifecycle_memory_covers_timeframe("H4", frame=frame) is False


def test_stale_tip_is_not_stretched_across_visible_window() -> None:
    from timeframe_chart_truth import ensure_tip_active_context_zone

    out = ensure_tip_active_context_zone(
        [],
        tip_active="SHORT_CONTEXT",
        tip_lifecycle="ACTIVE",
        tip_episode_id="M15:560",
        tip_timestamp="2026-08-25T20:30:00Z",
        timeframe="M15",
        window_start="2026-09-06T14:00:00Z",
    )
    assert out == []


def test_s41_paints_independent_memory_on_all_timeframes() -> None:
    import pandas as pd
    from timeframe_chart_truth import (
        TIMEFRAMES,
        build_context_zones_from_lifecycle_memory,
        fill_observe_context_zones,
        select_lifecycle_chart_zones,
        select_live_context_zones,
    )

    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "timeframe": "M15",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 1,
                "close": 100.0,
            },
            {
                "timestamp": pd.Timestamp("2026-09-09T04:15:00Z"),
                "timeframe": "M15",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 1,
                "close": 101.0,
            },
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "timeframe": "M30",
                "active_market_context": "OBSERVE",
                "lifecycle_state": "NO_ACTIVE_CONTEXT",
                "context_episode_id": 2,
                "close": 100.0,
            },
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "timeframe": "H1",
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 3,
                "close": 99.0,
            },
            {
                "timestamp": pd.Timestamp("2026-09-09T04:00:00Z"),
                "timeframe": "H4",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 4,
                "close": 98.0,
            },
        ]
    )
    window_start = pd.Timestamp("2026-09-09T00:00:00Z")
    window_end = pd.Timestamp("2026-09-09T08:00:00Z")
    journal_ghost = [
        {
            "timeframe": "H4",
            "direction": "SHORT",
            "directional_state": "SHORT_CONTEXT",
            "start_timestamp": "2026-09-09T01:00:00Z",
            "end_timestamp": None,
            "active": True,
            "lifecycle_episode_id": "H4:prov:1",
            "source": "LIVE1A_INTRABAR_CONTEXT_JOURNAL",
        }
    ]
    expected = {"M15": "LONG", "M30": None, "H1": "SHORT", "H4": "LONG"}
    for tf in TIMEFRAMES:
        memory_zones = build_context_zones_from_lifecycle_memory(
            tf, window_start=window_start, window_end=window_end, frame=frame
        )
        lifecycle_zones = select_lifecycle_chart_zones(
            tf,
            memory_zones=memory_zones,
            episode_zones=journal_ghost,
            memory_frame=frame,
        )
        painted = select_live_context_zones(
            live1b=True,
            entry_source="s41_command_bus",
            journal_zones=journal_ghost,
            parquet_zones=lifecycle_zones,
            parquet_available=True,
        )
        tip = memory_zones[0]["directional_state"] if memory_zones else "OBSERVE"
        filled = fill_observe_context_zones(
            painted,
            timeframe=tf,
            window_start="2026-09-09T00:00:00Z",
            window_end="2026-09-09T08:00:00Z",
            tip_context=tip,
        )
        sources = {z.get("source") for z in filled}
        ids = {z.get("lifecycle_episode_id") for z in filled}
        dirs = {z.get("direction") for z in filled if z.get("direction") in {"LONG", "SHORT"}}
        assert "LIVE1A_INTRABAR_CONTEXT_JOURNAL" not in sources
        assert "H4:prov:1" not in ids
        want = expected[tf]
        if want is None:
            assert dirs == set()
            assert all(z.get("directional_state") == "OBSERVE" for z in filled)
        else:
            assert dirs == {want}
            for zone in filled:
                if zone.get("source") == "CANONICAL_VISUAL_OBSERVE_GAP":
                    continue
                assert str(zone.get("lifecycle_episode_id") or "").startswith(f"{tf}:")

