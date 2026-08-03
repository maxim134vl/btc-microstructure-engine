"""Stale LIVE1A->LIVE1B context replay and S4.1 activation safety."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from btc_ml.trading import activation
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.entry_eligibility import (
    decision_timestamp,
    is_stale_entry_signal,
    stale_entry_block_reason,
)
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch


def _fresh_ts(seconds_ago: int = 30) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _stale_ts(hours_ago: int = 6) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def cfg(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    cfg_src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    (repo / "config" / "intrabar_paper_execution.json").write_text(
        json.dumps(raw, indent=2) + "\n", encoding="utf-8"
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    return load_intrabar_paper_config(repo_root=repo), repo


def _epoch(cfg) -> object:
    ep = create_epoch(
        epochs_root=cfg.epochs_root,
        initial_equity_usd=cfg.initial_equity_usd,
        utc_stamp="STALE1",
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


def _ctx(
    *,
    eid: str,
    etype: str,
    tf: str = "M15",
    prev: str = "OBSERVE",
    new: str = "LONG_CONTEXT",
    mono: int,
    episode: str = "ep_stale",
    decision_available_at: str | None = None,
    restart_backfill: bool = False,
) -> dict:
    decision = decision_available_at or _fresh_ts(30)
    payload = {
        "context_event_id": eid,
        "event_type": etype,
        "timeframe": tf,
        "previous_context": prev,
        "new_context": new,
        "event_monotonic_ns": mono,
        "event_timestamp": decision,
        "decision_available_at": decision,
        "context_event_price": "100.1",
        "best_bid": 100.0,
        "best_ask": 100.2,
        "bbo_receive_monotonic_ns": mono - 1000,
        "book_update_id": "b1",
        "lifecycle_episode_id": episode,
        "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
        "ingested_at": _fresh_ts(5),
    }
    if restart_backfill:
        payload["restart_backfill"] = True
        payload["materialization_class"] = "RESTART_BACKFILL"
        payload["revalidated_after_restart"] = True
    return payload


def _append_journal(cfg, event: dict, *, ingested_at: str | None = None) -> None:
    journal = cfg.context_journal_root / "events.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    event = dict(event)
    event["ingested_at"] = ingested_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def test_pre_activation_stale_context_start_yielded_blocked_checkpointed(cfg):
    c, _ = cfg
    ep = _epoch(c)
    stale = _ctx(
        eid="pre_act_start",
        etype="CONTEXT_START",
        mono=2_000_000,
        decision_available_at=_stale_ts(hours_ago=6),
    )
    _append_journal(c, stale, ingested_at=_stale_ts(hours_ago=8))
    eng = IntrabarPaperEngine(cfg=c, epoch=ep, activation_monotonic_ns=5_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=1_000_000,
        book_update_id="seed",
        domain="context",
    )
    yielded = list(eng.consumer.iter_new_events(max_entry_signal_age_seconds=c.max_entry_signal_age_seconds))
    assert len(yielded) == 1
    assert yielded[0]["_materialized_before_manager_activation"] is True
    assert yielded[0]["_monotonic_before_manager_activation"] is True
    acts = eng.poll_context_journal()
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_SIGNAL"
    assert eng.positions == {}
    assert eng.consumer.checkpoint.last_event_monotonic_ns == 2_000_000


def test_pre_activation_context_end_closes_open_position(cfg):
    c, _ = cfg
    ep = _epoch(c)
    eng = IntrabarPaperEngine(cfg=c, epoch=ep, activation_monotonic_ns=5_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=1_000_000,
        receive_timestamp=_fresh_ts(60),
        book_update_id="seed",
        domain="context",
    )
    eng.process_context_event(
        _ctx(eid="open_live", etype="CONTEXT_START", mono=1_500_000, episode="ep_pre_end")
    )
    assert "M15" in eng.positions
    stale_end = _ctx(
        eid="pre_act_end",
        etype="CONTEXT_END",
        prev="LONG_CONTEXT",
        new="OBSERVE",
        mono=2_000_000,
        episode="ep_pre_end",
        decision_available_at=_stale_ts(hours_ago=8),
    )
    _append_journal(c, stale_end, ingested_at=_stale_ts(hours_ago=9))
    acts = eng.poll_context_journal()
    assert acts and acts[0]["status"] == "EXITED"
    assert "M15" not in eng.positions
    assert eng.consumer.checkpoint.last_event_monotonic_ns == 2_000_000


def test_pre_activation_stale_context_flip_exits_but_blocks_reverse_entry(cfg):
    c, _ = cfg
    ep = _epoch(c)
    eng = IntrabarPaperEngine(cfg=c, epoch=ep, activation_monotonic_ns=5_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=1_000_000,
        receive_timestamp=_fresh_ts(60),
        book_update_id="seed",
        domain="context",
    )
    eng.process_context_event(
        _ctx(eid="flip_open", etype="CONTEXT_START", mono=1_500_000, episode="ep_pre_flip")
    )
    assert eng.positions["M15"].side == "LONG"
    stale_flip = _ctx(
        eid="pre_act_flip",
        etype="CONTEXT_FLIP",
        prev="LONG_CONTEXT",
        new="SHORT_CONTEXT",
        mono=2_000_000,
        episode="ep_pre_flip",
        decision_available_at=_stale_ts(hours_ago=6),
    )
    _append_journal(c, stale_flip, ingested_at=_stale_ts(hours_ago=7))
    acts = eng.poll_context_journal()
    assert [a["status"] for a in acts] == ["EXITED", "ENTRY_BLOCKED_STALE_SIGNAL"]
    assert "M15" not in eng.positions
    assert eng.consumer.checkpoint.last_event_monotonic_ns == 2_000_000


def test_restart_backfill_missing_decision_time_blocks_despite_fresh_lure_fields(cfg):
    c, _ = cfg
    eng = _engine(c)
    lure = _ctx(
        eid="missing_decision",
        etype="CONTEXT_START",
        mono=2_000_000,
        restart_backfill=True,
    )
    lure.pop("decision_available_at")
    lure["event_timestamp"] = _fresh_ts(5)
    lure["execution_not_before"] = _fresh_ts(1)
    lure["bbo_receive_timestamp"] = _fresh_ts(1)
    _append_journal(c, lure)
    acts = eng.poll_context_journal()
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_SIGNAL_NO_DECISION_TIME"
    assert eng.positions == {}
    blocked = eng.books.read_all("blocked")
    assert blocked[-1]["reason"] == "ENTRY_BLOCKED_STALE_SIGNAL_NO_DECISION_TIME"


def test_preflight_unconsumed_zero_after_stale_events_consumed(cfg, monkeypatch):
    c, repo = cfg
    ep = _epoch(c)
    epochs = repo / "data/trading/paper_epochs"
    paper = repo / "data/trading/intrabar_paper"
    journal = repo / "data/cognition/intrabar_context_events"
    monkeypatch.setattr(activation, "INTRABAR_EPOCHS_ROOT", epochs)
    monkeypatch.setattr(activation, "INTRABAR_PAPER_ROOT", paper)
    monkeypatch.setattr(activation, "INTRABAR_JOURNAL_ROOT", journal)

    eng = IntrabarPaperEngine(cfg=c, epoch=ep, activation_monotonic_ns=1_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=1_000_000,
        receive_timestamp=_fresh_ts(60),
        book_update_id="seed",
        domain="context",
    )
    stale = _ctx(
        eid="preflight_stale",
        etype="CONTEXT_START",
        mono=2_000_000,
        decision_available_at=_stale_ts(hours_ago=4),
        restart_backfill=True,
    )
    _append_journal(c, stale)
    eng.poll_context_journal()
    assert eng.consumer.checkpoint.last_event_monotonic_ns == 2_000_000

    detail = activation.intrabar_legacy_epoch_preflight()
    assert detail["paper_epoch_id"] == ep.paper_epoch_id
    assert detail["unconsumed_context_events"] == 0
    assert detail["open_positions"] == 0


def test_stale_replay_context_start_blocked_checkpoint_advances(cfg):
    c, _ = cfg
    eng = _engine(c)
    stale = _ctx(
        eid="replay_stale",
        etype="CONTEXT_START",
        mono=2_000_000,
        decision_available_at=_stale_ts(hours_ago=6),
        restart_backfill=True,
    )
    _append_journal(c, stale)
    assert eng.positions == {}
    acts = eng.poll_context_journal()
    assert len(acts) == 1
    assert acts[0]["status"] == "ENTRY_BLOCKED_RESTART_BACKFILL"
    assert eng.positions == {}
    assert eng.consumer.checkpoint.last_event_monotonic_ns == 2_000_000
    blocked = eng.books.read_all("blocked")
    assert blocked
    assert blocked[-1]["reason"] == "ENTRY_BLOCKED_RESTART_BACKFILL"
    assert blocked[-1]["decision_available_at"] == stale["decision_available_at"]
    assert "ingested_at" in blocked[-1]


def test_stale_signal_age_blocks_without_restart_flag(cfg):
    c, _ = cfg
    eng = _engine(c)
    stale = _ctx(
        eid="replay_age",
        etype="CONTEXT_START",
        mono=2_000_000,
        decision_available_at=_stale_ts(hours_ago=2),
        restart_backfill=False,
    )
    _append_journal(c, stale)
    acts = eng.poll_context_journal()
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_SIGNAL"
    assert eng.positions == {}


def test_context_end_closes_despite_stale_decision_time(cfg):
    c, _ = cfg
    eng = _engine(c)
    eng.process_context_event(
        _ctx(eid="fresh_open", etype="CONTEXT_START", mono=2_000_000, episode="ep_close")
    )
    assert "M15" in eng.positions
    stale_end = _ctx(
        eid="stale_end",
        etype="CONTEXT_END",
        prev="LONG_CONTEXT",
        new="OBSERVE",
        mono=3_000_000,
        episode="ep_close",
        decision_available_at=_stale_ts(hours_ago=8),
    )
    acts = eng.process_context_event(stale_end)
    assert acts and acts[0]["status"] == "EXITED"
    assert "M15" not in eng.positions


def test_fresh_context_start_still_opens(cfg):
    c, _ = cfg
    eng = _engine(c)
    acts = eng.process_context_event(
        _ctx(eid="fresh_start", etype="CONTEXT_START", mono=2_000_000, episode="ep_fresh")
    )
    assert acts[0]["status"] == "ENTERED"
    assert eng.positions["M15"].side == "LONG"


def test_duplicate_same_episode_start_does_not_reopen(cfg):
    c, _ = cfg
    eng = _engine(c)
    episode = "ep_dup"
    eng.process_context_event(
        _ctx(eid="start1", etype="CONTEXT_START", mono=2_000_000, episode=episode)
    )
    eng.process_context_event(
        _ctx(
            eid="end1",
            etype="CONTEXT_END",
            prev="LONG_CONTEXT",
            new="OBSERVE",
            mono=3_000_000,
            episode=episode,
        )
    )
    assert "M15" not in eng.positions
    dup = eng.process_context_event(
        _ctx(eid="start2", etype="CONTEXT_START", mono=4_000_000, episode=episode)
    )
    assert dup == []
    blocked = eng.books.read_all("blocked")
    assert blocked and blocked[-1]["reason"] == "ENTRY_BLOCKED_EPISODE_ALREADY_TRADED"
    assert eng.positions == {}


def test_entry_eligibility_uses_decision_available_at_not_ingested_at():
    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    event = {
        "event_type": "CONTEXT_START",
        "decision_available_at": "2026-08-03T06:00:00Z",
        "event_timestamp": "2026-08-03T06:00:00Z",
        "ingested_at": "2026-08-03T11:59:00Z",
        "execution_not_before": "2026-08-03T11:59:00Z",
    }
    assert decision_timestamp(event) == pd.Timestamp("2026-08-03T06:00:00Z", tz="UTC")
    assert is_stale_entry_signal(event, max_age_seconds=900.0, consumption_time=now)
    assert stale_entry_block_reason(event, max_age_seconds=900.0, consumption_time=now) == "ENTRY_BLOCKED_STALE_SIGNAL"


def test_restart_backfill_ignores_execution_not_before_for_age():
    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    event = {
        "event_type": "CONTEXT_START",
        "restart_backfill": True,
        "decision_available_at": "2026-08-03T06:00:00Z",
        "execution_not_before": "2026-08-03T11:59:00Z",
        "event_timestamp": "2026-08-03T11:59:00Z",
    }
    assert decision_timestamp(event) == pd.Timestamp("2026-08-03T06:00:00Z", tz="UTC")
    assert stale_entry_block_reason(event, max_age_seconds=900.0, consumption_time=now) == "ENTRY_BLOCKED_RESTART_BACKFILL"


def test_intrabar_preflight_blocks_open_legacy_position(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    epoch_id = "epoch_legacy_open"
    epochs = root / "data/trading/paper_epochs"
    paper = root / "data/trading/intrabar_paper"
    journal = root / "data/cognition/intrabar_context_events"
    epochs.mkdir(parents=True)
    paper.mkdir(parents=True)
    journal.mkdir(parents=True)
    (epochs / "active.json").write_text(
        json.dumps({"paper_epoch_id": epoch_id, "rule_contract_version": "v1"}) + "\n",
        encoding="utf-8",
    )
    books = paper / epoch_id / "books"
    books.mkdir(parents=True)
    (books / "positions.jsonl").write_text(
        json.dumps({"position_id": "pos1", "status": "OPEN", "timeframe": "M15"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(activation, "INTRABAR_EPOCHS_ROOT", epochs)
    monkeypatch.setattr(activation, "INTRABAR_PAPER_ROOT", paper)
    monkeypatch.setattr(activation, "INTRABAR_JOURNAL_ROOT", journal)

    detail = activation.intrabar_legacy_epoch_preflight()
    assert detail["open_positions"] == 1
    assert detail["mode"] == activation.MODE_OPEN_POSITION_PRESENT
    assert detail["blocking_status"] == activation.BLOCKED_BY_LEGACY_INTRABAR_EPOCH

    gates = activation.evaluate_gates()
    assert gates["allowed"] is False
    assert activation.BLOCKED_BY_LEGACY_INTRABAR_EPOCH in gates["blocked_reasons"]


def test_intrabar_preflight_blocks_unconsumed_context_events(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    epoch_id = "epoch_pending_events"
    epochs = root / "data/trading/paper_epochs"
    paper = root / "data/trading/intrabar_paper"
    journal = root / "data/cognition/intrabar_context_events"
    epochs.mkdir(parents=True)
    paper.mkdir(parents=True)
    journal.mkdir(parents=True)
    (epochs / "active.json").write_text(
        json.dumps({"paper_epoch_id": epoch_id}) + "\n",
        encoding="utf-8",
    )
    (paper / epoch_id).mkdir(parents=True)
    (paper / epoch_id / "context_consumer_checkpoint.json").write_text(
        json.dumps({"paper_epoch_id": epoch_id, "last_event_monotonic_ns": 1_000_000}) + "\n",
        encoding="utf-8",
    )
    (journal / "events.jsonl").write_text(
        json.dumps({"epoch_id": epoch_id, "event_monotonic_ns": 2_000_000}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(activation, "INTRABAR_EPOCHS_ROOT", epochs)
    monkeypatch.setattr(activation, "INTRABAR_PAPER_ROOT", paper)
    monkeypatch.setattr(activation, "INTRABAR_JOURNAL_ROOT", journal)

    detail = activation.intrabar_legacy_epoch_preflight()
    assert detail["unconsumed_context_events"] == 1
    assert detail["open_positions"] == 0
    assert detail["mode"] == activation.MODE_OPEN_POSITION_PRESENT
    assert detail["blocking_status"] == activation.BLOCKED_BY_LEGACY_INTRABAR_EPOCH
