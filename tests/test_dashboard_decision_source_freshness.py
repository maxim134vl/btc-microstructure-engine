"""Dashboard Decision layer source precedence and freshness."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import research_pipeline_service as svc  # noqa: E402


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _install_frames(monkeypatch, frames: dict[str, pd.DataFrame]) -> None:
    async def fake_read_parquet(name: str, tail: int | None = None, columns: list[str] | None = None) -> pd.DataFrame:
        frame = frames.get(name, pd.DataFrame())
        if tail is not None and len(frame) > tail:
            return frame.tail(tail).copy()
        return frame.copy()

    monkeypatch.setattr(svc, "read_parquet", fake_read_parquet)


def _base_frames() -> dict[str, pd.DataFrame]:
    return {
        "live_market_feed.parquet": _df([{"timestamp": "2026-07-23T12:15:00Z"}]),
        "context_decision_log.parquet": pd.DataFrame(),
        "market_context_lifecycle_memory.parquet": pd.DataFrame(),
        "market_state_memory.parquet": pd.DataFrame(),
        "trading_state_memory.parquet": pd.DataFrame(),
        "trading_state_feature_snapshots.parquet": pd.DataFrame(),
        "probabilistic_auction_memory.parquet": pd.DataFrame(),
    }


def _disable_live1a(monkeypatch) -> None:
    monkeypatch.setattr(svc, "load_live1a_intrabar_health", lambda: None)
    monkeypatch.setattr(svc, "load_live1b_paper_health", lambda: None)


def _live1a_health(
    *,
    market_context: str = "OBSERVE",
    lifecycle: str = "NO_ACTIVE_CONTEXT",
    updated_at: str = "2026-07-28T17:52:00Z",
    episode_id: str | None = None,
    event_id: str | None = None,
) -> dict:
    row = {
        "market_context": market_context,
        "lifecycle": lifecycle,
        "active": market_context,
        "lifecycle_episode_id": episode_id,
        "context_event_id": event_id,
    }
    bar = {
        "causal_cutoff_timestamp": updated_at,
        "bar_open_timestamp": "2026-07-28T17:45:00Z",
        "trade_count_so_far": 10,
        "last_trade_id": 1,
    }
    return {
        "updated_at": updated_at,
        "pid": 20378,
        "last_provisional_eval": {tf: dict(row) for tf in ("M15", "M30", "H1", "H4")},
        "partial_bars": {tf: dict(bar) for tf in ("M15", "M30", "H1", "H4")},
        "last_context_event": {},
    }


def test_stale_trading_state_memory_is_not_current_decision(monkeypatch) -> None:
    _disable_live1a(monkeypatch)
    frames = _base_frames()
    frames["trading_state_memory.parquet"] = _df(
        [
            {
                "timestamp": "2026-07-10T06:20:49Z",
                "trading_state": "OBSERVE",
                "entry_eligible": False,
                "execution_posture": "MONITOR_ONLY",
                "confidence_band": "LOW_CONFIDENCE",
                "market_state": "REVERSAL",
                "market_state_confidence": 0.16,
            }
        ]
    )
    _install_frames(monkeypatch, frames)

    snapshot = asyncio.run(svc.build_decision_layer_snapshot())

    assert snapshot["source_name"] == "trading_state_memory.parquet"
    assert snapshot["source_stale"] is True
    assert snapshot["status_label"] == "STALE_DECISION"
    assert snapshot["trading_state"] is None
    assert snapshot["stale_trading_state"] == "OBSERVE"
    assert "stale" in snapshot["freshness_warning"].lower()


def test_fresh_context_decision_log_wins_over_stale_trading_state(monkeypatch) -> None:
    _disable_live1a(monkeypatch)
    frames = _base_frames()
    frames["context_decision_log.parquet"] = _df(
        [
            {
                "decision_id": "decision-1",
                "candle_timestamp": "2026-07-23T12:15:00Z",
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "CHALLENGED",
                "candidate_context": None,
                "paper_action_candidate": "INTENT_OPEN_SHORT",
                "intended_side": "SHORT",
                "paper_loop_allowed": False,
                "confidence": 0.716,
                "edge_signal_rule": "NET_EXPECTED_EDGE_GT_ZERO",
            }
        ]
    )
    frames["trading_state_memory.parquet"] = _df(
        [{"timestamp": "2026-07-10T06:20:49Z", "trading_state": "OBSERVE", "entry_eligible": False}]
    )
    _install_frames(monkeypatch, frames)

    snapshot = asyncio.run(svc.build_decision_layer_snapshot())

    assert snapshot["source_name"] == "context_decision_log.parquet"
    assert snapshot["source_timestamp"] == "2026-07-23T12:15:00Z"
    assert snapshot["source_stale"] is False
    assert snapshot["status_label"] == "SHORT_CONTEXT"
    assert snapshot["trading_state"] == "SHORT_CONTEXT"
    assert snapshot["lifecycle_state"] == "CHALLENGED"
    assert snapshot["paper_action_candidate"] == "INTENT_OPEN_SHORT"


def test_fresh_lifecycle_wins_when_decision_log_is_stale(monkeypatch) -> None:
    _disable_live1a(monkeypatch)
    frames = _base_frames()
    frames["context_decision_log.parquet"] = _df(
        [{"candle_timestamp": "2026-07-23T10:00:00Z", "active_market_context": "OBSERVE"}]
    )
    frames["market_context_lifecycle_memory.parquet"] = _df(
        [
            {
                "timestamp": "2026-07-23T12:15:00Z",
                "raw_market_context": "LONG_CONTEXT",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "candidate_context": None,
                "action_allowed": False,
                "action_reason": "shadow market context only; execution disabled",
            }
        ]
    )
    frames["trading_state_memory.parquet"] = _df(
        [{"timestamp": "2026-07-10T06:20:49Z", "trading_state": "OBSERVE", "entry_eligible": False}]
    )
    _install_frames(monkeypatch, frames)

    snapshot = asyncio.run(svc.build_decision_layer_snapshot())

    assert snapshot["source_name"] == "market_context_lifecycle_memory.parquet"
    assert snapshot["source_stale"] is False
    assert snapshot["status_label"] == "LONG_CONTEXT"
    assert snapshot["trading_state"] == "LONG_CONTEXT"


def test_observe_is_shown_only_when_latest_fresh_source_is_observe(monkeypatch) -> None:
    _disable_live1a(monkeypatch)
    frames = _base_frames()
    frames["context_decision_log.parquet"] = _df(
        [
            {
                "decision_id": "decision-observe",
                "candle_timestamp": "2026-07-23T12:15:00Z",
                "active_market_context": "OBSERVE",
                "lifecycle_state": "NO_ACTIVE_CONTEXT",
                "candidate_context": None,
                "paper_action_candidate": "NO_TRADE_OBSERVE",
                "intended_side": "NONE",
                "paper_loop_allowed": False,
            }
        ]
    )
    _install_frames(monkeypatch, frames)

    snapshot = asyncio.run(svc.build_decision_layer_snapshot())

    assert snapshot["source_name"] == "context_decision_log.parquet"
    assert snapshot["source_stale"] is False
    assert snapshot["status_label"] == "OBSERVE"
    assert snapshot["trading_state"] == "OBSERVE"


def test_live1a_observe_overrides_legacy_short(monkeypatch) -> None:
    """Case 1: LIVE1A OBSERVE + legacy SHORT → OPS returns OBSERVE/NONE/NONE."""
    now = datetime(2026, 7, 28, 17, 52, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(
        svc,
        "load_live1a_intrabar_health",
        lambda: _live1a_health(market_context="OBSERVE", lifecycle="NO_ACTIVE_CONTEXT"),
    )
    monkeypatch.setattr(svc, "load_live1b_paper_health", lambda: {"paper_epoch_id": "EPOCH_A"})
    frames = _base_frames()
    frames["context_decision_log.parquet"] = _df(
        [
            {
                "candle_timestamp": "2026-07-28T17:30:00Z",
                "active_market_context": "SHORT_CONTEXT",
                "paper_action_candidate": "INTENT_OPEN_SHORT",
                "intended_side": "SHORT",
                "paper_loop_allowed": False,
            }
        ]
    )
    _install_frames(monkeypatch, frames)

    # Force now via direct builder (snapshot uses wall clock via builder path).
    payload = svc.build_live1a_decision_layer_payload(
        _live1a_health(),
        {"paper_epoch_id": "EPOCH_A"},
        now=now,
    )
    assert payload is not None
    assert payload["source"] == "LIVE1A_INTRABAR_CONTEXT"
    assert payload["trading_state"] == "OBSERVE"
    assert payload["market_state"] == "OBSERVE"
    assert payload["market_bias"] == "NONE"
    assert payload["entry_eligible"] is False
    assert payload["execution_posture"] == "NONE"
    assert payload["timeframe"] == "M15"

    snapshot = asyncio.run(svc.build_decision_layer_snapshot())
    assert snapshot["source"] == "LIVE1A_INTRABAR_CONTEXT"
    assert snapshot["trading_state"] == "OBSERVE"
    assert snapshot["execution_posture"] == "NONE"


def test_live1a_short_with_matching_live1b_intent(monkeypatch) -> None:
    """Case 2: LIVE1A SHORT + matching LIVE1B decision → SHORT + factual intent."""
    cog = _live1a_health(
        market_context="SHORT",
        lifecycle="ACTIVE",
        episode_id="M15:prov:1",
        event_id="evt-1",
    )
    paper = {
        "paper_epoch_id": "EPOCH_A",
        "last_decision": {
            "paper_epoch_id": "EPOCH_A",
            "timeframe": "M15",
            "lifecycle_episode_id": "M15:prov:1",
            "context_event_id": "evt-1",
            "entry_eligible": True,
            "intent": "INTENT_OPEN_SHORT",
            "decision_reason": "EDGE_OK",
        },
    }
    monkeypatch.setattr(svc, "load_live1a_intrabar_health", lambda: cog)
    monkeypatch.setattr(svc, "load_live1b_paper_health", lambda: paper)
    _install_frames(monkeypatch, _base_frames())

    snapshot = asyncio.run(svc.build_decision_layer_snapshot())
    assert snapshot["trading_state"] == "SHORT_CONTEXT"
    assert snapshot["market_bias"] == "SHORT"
    assert snapshot["entry_eligible"] is True
    assert snapshot["execution_posture"] == "INTENT_OPEN_SHORT"
    assert snapshot["lifecycle_episode_id"] == "M15:prov:1"
    assert snapshot["context_event_id"] == "evt-1"


def test_live1a_short_without_matching_live1b_decision(monkeypatch) -> None:
    """Case 3: LIVE1A SHORT without matching LIVE1B decision → eligible NO, intent NONE."""
    cog = _live1a_health(
        market_context="SHORT",
        lifecycle="ACTIVE",
        episode_id="M15:prov:2",
        event_id="evt-2",
    )
    monkeypatch.setattr(svc, "load_live1a_intrabar_health", lambda: cog)
    monkeypatch.setattr(svc, "load_live1b_paper_health", lambda: {"paper_epoch_id": "EPOCH_A"})
    _install_frames(monkeypatch, _base_frames())

    snapshot = asyncio.run(svc.build_decision_layer_snapshot())
    assert snapshot["trading_state"] == "SHORT_CONTEXT"
    assert snapshot["entry_eligible"] is False
    assert snapshot["execution_posture"] == "NONE"


def test_live1a_observe_clears_old_short_intent(monkeypatch) -> None:
    """Case 4: CONTEXT_END/OBSERVE clears stale SHORT episode/intent for OPS card."""
    cog = _live1a_health(market_context="OBSERVE", lifecycle="NO_ACTIVE_CONTEXT")
    paper = {
        "paper_epoch_id": "EPOCH_A",
        "last_decision": {
            "paper_epoch_id": "EPOCH_A",
            "timeframe": "M15",
            "lifecycle_episode_id": "M15:old-short",
            "context_event_id": "evt-old",
            "entry_eligible": True,
            "intent": "INTENT_OPEN_SHORT",
        },
    }
    monkeypatch.setattr(svc, "load_live1a_intrabar_health", lambda: cog)
    monkeypatch.setattr(svc, "load_live1b_paper_health", lambda: paper)
    _install_frames(monkeypatch, _base_frames())

    snapshot = asyncio.run(svc.build_decision_layer_snapshot())
    assert snapshot["trading_state"] == "OBSERVE"
    assert snapshot["market_bias"] == "NONE"
    assert snapshot["entry_eligible"] is False
    assert snapshot["execution_posture"] == "NONE"
    assert snapshot["lifecycle_episode_id"] is None
