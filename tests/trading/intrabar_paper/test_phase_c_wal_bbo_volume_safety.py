"""Phase C safety gates: soft bookTicker fsync must not break BBO fills or volume.

Contracts locked here:
1. ENTRY/EXIT paper fills still use best ask/bid via fill_price_for.
2. Trade volume lives on AGG_TRADE.quantity and stays hard-durable (fsync).
3. Soft BOOK_TICKER durability does not strip/alter volume rows or skip BBO dispatch.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from btc_ml.trading.intrabar_paper.bbo import fill_price_for
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch
from btc_ml.trading.intrabar_paper.execution_market_processor import (
    ExecutionMarketProcessor,
    normalize_futures_agg_trade,
    normalize_futures_book_ticker,
)
from btc_ml.trading.intrabar_paper.execution_market_wal import (
    EVENT_AGG_TRADE,
    EVENT_BOOK_TICKER,
    ExecutionMarketWAL,
)


@pytest.fixture
def env(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    cfg_src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    raw["entry_source"] = "context_journal"
    (repo / "config" / "intrabar_paper_execution.json").write_text(
        json.dumps(raw, indent=2) + "\n", encoding="utf-8"
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    cfg = load_intrabar_paper_config(repo_root=repo)
    ep = activate_epoch(
        create_epoch(
            epochs_root=cfg.epochs_root,
            initial_equity_usd=cfg.initial_equity_usd,
            utc_stamp="PHASEC",
        ),
        epochs_root=cfg.epochs_root,
    )
    engine = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    epoch_root = cfg.books_root / ep.paper_epoch_id
    return cfg, repo, engine, epoch_root, ep


def _processor(env) -> ExecutionMarketProcessor:
    cfg, _repo, engine, epoch_root, ep = env
    proc = ExecutionMarketProcessor.create(
        engine=engine,
        epoch_root=epoch_root,
        paper_epoch_id=ep.paper_epoch_id,
        max_bbo_age_ms=cfg.max_bbo_age_ms,
        max_agg_trade_age_ms=cfg.max_agg_trade_age_ms,
    )
    engine.attach_execution_market(proc)
    proc.on_websocket_connected()
    return proc


def _seed_ready(
    proc: ExecutionMarketProcessor,
    *,
    bid: float = 100.0,
    ask: float = 100.2,
    agg_id: int = 1,
    price: float | None = None,
    quantity: str = "0.01",
) -> int:
    """Book + aggTrade required for EXECUTION_MARKET HEALTHY / entry gate."""
    mono = time.monotonic_ns()
    _book(proc, bid=bid, ask=ask, mono=mono)
    _agg(
        proc,
        agg_id=agg_id,
        price=price if price is not None else (bid + ask) / 2.0,
        quantity=quantity,
        mono=mono + 1,
    )
    assert proc.execution_market_ready_for_entry() is True
    return mono


def _fresh_ts(seconds_ago: int = 20) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace(
        "+00:00", "Z"
    )


def _book(
    proc: ExecutionMarketProcessor,
    *,
    bid: float,
    ask: float,
    mono: int | None = None,
    update_id: int | None = None,
) -> dict[str, Any]:
    mono = mono or time.monotonic_ns()
    event = normalize_futures_book_ticker(
        {"u": update_id or mono, "b": str(bid), "a": str(ask), "E": 1},
        symbol="BTCUSDT",
        connection_session_id=proc.public_connection_session_id,
        receive_monotonic_ns=mono,
        receive_timestamp=_fresh_ts(),
    )
    result = proc._process_book_ticker(event)
    assert result["status"] == "BOOK_TICKER_DISPATCHED"
    return event


def _agg(
    proc: ExecutionMarketProcessor,
    *,
    agg_id: int,
    price: float,
    quantity: str,
    mono: int | None = None,
) -> dict[str, Any]:
    mono = mono or time.monotonic_ns()
    event = normalize_futures_agg_trade(
        {"a": agg_id, "p": str(price), "q": quantity, "T": 1, "m": False, "E": 1},
        symbol="BTCUSDT",
        connection_session_id=proc.market_connection_session_id,
        receive_monotonic_ns=mono,
        receive_timestamp=_fresh_ts(),
    )
    result = proc._persist_and_dispatch_agg_trade(event)
    assert result["status"] == "AGG_TRADE_DISPATCHED"
    return event


def _ctx(
    *,
    eid: str,
    etype: str,
    tf: str,
    prev: str,
    new: str,
    mono: int,
    bid: float,
    ask: float,
    episode: str = "ep_phase_c",
) -> dict[str, Any]:
    ts = _fresh_ts()
    return {
        "context_event_id": eid,
        "event_type": etype,
        "timeframe": tf,
        "previous_context": prev,
        "new_context": new,
        "event_monotonic_ns": mono,
        "event_timestamp": ts,
        "decision_available_at": ts,
        "context_event_price": (bid + ask) / 2.0,
        "price": (bid + ask) / 2.0,
        "best_bid": bid,
        "best_ask": ask,
        "bbo_receive_monotonic_ns": mono - 1000,
        "book_update_id": str(mono),
        "lifecycle_episode_id": episode,
    }


def _wal_rows(proc: ExecutionMarketProcessor) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in proc.wal.events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_book_ticker_contract_has_no_trade_volume_field():
    event = normalize_futures_book_ticker(
        {"u": 1, "b": "100.0", "a": "100.2", "E": 1},
        symbol="BTCUSDT",
        connection_session_id="sess",
        receive_monotonic_ns=1,
        receive_timestamp="2026-08-25T00:00:00Z",
    )
    assert event["event_type"] == EVENT_BOOK_TICKER
    assert "quantity" not in event
    assert "aggregate_trade_id" not in event


def test_agg_trade_normalize_preserves_volume_quantity():
    event = normalize_futures_agg_trade(
        {"a": 42, "p": "101.5", "q": "1.23456789", "T": 1, "m": True},
        symbol="BTCUSDT",
        connection_session_id="sess",
        receive_monotonic_ns=1,
        receive_timestamp="2026-08-25T00:00:00Z",
    )
    assert event["event_type"] == EVENT_AGG_TRADE
    assert event["quantity"] == "1.23456789"
    assert event["price"] == "101.5"
    assert event["aggregate_trade_id"] == 42


def test_soft_book_ticker_skips_fsync_but_hard_agg_trade_fsyncs_volume(env):
    proc = _processor(env)
    assert proc.wal.fsync_count == 0

    _book(proc, bid=100.0, ask=100.2)
    assert proc.wal.fsync_count == 0
    assert proc.wal.state_write_count == 0

    _agg(proc, agg_id=7, price=100.1, quantity="0.55000000")
    # pre_agg_trade flush of soft book + hard aggTrade append
    assert proc.wal.fsync_count == 2
    assert proc.wal.state_write_count >= 1
    assert proc.wal.last_confirmed_agg_trade_id == 7

    rows = _wal_rows(proc)
    books = [r for r in rows if r["event_type"] == EVENT_BOOK_TICKER]
    trades = [r for r in rows if r["event_type"] == EVENT_AGG_TRADE]
    assert len(books) == 1 and books[0]["wal_fsync"] is False
    assert len(trades) == 1
    assert trades[0]["wal_fsync"] is True
    assert trades[0]["quantity"] == "0.55000000"
    assert trades[0]["price"] == "100.1"


def test_soft_book_ticker_still_drives_long_entry_at_ask(env):
    _cfg, _repo, engine, _epoch_root, _ep = env
    proc = _processor(env)
    mono = _seed_ready(proc, bid=64000.0, ask=64001.5, agg_id=11)
    # Refresh soft BBO after seed (still no extra fsync beyond the one aggTrade).
    fsync_after_seed = proc.wal.fsync_count
    _book(proc, bid=64000.0, ask=64001.5, mono=mono + 5)
    assert proc.wal.fsync_count == fsync_after_seed

    local = engine.bbo.latest
    assert local is not None
    assert local.best_bid == pytest.approx(64000.0)
    assert local.best_ask == pytest.approx(64001.5)
    assert fill_price_for(side="LONG", action="ENTRY", bbo=local) == pytest.approx(64001.5)

    acts = engine.process_context_event(
        _ctx(
            eid="long_ask",
            etype="CONTEXT_START",
            tf="M15",
            prev="OBSERVE",
            new="LONG_CONTEXT",
            mono=mono + 10,
            bid=64000.0,
            ask=64001.5,
        )
    )
    assert acts and acts[0]["status"] == "ENTERED"
    fill = acts[0]["fill"]
    assert fill["paper_fill_price"] == pytest.approx(64001.5)
    assert fill["best_ask"] == pytest.approx(64001.5)
    assert fill["best_bid"] == pytest.approx(64000.0)


def test_soft_book_ticker_still_drives_short_entry_at_bid(env):
    _cfg, _repo, engine, _epoch_root, _ep = env
    proc = _processor(env)
    mono = _seed_ready(proc, bid=63990.0, ask=63992.0, agg_id=12)
    _book(proc, bid=63990.0, ask=63992.0, mono=mono + 5)

    acts = engine.process_context_event(
        _ctx(
            eid="short_bid",
            etype="CONTEXT_START",
            tf="M15",
            prev="OBSERVE",
            new="SHORT_CONTEXT",
            mono=mono + 10,
            bid=63990.0,
            ask=63992.0,
        )
    )
    assert acts and acts[0]["status"] == "ENTERED"
    fill = acts[0]["fill"]
    assert fill["paper_fill_price"] == pytest.approx(63990.0)
    assert fill_price_for(side="SHORT", action="ENTRY", bbo=engine.bbo.latest) == pytest.approx(
        63990.0
    )


def test_soft_book_ticker_context_exit_uses_opposite_side_of_book(env):
    _cfg, _repo, engine, _epoch_root, _ep = env
    proc = _processor(env)
    mono = _seed_ready(proc, bid=100.0, ask=100.2, agg_id=13)
    entered = engine.process_context_event(
        _ctx(
            eid="enter_long",
            etype="CONTEXT_START",
            tf="M15",
            prev="OBSERVE",
            new="LONG_CONTEXT",
            mono=mono + 10,
            bid=100.0,
            ask=100.2,
        )
    )
    assert entered[0]["status"] == "ENTERED"

    exit_mono = mono + 1_000_000
    _book(proc, bid=101.0, ask=101.2, mono=exit_mono)
    exited = engine.process_context_event(
        _ctx(
            eid="exit_long",
            etype="CONTEXT_END",
            tf="M15",
            prev="LONG_CONTEXT",
            new="OBSERVE",
            mono=exit_mono + 10,
            bid=101.0,
            ask=101.2,
        )
    )
    assert exited and exited[0]["status"] == "EXITED"
    fill = exited[0]["fill"]
    # LONG EXIT = bid
    assert fill["paper_fill_price"] == pytest.approx(101.0)
    bid = fill.get("best_bid", fill.get("fill_bid"))
    ask = fill.get("best_ask", fill.get("fill_ask"))
    assert bid == pytest.approx(101.0)
    assert ask == pytest.approx(101.2)


def test_volume_rows_survive_interleaved_soft_book_tickers(env):
    proc = _processor(env)
    _book(proc, bid=100.0, ask=100.2)
    _agg(proc, agg_id=1, price=100.05, quantity="0.010")
    _book(proc, bid=100.1, ask=100.3)
    _agg(proc, agg_id=2, price=100.20, quantity="2.50000001")
    _book(proc, bid=100.2, ask=100.4)

    rows = _wal_rows(proc)
    trades = [r for r in rows if r["event_type"] == EVENT_AGG_TRADE]
    assert [t["aggregate_trade_id"] for t in trades] == [1, 2]
    assert [t["quantity"] for t in trades] == ["0.010", "2.50000001"]
    assert all(t["wal_fsync"] is True for t in trades)
    assert all(
        r["wal_fsync"] is False for r in rows if r["event_type"] == EVENT_BOOK_TICKER
    )
    # Soft books never fsync alone; each aggTrade does pre_agg flush + hard fsync.
    assert proc.wal.fsync_count == 4
    assert proc.wal.last_confirmed_agg_trade_id == 2


def test_tp_sl_fill_uses_agg_trade_price_not_bbo_after_soft_books(env):
    _cfg, _repo, engine, _epoch_root, _ep = env
    proc = _processor(env)
    mono = _seed_ready(proc, bid=100.0, ask=100.2, agg_id=20)
    entered = engine.process_context_event(
        _ctx(
            eid="pos_for_tp",
            etype="CONTEXT_START",
            tf="M15",
            prev="OBSERVE",
            new="LONG_CONTEXT",
            mono=mono + 10,
            bid=100.0,
            ask=100.2,
        )
    )
    assert entered[0]["status"] == "ENTERED"
    pos = engine.positions["M15"]
    # Soft BBO far from TP, then aggTrade crosses take-profit.
    _book(proc, bid=100.5, ask=100.7, mono=mono + 20)
    tp = float(pos.take_profit_price)
    result = _agg(proc, agg_id=99, price=tp + 1.0, quantity="0.77")
    assert result["quantity"] == "0.77"

    fills = [f for f in engine.books.read_all("fills") if f.get("action") == "EXIT"]
    assert fills, "expected protective EXIT fill"
    # Protective exit prices from aggTrade, not from the soft BBO mid/ask.
    assert float(fills[-1]["paper_fill_price"]) == pytest.approx(tp + 1.0)
    assert "M15" not in engine.positions


def test_wal_append_api_defaults_remain_hard_durable(tmp_path: Path):
    wal = ExecutionMarketWAL(tmp_path / "wal", paper_epoch_id="E")
    ok = wal.append(
        {
            "event_type": EVENT_AGG_TRADE,
            "aggregate_trade_id": 1,
            "price": "1",
            "quantity": "9.9",
        }
    )
    assert ok.ok
    assert wal.fsync_count == 1
    row = json.loads(wal.events_path.read_text(encoding="utf-8").strip())
    assert row["quantity"] == "9.9"
    assert row["wal_fsync"] is True


def test_periodic_fsync_hardens_soft_book_ticker_bytes(tmp_path: Path):
    wal = ExecutionMarketWAL(tmp_path / "wal", paper_epoch_id="E")
    wal.soft_fsync_interval_ms = 1.0
    soft = wal.append(
        {
            "event_type": EVENT_BOOK_TICKER,
            "best_bid": "100.0",
            "best_ask": "100.2",
            "book_update_id": "1",
        },
        fsync=False,
        update_state=False,
    )
    assert soft.ok
    assert wal.fsync_count == 0
    assert wal._soft_dirty is True
    assert wal.state_write_count == 0

    # Pin the durability clock so the interval is deterministic in tests.
    wal._last_durable_mono_ns = 1_000_000
    assert wal.maybe_periodic_flush(now_mono_ns=1_000_500) is False
    assert wal.fsync_count == 0

    assert wal.maybe_periodic_flush(now_mono_ns=3_000_000) is True
    assert wal.fsync_count == 1
    assert wal.periodic_fsync_count == 1
    assert wal.state_write_count == 1
    assert wal._soft_dirty is False
    state = json.loads(wal.state_path.read_text(encoding="utf-8"))
    assert int(state["last_wal_offset"]) == soft.wal_offset


def test_pre_agg_trade_flush_clears_soft_dirty_before_volume(env):
    proc = _processor(env)
    proc.wal.soft_fsync_interval_ms = 60_000.0  # avoid timer path
    _book(proc, bid=100.0, ask=100.2)
    assert proc.wal._soft_dirty is True
    assert proc.wal.fsync_count == 0
    _agg(proc, agg_id=5, price=100.1, quantity="0.42")
    # pre_agg_trade flush + hard aggTrade fsync
    assert proc.wal.fsync_count >= 2
    assert proc.wal._soft_dirty is False
    trades = [r for r in _wal_rows(proc) if r["event_type"] == EVENT_AGG_TRADE]
    assert trades[-1]["quantity"] == "0.42"
