"""Minimal LIVE1B contract tests before cutover."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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


def _fresh_ts(seconds_ago: int = 30) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _stale_ts(hours_ago: int = 6) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


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
    decision_available_at: str | None = None,
    restart_backfill: bool = False,
) -> dict:
    ts = decision_available_at or _fresh_ts(30)
    payload = {
        "context_event_id": eid,
        "event_type": etype,
        "timeframe": tf,
        "previous_context": prev,
        "new_context": new,
        "event_monotonic_ns": mono,
        "event_timestamp": ts,
        "decision_available_at": ts,
        "context_event_price": "100.1",
        "best_bid": bid,
        "best_ask": ask,
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


def test_long_start_fills_context_event_price(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    acts = eng.process_context_event(
        _ctx(eid="e1", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    assert acts and acts[0]["status"] == "ENTERED"
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(100.1)
    assert acts[0]["fill"]["best_ask"] == pytest.approx(100.2)
    assert acts[0]["fill"]["entry_price_source"] == "context_event_price"
    assert eng.positions["M15"].side == "LONG"


def test_short_start_fills_context_event_price(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    acts = eng.process_context_event(
        _ctx(eid="e2", etype="CONTEXT_START", tf="M30", prev="OBSERVE", new="SHORT_CONTEXT", mono=2_000_000)
    )
    assert acts[0]["status"] == "ENTERED"
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(100.1)
    assert acts[0]["fill"]["best_bid"] == pytest.approx(100.0)
    assert eng.positions["M30"].side == "SHORT"


def test_entry_uses_context_price_not_bbo_ask_or_bid(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    long_ev = _ctx(
        eid="ctx_px_long",
        etype="CONTEXT_START",
        tf="M15",
        prev="OBSERVE",
        new="LONG_CONTEXT",
        mono=2_000_000,
        bid=99.0,
        ask=101.0,
    )
    long_ev["context_event_price"] = "100.0"
    acts = eng.process_context_event(long_ev)
    assert acts[0]["status"] == "ENTERED"
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(100.0)
    assert acts[0]["fill"]["gross_entry_price"] == pytest.approx(100.0)
    assert acts[0]["fill"]["best_ask"] == pytest.approx(101.0)
    assert acts[0]["fill"]["best_bid"] == pytest.approx(99.0)
    eng.process_context_event(
        _ctx(
            eid="ctx_px_end",
            etype="CONTEXT_END",
            tf="M15",
            prev="LONG_CONTEXT",
            new="OBSERVE",
            mono=3_000_000,
            bid=99.0,
            ask=101.0,
        )
    )
    short_ev = _ctx(
        eid="ctx_px_short",
        etype="CONTEXT_START",
        tf="M30",
        prev="OBSERVE",
        new="SHORT_CONTEXT",
        mono=4_000_000,
        bid=99.0,
        ask=101.0,
        episode="ep_short_px",
    )
    short_ev["context_event_price"] = "100.0"
    acts2 = eng.process_context_event(short_ev)
    assert acts2[0]["status"] == "ENTERED"
    assert acts2[0]["fill"]["paper_fill_price"] == pytest.approx(100.0)


def test_missing_context_event_price_blocks_entry(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    ev = _ctx(eid="missing_px", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    ev.pop("context_event_price", None)
    acts = eng.process_context_event(ev)
    assert acts[0]["status"] == "ENTRY_BLOCKED_MISSING_CONTEXT_EVENT_PRICE"
    assert eng.positions == {}
    blocked = eng.books.read_all("blocked")
    assert blocked and blocked[-1]["reason"] == "ENTRY_BLOCKED_MISSING_CONTEXT_EVENT_PRICE"


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


def test_pre_activation_stale_start_is_yielded_blocked_and_checkpointed(cfg):
    c, repo = cfg
    ep = _epoch(c, repo)
    stale = _ctx(
        eid="pre_act_stale",
        etype="CONTEXT_START",
        tf="M15",
        prev="OBSERVE",
        new="LONG_CONTEXT",
        mono=2_000_000,
        decision_available_at=_stale_ts(hours_ago=6),
    )
    stale["ingested_at"] = _stale_ts(hours_ago=8)
    journal = c.context_journal_root / "events.jsonl"
    journal.write_text(json.dumps(stale) + "\n", encoding="utf-8")
    eng = IntrabarPaperEngine(cfg=c, epoch=ep, activation_monotonic_ns=5_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=100.0, best_ask=100.2, receive_monotonic_ns=1_000_000, book_update_id="1", domain="context"
    )
    acts = eng.poll_context_journal()
    assert len(acts) == 1
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_CONTEXT_EVENT"
    assert eng.positions == {}
    assert eng.consumer.checkpoint.last_event_monotonic_ns == 2_000_000


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
    assert acts[1]["fill"]["paper_fill_price"] == pytest.approx(100.1)  # short entry at context_event_price
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
    assert acts[1]["fill"]["paper_fill_price"] == pytest.approx(100.1)  # long entry at context_event_price


def test_tp_before_end(cfg):
    c, repo = cfg
    eng = _engine(c, repo)
    eng.process_context_event(
        _ctx(eid="t0", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    pos = eng.positions["M15"]
    # Protective TP is triggered by actual market trade price.
    eng.update_from_trade(
        price=pos.take_profit_price + 0.01,
        receive_monotonic_ns=3_000_000,
        source_event_id="agg_tp",
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
    eng.update_from_trade(
        price=pos.stop_loss_price - 0.01,
        receive_monotonic_ns=3_000_000,
        source_event_id="agg_sl",
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


def test_sl_executes_from_aggtrade_without_any_bbo(cfg):
    """
    Regression: protective SL must not depend on BBO availability.

    Once a position is open, an aggTrade crossing the fixed stop level
    must close the position immediately at the event price.
    """
    c, repo = cfg
    eng = _engine(c, repo)

    eng.process_context_event(
        _ctx(
            eid="sl_no_bbo_start",
            etype="CONTEXT_START",
            tf="M30",
            prev="OBSERVE",
            new="LONG_CONTEXT",
            mono=2_000_000,
            episode="M30:regression:sl_no_bbo",
        )
    )

    pos = eng.positions["M30"]
    stop = pos.stop_loss_price

    # Simulate complete BBO unavailability AFTER the position is open.
    eng.bbo._latest = None
    eng.bbo._latest_local = None

    # Actual market trade crosses the protective stop.
    event_price = stop - 0.01
    eng.update_from_trade(
        price=event_price,
        receive_monotonic_ns=3_000_000,
        receive_timestamp="2026-08-07T00:00:00Z",
        source_event_id="agg_sl_no_bbo",
    )

    assert "M30" not in eng.positions

    assert eng.last_command is not None
    assert eng.last_command["trigger_type"] == "SL"
    assert eng.last_command["trigger_event_id"] == "agg_sl_no_bbo"
    assert eng.last_command["trigger_price"] == pytest.approx(event_price)
    assert eng.last_command["paper_fill_price"] == pytest.approx(event_price)
    assert eng.last_command["execution_price"] == pytest.approx(event_price)
    assert eng.last_command["protective_level"] == pytest.approx(stop)
    assert eng.last_command["protective_slippage"] == pytest.approx(-0.01)

    # Protective execution must not fabricate BBO metadata.
    assert eng.last_command["best_bid"] is None
    assert eng.last_command["best_ask"] is None


@pytest.mark.parametrize(
    ("side", "trigger", "level", "pre_price", "event_price", "expected_slippage"),
    [
        ("LONG", "SL", 95.0, 96.0, 94.0, -1.0),
        ("SHORT", "SL", 105.0, 104.0, 106.0, 1.0),
        ("LONG", "TP", 110.0, 109.0, 113.0, 3.0),
        ("SHORT", "TP", 90.0, 91.0, 87.0, -3.0),
    ],
)
def test_protective_gap_and_overshoot_fill_at_event_price(
    cfg, side, trigger, level, pre_price, event_price, expected_slippage
):
    c, repo = cfg
    eng = _engine(c, repo)
    tf = "M15"
    eng.process_context_event(
        _ctx(
            eid=f"{side}_{trigger}_start",
            etype="CONTEXT_START",
            tf=tf,
            prev="OBSERVE",
            new=f"{side}_CONTEXT",
            mono=2_000_000,
        )
    )
    pos = eng.positions[tf]
    pos.entry_price = 100.0
    if trigger == "SL":
        pos.stop_loss_price = level
        pos.take_profit_price = 110.0 if side == "LONG" else 90.0
    else:
        pos.take_profit_price = level
        pos.stop_loss_price = 95.0 if side == "LONG" else 105.0

    assert eng.update_from_trade(
        price=pre_price,
        receive_monotonic_ns=3_000_000,
        source_event_id=f"{side}_{trigger}_pre",
    ) == []
    actions = eng.update_from_trade(
        price=event_price,
        receive_monotonic_ns=4_000_000,
        source_event_id=f"{side}_{trigger}_hit",
    )
    assert len(actions) == 1
    assert actions[0]["status"] == "EXITED"
    assert actions[0]["trade"]["exit_price"] == pytest.approx(event_price)
    assert actions[0]["trade"]["execution_price"] == pytest.approx(event_price)
    assert actions[0]["trade"]["trigger_price"] == pytest.approx(event_price)
    assert actions[0]["trade"]["protective_level"] == pytest.approx(level)
    assert actions[0]["trade"]["protective_slippage"] == pytest.approx(expected_slippage)
    assert actions[0]["fill"]["trigger_price"] == pytest.approx(event_price)
    assert actions[0]["fill"]["paper_fill_price"] == pytest.approx(event_price)
    assert actions[0]["trade"]["stop_loss_price"] == pytest.approx(pos.stop_loss_price)
    assert actions[0]["trade"]["take_profit_price"] == pytest.approx(pos.take_profit_price)

    # The first crossing closes exactly once; subsequent ticks cannot duplicate it.
    assert eng.update_from_trade(
        price=event_price - 1.0 if side == "LONG" else event_price + 1.0,
        receive_monotonic_ns=5_000_000,
        source_event_id=f"{side}_{trigger}_later",
    ) == []
    assert len(eng.books.read_all("trades")) == 1


def test_health_write_oserror_is_nonfatal(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    c, repo = cfg
    monkeypatch.chdir(repo)
    eng = _engine(c, repo)
    blocked_tmp = eng.health_path.with_suffix(".tmp")
    original_write_text = Path.write_text

    def fail_one_health_target(self: Path, *args, **kwargs):
        if self == blocked_tmp:
            raise OSError(28, "No space left on device")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_one_health_target)
    assert eng.write_health() == eng.health_path
    assert "No space left on device" in str(eng.last_health_write_error)
    assert (repo / "data/runtime/intrabar_paper_health.json").exists()
