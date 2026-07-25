#!/usr/bin/env python3
"""paper_action_clock prefers intrabar event detected_at."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "live"))

from paper_action_clock import (  # noqa: E402
    ACTION_USED_INTRABAR_EVENT_DETECTED_AT,
    CLOCK_FALLBACK_TO_SOURCE_CONTEXT_TS,
    NO_INTRABAR_EVENT_FOR_CONTEXT,
    lookup_intrabar_event_for_source,
    resolve_paper_action_ts,
)


def test_prefers_intrabar_event_over_source():
    out = resolve_paper_action_ts(
        intrabar_event_detected_at="2026-07-21T15:07:00Z",
        decision_available_at="2026-07-21T15:16:00Z",
        source_context_ts="2026-07-21T15:00:00Z",
        intrabar_event_id="ICE_test",
        intrabar_event_provisional=True,
    )
    assert out["paper_action_ts"].startswith("2026-07-21T15:07:00")
    assert out["action_clock_source"] == "intrabar_event_detected_at"
    assert ACTION_USED_INTRABAR_EVENT_DETECTED_AT in out["warnings"]
    assert out["source_context_ts"] == "2026-07-21T15:00:00Z"
    assert out["intrabar_event_id"] == "ICE_test"


def test_fallback_warning_without_intrabar_event():
    out = resolve_paper_action_ts(source_context_ts="2026-07-21T15:00:00Z")
    assert CLOCK_FALLBACK_TO_SOURCE_CONTEXT_TS in out["warnings"]
    assert NO_INTRABAR_EVENT_FOR_CONTEXT in out["warnings"]


def test_lookup_intrabar_event():
    events = pd.DataFrame(
        [
            {
                "source_context_ts": "2026-07-21T15:00:00Z",
                "event_type": "CONTEXT_START",
                "event_detected_at": "2026-07-21T15:07:11Z",
                "event_id": "ICE_1",
                "provisional": True,
            }
        ]
    )
    row = lookup_intrabar_event_for_source(
        events, source_context_ts="2026-07-21T15:00:00Z", event_types=("CONTEXT_START",)
    )
    assert row is not None
    assert str(row["event_detected_at"]).startswith("2026-07-21T15:07:11")
