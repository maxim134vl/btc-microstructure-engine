"""Regression tests for context-event freshness / restart backfill execution bug."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from btc_ml.live.intrabar.closed_bar_event_bridge import materialize_closed_bar_events
from btc_ml.live.intrabar.context_event_freshness import (
    FRESHNESS_FRESH,
    FRESHNESS_STALE_AGE,
    annotate_event_provenance,
    entry_freshness_block_reason,
    evaluate_entry_freshness,
    is_entry_execution_eligible,
)
from btc_ml.live.intrabar.context_event_journal import ContextEventJournal
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch


def _fresh_ts(seconds_ago: int = 30) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _hours_ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def cfg(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    cfg_src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    raw["context_event_max_age_seconds"] = 300.0
    (repo / "config" / "intrabar_paper_execution.json").write_text(
        json.dumps(raw, indent=2) + "\n", encoding="utf-8"
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    return load_intrabar_paper_config(repo_root=repo), repo


def _epoch(cfg):
    ep = create_epoch(
        epochs_root=cfg.epochs_root,
        initial_equity_usd=cfg.initial_equity_usd,
        utc_stamp="FRESH1",
    )
    return activate_epoch(ep, epochs_root=cfg.epochs_root)


def _engine(cfg, activation_mono: int = 1_000_000) -> IntrabarPaperEngine:
    eng = IntrabarPaperEngine(cfg=cfg, epoch=_epoch(cfg), activation_monotonic_ns=activation_mono)
    eng.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=activation_mono,
        receive_timestamp=_fresh_ts(60),
        book_update_id="seed",
        domain="context",
    )
    return eng


def _ctx_event(
    *,
    eid: str,
    etype: str = "CONTEXT_START",
    decision_available_at: str,
    context_origin_timestamp: str | None = None,
    restart_backfill: bool = False,
    execution_eligible: bool | None = None,
    mono: int = 2_000_000,
) -> dict:
    payload = {
        "context_event_id": eid,
        "event_type": etype,
        "timeframe": "M15",
        "previous_context": "OBSERVE",
        "new_context": "LONG_CONTEXT",
        "direction": "LONG",
        "event_monotonic_ns": mono,
        "event_timestamp": decision_available_at,
        "decision_available_at": decision_available_at,
        "context_origin_timestamp": context_origin_timestamp or decision_available_at,
        "original_context_timestamp": context_origin_timestamp or decision_available_at,
        "source_bar_timestamp": context_origin_timestamp or decision_available_at,
        "context_event_price": "100.1",
        "best_bid": 100.0,
        "best_ask": 100.2,
        "bbo_receive_monotonic_ns": mono - 1000,
        "book_update_id": "b1",
        "lifecycle_episode_id": "ep_freshness",
        "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
        "ingested_at": _fresh_ts(5),
        "materialized_timestamp": _fresh_ts(5),
        "materialization_source": "closed_bar_context_decision",
    }
    if restart_backfill:
        payload["restart_backfill"] = True
        payload["materialization_class"] = "RESTART_BACKFILL"
        payload["revalidated_after_restart"] = True
        payload["freshness_status"] = "STALE_RESTART_BACKFILL"
        payload["execution_eligible"] = False
    if execution_eligible is not None:
        payload["execution_eligible"] = execution_eligible
    return payload


def _append_journal(cfg, event: dict) -> None:
    journal = cfg.context_journal_root / "events.jsonl"
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def test_case1_historical_event_age_7_hours_rejected(cfg):
    """Trade #13 class: laundered decision_available_at with old context origin."""
    c, _ = cfg
    eng = _engine(c)
    fresh_decision = _fresh_ts(30)
    stale_origin = _hours_ago(7)
    event = _ctx_event(
        eid="case1_stale_origin",
        decision_available_at=fresh_decision,
        context_origin_timestamp=stale_origin,
    )
    provenance = annotate_event_provenance(
        event,
        materialization_source="closed_bar_context_decision",
        max_age_seconds=c.context_event_max_age_seconds,
        materialized_timestamp=_fresh_ts(5),
    )
    event.update(provenance)
    assert provenance["freshness_status"] == FRESHNESS_STALE_AGE
    assert provenance["execution_eligible"] is False
    assert entry_freshness_block_reason(event, max_age_seconds=c.context_event_max_age_seconds)
    _append_journal(c, event)
    acts = eng.poll_context_journal()
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_CONTEXT_EVENT"
    assert eng.positions == {}


def test_case2_restart_backfill_event_rejected(cfg):
    c, _ = cfg
    eng = _engine(c)
    event = _ctx_event(
        eid="case2_restart",
        decision_available_at=_fresh_ts(30),
        restart_backfill=True,
    )
    assert evaluate_entry_freshness(event, max_age_seconds=300.0) != FRESHNESS_FRESH
    _append_journal(c, event)
    acts = eng.poll_context_journal()
    assert acts[0]["status"] in {"ENTRY_BLOCKED_RESTART_BACKFILL", "ENTRY_BLOCKED_REPLAY_SIGNAL"}
    assert eng.positions == {}


