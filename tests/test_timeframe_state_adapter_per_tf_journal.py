"""S4.1 adapter: per-TF cognition journal, no M15 leak onto H4/H1/M30."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from btc_ml.trading.timeframe_manager import _preview_context_for_open_position
from btc_ml.trading.timeframe_state_adapter import (
    TimeframeSources,
    _lifecycle_from_context_journal,
    resolve_timeframe_state,
)


def _availability() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "evaluation_timestamp": "2026-08-24T04:30:00Z",
                "timeframe": "M15",
                "source_bar_open": "2026-08-24T04:15:00Z",
                "source_bar_close": "2026-08-24T04:30:00Z",
                "source_state_timestamp": "2026-08-24T04:15:00Z",
                "source_event_timestamp": "2026-08-24T04:15:00Z",
                "availability_status": "FRESH_EVENT",
                "availability_reason": "completed_bar_closed_at_or_before_evaluation",
                "is_new_event": True,
                "writer_state": "RUNNING",
            },
            {
                "evaluation_timestamp": "2026-08-24T04:30:00Z",
                "timeframe": "H4",
                "source_bar_open": "2026-08-24T00:00:00Z",
                "source_bar_close": "2026-08-24T04:00:00Z",
                "source_state_timestamp": "2026-08-24T00:00:00Z",
                "source_event_timestamp": "2026-08-24T00:00:00Z",
                "availability_status": "AVAILABLE_LAST_CONFIRMED",
                "availability_reason": "last_completed_bar_available",
                "is_new_event": False,
                "writer_state": "EVENT_DRIVEN",
            },
        ]
    )


def test_tagged_lifecycle_does_not_copy_m15_onto_h4():
    sources = TimeframeSources(
        availability=_availability(),
        lifecycle=pd.DataFrame(
            [
                {
                    "timestamp": "2026-08-24T04:15:00Z",
                    "timeframe": "M15",
                    "active_market_context": "LONG_CONTEXT",
                    "lifecycle_state": "ACTIVE",
                    "context_episode_id": 547,
                    "active_context_started_at": "2026-08-23T22:15:00Z",
                    "context_origin_price": 77668.0,
                },
                {
                    "timestamp": "2026-08-24T00:00:00Z",
                    "timeframe": "H4",
                    "active_market_context": "SHORT_CONTEXT",
                    "lifecycle_state": "ACTIVE",
                    "context_episode_id": 36,
                    "active_context_started_at": "2026-08-24T00:00:00Z",
                    "context_origin_price": 77122.0,
                },
            ]
        ),
    )
    m15 = resolve_timeframe_state(
        timeframe="M15", evaluation_timestamp="2026-08-24T04:30:00Z", sources=sources
    )
    h4 = resolve_timeframe_state(
        timeframe="H4", evaluation_timestamp="2026-08-24T04:30:00Z", sources=sources
    )
    assert m15["timeframe_direction"] == "LONG"
    assert m15["lifecycle_episode_id"] == "M15:547"
    assert h4["timeframe_direction"] == "SHORT"
    assert h4["lifecycle_episode_id"] == "H4:36"
    assert h4["timeframe_state"] == "SHORT_CONTEXT"


def test_journal_rows_are_scoped_by_timeframe(tmp_path: Path):
    journal = tmp_path / "events.jsonl"
    journal.write_text(
        json.dumps(
            {
                "timeframe": "M15",
                "event_type": "CONTEXT_FLIP",
                "new_context": "LONG_CONTEXT",
                "event_timestamp": "2026-08-24T04:15:00Z",
                "lifecycle_episode_id": "M15:547",
                "evidence": {"lifecycle_phase": "ACTIVE"},
            }
        )
        + "\n"
        + json.dumps(
            {
                "timeframe": "H4",
                "event_type": "CONTEXT_START",
                "new_context": "SHORT_CONTEXT",
                "event_timestamp": "2026-08-24T00:00:00Z",
                "lifecycle_episode_id": "H4:36",
                "evidence": {"lifecycle_phase": "ACTIVE"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    frame = _lifecycle_from_context_journal(journal)
    assert frame is not None
    assert set(frame["timeframe"]) == {"M15", "H4"}
    sources = TimeframeSources(availability=_availability(), lifecycle=frame)
    m15 = resolve_timeframe_state(
        timeframe="M15", evaluation_timestamp="2026-08-24T04:30:00Z", sources=sources
    )
    h4 = resolve_timeframe_state(
        timeframe="H4", evaluation_timestamp="2026-08-24T04:30:00Z", sources=sources
    )
    assert m15["lifecycle_episode_id"] == "M15:547"
    assert h4["lifecycle_episode_id"] == "H4:36"
    assert m15["timeframe_direction"] != h4["timeframe_direction"]


def test_untagged_m15_parquet_does_not_leak_onto_h4():
    """Legacy research parquet has no timeframe column — H4 must stay flat."""
    sources = TimeframeSources(
        availability=_availability(),
        lifecycle=pd.DataFrame(
            [
                {
                    "timestamp": "2026-08-24T04:15:00Z",
                    "active_market_context": "LONG_CONTEXT",
                    "lifecycle_state": "ACTIVE",
                    "context_episode_id": 547,
                    "active_context_started_at": "2026-08-23T22:15:00Z",
                    "context_origin_price": 77668.0,
                }
            ]
        ),
        lifecycle_source="parquet",
    )
    m15 = resolve_timeframe_state(
        timeframe="M15", evaluation_timestamp="2026-08-24T04:30:00Z", sources=sources
    )
    h4 = resolve_timeframe_state(
        timeframe="H4", evaluation_timestamp="2026-08-24T04:30:00Z", sources=sources
    )
    assert m15["timeframe_direction"] == "LONG"
    assert m15["lifecycle_episode_id"] == "M15:547"
    assert h4["actionable"] is False
    assert h4["timeframe_direction"] == "NON_DIRECTIONAL"
    assert h4["no_action_reason"] == "NO_LIFECYCLE_ROW_AT_OR_BEFORE_BAR_CLOSE"


def test_challenged_directional_context_is_not_actionable_for_entry():
    sources = TimeframeSources(
        availability=_availability(),
        lifecycle=pd.DataFrame(
            [
                {
                    "timestamp": "2026-08-24T04:15:00Z",
                    "timeframe": "M15",
                    "active_market_context": "LONG_CONTEXT",
                    "lifecycle_state": "CHALLENGED",
                    "context_episode_id": 547,
                    "active_context_started_at": "2026-08-23T22:15:00Z",
                    "context_origin_price": 77668.0,
                }
            ]
        ),
    )
    m15 = resolve_timeframe_state(
        timeframe="M15", evaluation_timestamp="2026-08-24T04:30:00Z", sources=sources
    )
    assert m15["timeframe_direction"] == "LONG"
    assert m15["lifecycle_phase"] == "CHALLENGED"
    assert m15["actionable"] is False
    assert m15["no_action_reason"] == "LIFECYCLE_PHASE_NOT_ACTIONABLE:CHALLENGED"


def test_open_short_holds_through_observe_and_closes_on_long():
    assert _preview_context_for_open_position("SHORT", "OBSERVE") == "SHORT_CONTEXT"
    assert _preview_context_for_open_position("SHORT", "UNKNOWN") == "SHORT_CONTEXT"
    assert _preview_context_for_open_position("SHORT", "LONG_CONTEXT") == "LONG_CONTEXT"
    assert _preview_context_for_open_position("LONG", "OBSERVE") == "LONG_CONTEXT"
    assert _preview_context_for_open_position("LONG", "SHORT_CONTEXT") == "SHORT_CONTEXT"
