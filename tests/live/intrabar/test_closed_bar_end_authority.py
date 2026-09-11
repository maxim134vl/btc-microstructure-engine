"""Closed-bar book is idea-death authority for journal CONTEXT_END.

Anti-Saw is not in this path. It remains a trade filter on S41 only.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from btc_ml.live.intrabar.closed_bar_context_authority import (
    ClosedBarContextAuthority,
    closed_bar_still_directional,
    closed_bar_tip_is_current,
)
from btc_ml.live.intrabar.cognition_pipeline import IntrabarCognitionEngine
from btc_ml.live.intrabar.context_event_freshness import is_provisional_context_end
from btc_ml.live.intrabar.context_event_journal import ContextEventJournal
from btc_ml.live.intrabar.event_time_lifecycle import (
    hold_provisional_end_for_closed_bar,
    retain_directional_lifecycle,
)


def _trade(price: str, ts: str, mono: int, tid: int) -> dict:
    return {
        "price": price,
        "quantity": "0.01",
        "quote_quantity": str(float(price) * 0.01),
        "exchange_trade_timestamp": ts,
        "local_receive_timestamp": ts,
        "local_receive_monotonic_ns": mono,
        "aggregate_trade_id": tid,
        "buyer_is_market_maker": False,
        "connection_session_id": "sess",
        "reconnect_generation": 1,
    }


def test_closed_bar_directional_gate_is_not_anti_saw():
    assert closed_bar_still_directional("LONG_CONTEXT") is True
    assert closed_bar_still_directional("SHORT") is True
    assert closed_bar_still_directional("OBSERVE") is False
    assert closed_bar_still_directional(None) is False
    assert hold_provisional_end_for_closed_bar(closed_bar_active="LONG_CONTEXT") is True
    assert hold_provisional_end_for_closed_bar(closed_bar_active="OBSERVE") is False
    assert hold_provisional_end_for_closed_bar(closed_bar_active=None) is False
    assert (
        hold_provisional_end_for_closed_bar(
            closed_bar_active="OBSERVE",
            closed_bar_timestamp="2026-09-11T08:45:00Z",
            event_timestamp="2026-09-11T09:45:00.011286Z",
            timeframe="M15",
        )
        is True
    )
    assert (
        hold_provisional_end_for_closed_bar(
            closed_bar_active="OBSERVE",
            closed_bar_timestamp="2026-09-11T09:30:00Z",
            event_timestamp="2026-09-11T09:45:00.011286Z",
            timeframe="M15",
        )
        is False
    )


def test_retain_keeps_prev_active_and_marks_challenged():
    prev = {
        "active_market_context": "LONG_CONTEXT",
        "lifecycle_state": "ACTIVE",
        "active_context_started_at": pd.Timestamp("2026-08-17T10:59:00Z"),
        "active_context_age_bars": 4,
    }
    killed = {
        "active_market_context": "OBSERVE",
        "lifecycle_state": "INVALIDATED",
        "invalidation_type": "THESIS_REJECTION",
    }
    out = retain_directional_lifecycle(
        prev,
        killed,
        hold_reason="provisional CONTEXT_END held: closed-bar still LONG_CONTEXT",
    )
    assert out["active_market_context"] == "LONG_CONTEXT"
    assert out["lifecycle_state"] == "CHALLENGED"
    assert out["_provisional_end_held"] is True
    assert out["active_context_started_at"] == prev["active_context_started_at"]


def test_provisional_end_flattens_only_when_closed_bar_confirms():
    flicker = {
        "event_type": "CONTEXT_END",
        "evaluation_mode": "PROVISIONAL_INTRABAR",
    }
    confirmed = {
        "event_type": "CONTEXT_END",
        "evaluation_mode": "PROVISIONAL_INTRABAR",
        "closed_bar_confirms_end": True,
    }
    assert is_provisional_context_end(flicker) is True
    assert is_provisional_context_end(confirmed) is False


def test_authority_reads_latest_row_per_tf(tmp_path: Path):
    frame = pd.DataFrame(
        [
            {
                "timestamp": "2026-08-17T10:00:00Z",
                "timeframe": "M15",
                "active_market_context": "OBSERVE",
            },
            {
                "timestamp": "2026-08-17T10:15:00Z",
                "timeframe": "M15",
                "active_market_context": "LONG_CONTEXT",
            },
            {
                "timestamp": "2026-08-17T08:00:00Z",
                "timeframe": "H4",
                "active_market_context": "SHORT_CONTEXT",
            },
        ]
    )
    path = tmp_path / "market_context_lifecycle_memory.parquet"
    frame.to_parquet(path, index=False)
    auth = ClosedBarContextAuthority(path)
    assert auth.active_market_context("M15") == "LONG_CONTEXT"
    assert auth.still_directional("M15") is True
    assert auth.tip_timestamp("M15") == pd.Timestamp("2026-08-17T10:15:00Z", tz="UTC")
    assert auth.active_market_context("H4") == "SHORT_CONTEXT"
    assert auth.known("M30") is False


def test_journal_does_not_emit_end_while_closed_bar_is_long(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    journal = ContextEventJournal(tmp_path)
    authority = ClosedBarContextAuthority(snapshot={"M15": "LONG_CONTEXT"})
    engine = IntrabarCognitionEngine(
        context_journal=journal,
        closed_bar_authority=authority,
    )
    engine.lifecycle_prev["M15"] = {
        "active_market_context": "LONG_CONTEXT",
        "lifecycle_state": "ACTIVE",
        "active_context_started_at": pd.Timestamp("2026-08-17T10:59:00Z"),
        "evaluation_mode": "PROVISIONAL_INTRABAR",
    }
    engine._active_episode["M15"] = "M15:prov:1"

    monkeypatch.setattr(
        "btc_ml.live.intrabar.cognition_pipeline.synthesize_provisional_state",
        lambda **_k: {
            "market_context": "OBSERVE",
            "context_status": "INVALIDATED",
            "auction_episode": "BALANCE",
            "decision_evidence": {},
        },
    )
    monkeypatch.setattr(
        "btc_ml.live.intrabar.cognition_pipeline.step_event_time_lifecycle",
        lambda **_k: {
            "active_market_context": "OBSERVE",
            "lifecycle_state": "INVALIDATED",
            "invalidation_type": "THESIS_REJECTION",
            "evaluation_mode": "PROVISIONAL_INTRABAR",
        },
    )

    emitted = engine.on_agg_trade(_trade("77000", "2026-08-17T11:00:00.500Z", 1_000, 1))
    ends = [e for e in emitted if e.get("event_type") == "CONTEXT_END" and e.get("timeframe") == "M15"]
    assert ends == []
    assert engine.end_holds >= 1
    assert engine.lifecycle_prev["M15"]["active_market_context"] == "LONG_CONTEXT"
    assert engine._active_episode["M15"] == "M15:prov:1"


def test_journal_emits_confirmed_end_when_closed_bar_is_observe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    journal = ContextEventJournal(tmp_path)
    authority = ClosedBarContextAuthority(snapshot={"M15": "OBSERVE"})
    engine = IntrabarCognitionEngine(
        context_journal=journal,
        closed_bar_authority=authority,
    )
    engine.lifecycle_prev["M15"] = {
        "active_market_context": "LONG_CONTEXT",
        "lifecycle_state": "CHALLENGED",
        "active_context_started_at": pd.Timestamp("2026-08-17T10:59:00Z"),
        "evaluation_mode": "PROVISIONAL_INTRABAR",
    }
    engine._active_episode["M15"] = "M15:prov:1"

    monkeypatch.setattr(
        "btc_ml.live.intrabar.cognition_pipeline.synthesize_provisional_state",
        lambda **_k: {
            "market_context": "OBSERVE",
            "context_status": "INVALIDATED",
            "auction_episode": "BALANCE",
            "decision_evidence": {},
        },
    )
    monkeypatch.setattr(
        "btc_ml.live.intrabar.cognition_pipeline.step_event_time_lifecycle",
        lambda **_k: {
            "active_market_context": "OBSERVE",
            "lifecycle_state": "INVALIDATED",
            "invalidation_type": "AUCTION_NEUTRALIZATION",
            "evaluation_mode": "PROVISIONAL_INTRABAR",
        },
    )

    emitted = engine.on_agg_trade(_trade("77000", "2026-08-19T15:30:00.200Z", 2_000, 2))
    ends = [e for e in emitted if e.get("event_type") == "CONTEXT_END" and e.get("timeframe") == "M15"]
    assert len(ends) == 1
    assert ends[0]["lifecycle_episode_id"] == "M15:prov:1"
    assert ends[0]["closed_bar_confirms_end"] is True
    assert is_provisional_context_end(ends[0]) is False
    assert "M15" not in engine._active_episode


def test_closed_bar_tip_currentness_m15_birth_bar():
    assert (
        closed_bar_tip_is_current(
            closed_bar_timestamp="2026-09-11T08:45:00Z",
            event_timestamp="2026-09-11T09:45:00.011286Z",
            timeframe="M15",
        )
        is False
    )
    assert (
        closed_bar_tip_is_current(
            closed_bar_timestamp="2026-09-11T09:30:00Z",
            event_timestamp="2026-09-11T09:45:00.011286Z",
            timeframe="M15",
        )
        is True
    )


def test_stale_observe_does_not_kill_live_short(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """M15_10: live FLIP to SHORT, then bar-close END because authority still showed 08:45 OBSERVE."""
    frame = pd.DataFrame(
        [
            {
                "timestamp": "2026-09-11T08:45:00Z",
                "timeframe": "M15",
                "active_market_context": "OBSERVE",
            }
        ]
    )
    path = tmp_path / "market_context_lifecycle_memory.parquet"
    frame.to_parquet(path, index=False)
    journal = ContextEventJournal(tmp_path / "journal")
    engine = IntrabarCognitionEngine(
        context_journal=journal,
        closed_bar_authority=ClosedBarContextAuthority(path),
    )
    engine.lifecycle_prev["M15"] = {
        "active_market_context": "SHORT_CONTEXT",
        "lifecycle_state": "ACTIVE",
        "active_context_started_at": pd.Timestamp("2026-09-11T09:40:11.590602Z"),
        "evaluation_mode": "PROVISIONAL_INTRABAR",
    }
    engine._active_episode["M15"] = "M15:prov:1"

    monkeypatch.setattr(
        "btc_ml.live.intrabar.cognition_pipeline.synthesize_provisional_state",
        lambda **_k: {
            "market_context": "OBSERVE",
            "context_status": "INVALIDATED",
            "auction_episode": "BALANCE",
            "decision_evidence": {},
        },
    )
    monkeypatch.setattr(
        "btc_ml.live.intrabar.cognition_pipeline.step_event_time_lifecycle",
        lambda **_k: {
            "active_market_context": "OBSERVE",
            "lifecycle_state": "INVALIDATED",
            "invalidation_type": "AUCTION_NEUTRALIZATION",
            "evaluation_mode": "PROVISIONAL_INTRABAR",
        },
    )

    emitted = engine.on_agg_trade(_trade("76965.72", "2026-09-11T09:45:00.011286Z", 3_000, 3))
    ends = [e for e in emitted if e.get("event_type") == "CONTEXT_END" and e.get("timeframe") == "M15"]
    assert ends == []
    assert engine.end_holds >= 1
    assert engine.lifecycle_prev["M15"]["active_market_context"] == "SHORT_CONTEXT"
    assert engine._active_episode["M15"] == "M15:prov:1"