def test_case3_fresh_event_accepted(cfg):
    c, _ = cfg
    eng = _engine(c)
    fresh = _fresh_ts(30)
    event = _ctx_event(
        eid="case3_fresh",
        decision_available_at=fresh,
        context_origin_timestamp=fresh,
        execution_eligible=True,
    )
    provenance = annotate_event_provenance(
        event,
        materialization_source="closed_bar_context_decision",
        max_age_seconds=c.context_event_max_age_seconds,
        materialized_timestamp=_fresh_ts(5),
    )
    event.update(provenance)
    assert provenance["freshness_status"] == FRESHNESS_FRESH
    assert is_entry_execution_eligible(event, max_age_seconds=c.context_event_max_age_seconds)
    _append_journal(c, event)
    acts = eng.poll_context_journal()
    assert acts and acts[0]["status"] == "ENTERED"
    assert "M15" in eng.positions


def test_case4_duplicate_materialization_idempotent(tmp_path: Path):
    from datetime import datetime, timedelta, timezone

    journal = ContextEventJournal(tmp_path / "events")
    fresh_bar = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    fresh_decision = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    fresh_bbo = (datetime.now(timezone.utc) - timedelta(seconds=25)).isoformat().replace("+00:00", "Z")
    row = {
        "decision_id": "dup-1",
        "source_timeframe": "M15",
        "candle_timestamp": fresh_bar,
        "decision_written_at_utc": fresh_decision,
        "active_market_context": "LONG_CONTEXT",
        "previous_active_market_context": "OBSERVE",
        "lifecycle_episode_id": "ep_dup",
        "active_context_started_at": fresh_bar,
        "action_allowed": True,
        "paper_action_candidate": "INTENT_OPEN_LONG",
        "intended_side": "LONG",
        "signal_eligibility_status": "ELIGIBLE_DIRECTIONAL_SIGNAL",
        "decision_freshness_status": "FRESH",
        "close": 100.0,
    }
    bbo = {
        "best_bid": 100.0,
        "best_ask": 100.2,
        "book_update_id": "bbo1",
        "bbo_receive_timestamp": fresh_bbo,
        "bbo_receive_monotonic_ns": 2_000_000,
    }
    kwargs = dict(
        rows=[row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id="EPOCH_DUP",
        current_bbo=bbo,
        bridge_activated_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        context_event_max_age_seconds=300.0,
    )
    first = materialize_closed_bar_events(**kwargs)
    second_kwargs = dict(kwargs)
    second_kwargs["current_bbo"] = {**bbo, "bbo_receive_monotonic_ns": 3_000_000}
    second = materialize_closed_bar_events(**second_kwargs)
    assert first.emitted_count == 1
    assert second.emitted_count == 0
    assert second.duplicate_events == 1
    assert len(journal.path.read_text(encoding="utf-8").splitlines()) == 1


def test_ingested_at_older_than_decision_does_not_launder_freshness(cfg):
    """Regression: pre-activation ingested_at must not shrink apparent signal age."""
    c, _ = cfg
    eng = _engine(c)
    decision = _hours_ago(6)
    event = _ctx_event(
        eid="ingested_launder",
        decision_available_at=decision,
        context_origin_timestamp=decision,
    )
    event["ingested_at"] = _hours_ago(8)
    assert entry_freshness_block_reason(event, max_age_seconds=c.context_event_max_age_seconds)
    _append_journal(c, event)
    acts = eng.poll_context_journal()
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_CONTEXT_EVENT"
    assert eng.positions == {}


def test_trade13_replay_class_blocked(cfg):
    """Replay the confirmed bug shape: fresh decision_available_at, 7h-old origin."""
    c, _ = cfg
    eng = _engine(c)
    event = {
        "context_event_id": "CTX_00b3b57d9d489f726f33",
        "event_type": "CONTEXT_START",
        "timeframe": "M30",
        "previous_context": "OBSERVE",
        "new_context": "LONG_CONTEXT",
        "direction": "LONG",
        "event_monotonic_ns": 2_000_000,
        "event_timestamp": "2026-08-03T09:27:10Z",
        "decision_available_at": "2026-08-03T09:27:10Z",
        "context_origin_timestamp": "2026-08-03T02:16:39Z",
        "source_bar_timestamp": "2026-08-03T09:15:00Z",
        "context_event_price": "100.1",
        "best_bid": 100.0,
        "best_ask": 100.2,
        "bbo_receive_monotonic_ns": 1_999_000,
        "book_update_id": "b1",
        "lifecycle_episode_id": "ep_trade13",
        "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
        "ingested_at": "2026-08-03T09:27:12Z",
        "delivery_mode": "LIVE",
    }
    event.update(
        annotate_event_provenance(
            event,
            materialization_source="closed_bar_context_decision",
            max_age_seconds=c.context_event_max_age_seconds,
            materialized_timestamp="2026-08-03T09:27:12Z",
        )
    )
    _append_journal(c, event)
    acts = eng.poll_context_journal()
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_CONTEXT_EVENT"
    assert eng.positions == {}


def test_trade28_replay_class_blocked(cfg):
    """Trade #28 class: 791s age without restart_backfill metadata still rejected."""
    c, _ = cfg
    eng = _engine(c)
    decision = _fresh_ts(791)
    event = _ctx_event(
        eid="CTX_trade28",
        decision_available_at=decision,
        context_origin_timestamp=decision,
        restart_backfill=False,
    )
    event["delivery_mode"] = "LIVE"
    _append_journal(c, event)
    acts = eng.poll_context_journal()
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_CONTEXT_EVENT"
    assert eng.positions == {}
