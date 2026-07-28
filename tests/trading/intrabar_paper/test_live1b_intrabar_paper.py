"""Minimal LIVE1B contract tests before cutover."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.trading.intrabar_paper.bbo import CausalBBOStore, fill_price_for
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.consumer import ContextEventConsumer, idempotency_key
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import PaperEpoch, activate_epoch, create_epoch


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def _epoch(cfg, repo) -> PaperEpoch:
    ep = create_epoch(
        epochs_root=cfg.epochs_root,
        initial_equity_usd=cfg.initial_equity_usd,
        utc_stamp="TEST20260728",
    )
    return activate_epoch(ep, epochs_root=cfg.epochs_root)


def _engine(cfg, repo) -> IntrabarPaperEngine:
    ep = _epoch(cfg, repo)
    eng = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    # Seed causal BBO in context-event clock domain (same as journal events).
    eng.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=1_000_000,
        receive_timestamp="2026-07-28T00:00:00Z",
        book_update_id="1",
        domain="context",
    )
    return eng


def _ctx(
    *,
    eid: str,
    etype: str,
    tf: str,
    prev: str,
    new: str,
    mono: int,
    episode: str = "ep1",
    bid: float = 100.0,
    ask: float = 100.2,
) -> dict:
    return {
        "context_event_id": eid,
        "event_type": etype,
        "timeframe": tf,
        "previous_context": prev,
        "new_context": new,
        "event_monotonic_ns": mono,
        "event_timestamp": "2026-07-28T12:00:00Z",
        "context_event_price": "100.1",
        "best_bid": bid,
        "best_ask": ask,
        "bbo_receive_monotonic_ns": mono - 1000,
        "book_update_id": "b1",
        "lifecycle_episode_id": episode,
    }


def test_long_start_fills_ask(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    acts = eng.process_context_event(
        _ctx(eid="e1", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    assert acts and acts[0]["status"] == "ENTERED"
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(100.2)
    assert eng.positions["M15"].side == "LONG"


def test_short_start_fills_bid(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    acts = eng.process_context_event(
        _ctx(eid="e2", etype="CONTEXT_START", tf="M30", prev="OBSERVE", new="SHORT_CONTEXT", mono=2_000_000)
    )
    assert acts[0]["status"] == "ENTERED"
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(100.0)


def test_no_entry_observe_or_end(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    assert eng.process_context_event(
        _ctx(eid="o1", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="OBSERVE", mono=2_000_000)
    ) == []
    # END without position
    assert (
        eng.process_context_event(
            _ctx(eid="end1", etype="CONTEXT_END", tf="M15", prev="LONG_CONTEXT", new="OBSERVE", mono=3_000_000)
        )
        == []
    )


def test_no_entry_before_activation(cfg):
    c, repo = cfg
    ep = _epoch(c, repo)
    eng = IntrabarPaperEngine(cfg=c, epoch=ep, activation_monotonic_ns=5_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=100.0, best_ask=100.2, receive_monotonic_ns=1_000_000, book_update_id="1", domain="context"
    )
    # Consumer gate: write journal event before activation mono and poll
    journal = c.context_journal_root / "events.jsonl"
    journal.write_text(
        json.dumps(
            _ctx(
                eid="old",
                etype="CONTEXT_START",
                tf="M15",
                prev="OBSERVE",
                new="LONG_CONTEXT",
                mono=2_000_000,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    assert eng.poll_context_journal() == []
    assert eng.positions == {}


def test_no_duplicate_after_restart(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    ev = _ctx(eid="dup1", etype="CONTEXT_START", tf="H1", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    assert eng.process_context_event(ev)[0]["status"] == "ENTERED"
    # Simulate restart with same checkpoint keys
    eng2 = IntrabarPaperEngine(cfg=c, epoch=eng.epoch)
    eng2.bbo.update_from_book_ticker(
        best_bid=100.0, best_ask=100.2, receive_monotonic_ns=1_000_000, book_update_id="1", domain="context"
    )
    # Restore processed key via consumer checkpoint file
    eng.consumer.save()
    eng2.consumer.checkpoint.processed_keys = set(eng.consumer.checkpoint.processed_keys)
    out = eng2.process_context_event(ev)
    assert out[0]["status"] == "DUPLICATE_PREVENTED"
    assert len(eng2.positions) <= 1


def test_long_end_exits_bid(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    eng.process_context_event(
        _ctx(eid="e1", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    acts = eng.process_context_event(
        _ctx(
            eid="e2",
            etype="CONTEXT_END",
            tf="M15",
            prev="LONG_CONTEXT",
            new="OBSERVE",
            mono=4_000_000,
            bid=101.0,
            ask=101.2,
            episode="ep1",
        )
    )
    assert acts[0]["status"] == "EXITED"
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(101.0)
    assert "M15" not in eng.positions


def test_short_end_exits_ask(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    eng.process_context_event(
        _ctx(eid="s1", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="SHORT_CONTEXT", mono=2_000_000)
    )
    acts = eng.process_context_event(
        _ctx(
            eid="s2",
            etype="CONTEXT_END",
            tf="M15",
            prev="SHORT_CONTEXT",
            new="OBSERVE",
            mono=4_000_000,
            bid=99.0,
            ask=99.2,
        )
    )
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(99.2)


def test_flip_long_to_short_close_then_open(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    eng.process_context_event(
        _ctx(eid="f0", etype="CONTEXT_START", tf="H4", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    eng.update_bbo_from_market(
        best_bid=100.5, best_ask=100.7, receive_monotonic_ns=3_000_000, book_update_id="2"
    )
    acts = eng.process_context_event(
        _ctx(
            eid="f1",
            etype="CONTEXT_FLIP",
            tf="H4",
            prev="LONG_CONTEXT",
            new="SHORT_CONTEXT",
            mono=4_000_000,
            bid=100.5,
            ask=100.7,
            episode="ep_flip",
        )
    )
    assert [a["status"] for a in acts] == ["EXITED", "ENTERED"]
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(100.5)  # long exit bid
    assert acts[1]["fill"]["paper_fill_price"] == pytest.approx(100.5)  # short entry bid
    assert eng.positions["H4"].side == "SHORT"
    assert acts[0]["fill"].get("trigger_monotonic_ns", 4_000_000) < acts[1]["fill"]["fill_monotonic_ns"]


def test_flip_short_to_long(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    eng.process_context_event(
        _ctx(eid="g0", etype="CONTEXT_START", tf="H1", prev="OBSERVE", new="SHORT_CONTEXT", mono=2_000_000)
    )
    eng.update_bbo_from_market(
        best_bid=100.5, best_ask=100.7, receive_monotonic_ns=3_000_000, book_update_id="2"
    )
    acts = eng.process_context_event(
        _ctx(
            eid="g1",
            etype="CONTEXT_FLIP",
            tf="H1",
            prev="SHORT_CONTEXT",
            new="LONG_CONTEXT",
            mono=4_000_000,
            bid=100.5,
            ask=100.7,
            episode="ep_flip2",
        )
    )
    assert [a["status"] for a in acts] == ["EXITED", "ENTERED"]
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(100.7)  # short exit ask
    assert acts[1]["fill"]["paper_fill_price"] == pytest.approx(100.7)  # long entry ask


def test_tp_before_end(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    eng.process_context_event(
        _ctx(eid="t0", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    pos = eng.positions["M15"]
    # Push bid through TP on manager-local BBO stream
    eng.update_bbo_from_market(
        best_bid=pos.take_profit_price + 0.01,
        best_ask=pos.take_profit_price + 0.2,
        receive_monotonic_ns=3_000_000,
        book_update_id="tp",
        source_event_id="bbo_tp",
    )
    assert "M15" not in eng.positions
    trades = eng.books.read_all("trades")
    assert trades and trades[-1]["exit_reason"] == "TP"


def test_sl_before_flip(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    eng.process_context_event(
        _ctx(eid="sl0", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    pos = eng.positions["M15"]
    eng.update_bbo_from_market(
        best_bid=pos.stop_loss_price - 0.01,
        best_ask=pos.stop_loss_price + 0.1,
        receive_monotonic_ns=3_000_000,
        book_update_id="sl",
        source_event_id="bbo_sl",
    )
    assert "M15" not in eng.positions
    assert eng.books.read_all("trades")[-1]["exit_reason"] == "SL"


def test_no_future_bbo(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    # Only future BBO exists in context domain
    eng.bbo = CausalBBOStore()
    eng.bbo.update_from_book_ticker(
        best_bid=100.0, best_ask=100.2, receive_monotonic_ns=9_000_000, book_update_id="fut", domain="context"
    )
    acts = eng.process_context_event(
        _ctx(eid="fut", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    # Event itself carries BBO at mono-1000; that becomes latest. Force stale by clearing after process start:
    # Re-test with event that has no BBO fields
    eng.bbo = CausalBBOStore()
    eng.bbo.update_from_book_ticker(
        best_bid=100.0, best_ask=100.2, receive_monotonic_ns=9_000_000, book_update_id="fut", domain="context"
    )
    ev = _ctx(eid="fut2", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    ev.pop("best_bid")
    ev.pop("best_ask")
    ev.pop("bbo_receive_monotonic_ns")
    acts = eng.process_context_event(ev)
    assert acts[0]["status"] == "ENTRY_BLOCKED_NO_CAUSAL_BBO"
    assert eng.positions == {}


def test_fill_contract_helpers():
    store = CausalBBOStore()
    bbo = store.update_from_book_ticker(
        best_bid=10.0, best_ask=10.5, receive_monotonic_ns=1, book_update_id="x"
    )
    assert fill_price_for(side="LONG", action="ENTRY", bbo=bbo) == 10.5
    assert fill_price_for(side="SHORT", action="ENTRY", bbo=bbo) == 10.0
    assert fill_price_for(side="LONG", action="EXIT", bbo=bbo) == 10.0
    assert fill_price_for(side="SHORT", action="EXIT", bbo=bbo) == 10.5


def test_idempotency_key_stable():
    k = idempotency_key(
        paper_epoch_id="E1", context_event_id="C1", timeframe="M15", action="ENTRY_LONG"
    )
    assert k == "E1|C1|M15|ENTRY_LONG"


def test_config_requires_explicit_bbo_age():
    cfg = load_intrabar_paper_config()
    assert cfg.max_bbo_age_ms == 2000.0
    assert cfg.real_execution_enabled is False
    assert cfg.paper_only is True
    assert cfg.initial_equity_usd == 100000.0
    assert cfg.max_risk_per_trade_usd == 1000.0
