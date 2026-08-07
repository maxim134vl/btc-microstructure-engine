"""Targeted tests for LIVE1B execution market WAL and continuity."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch
from btc_ml.trading.intrabar_paper.execution_market_processor import (
    ExecutionMarketProcessor,
    normalize_futures_agg_trade,
    normalize_futures_book_ticker,
)
from btc_ml.trading.intrabar_paper.execution_market_state import ExecutionMarketState


@pytest.fixture
def env(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    cfg_src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    (repo / "config" / "intrabar_paper_execution.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    cfg = load_intrabar_paper_config(repo_root=repo)
    ep = activate_epoch(
        create_epoch(epochs_root=cfg.epochs_root, initial_equity_usd=cfg.initial_equity_usd, utc_stamp="WALTEST"),
        epochs_root=cfg.epochs_root,
    )
    engine = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    epoch_root = cfg.books_root / ep.paper_epoch_id
    return cfg, repo, engine, epoch_root, ep


def _processor(
    env,
    *,
    fetch_agg_trades=None,
) -> ExecutionMarketProcessor:
    cfg, _repo, engine, epoch_root, ep = env
    proc = ExecutionMarketProcessor.create(
        engine=engine,
        epoch_root=epoch_root,
        paper_epoch_id=ep.paper_epoch_id,
        max_bbo_age_ms=cfg.max_bbo_age_ms,
        max_agg_trade_age_ms=cfg.max_agg_trade_age_ms,
        fetch_agg_trades=fetch_agg_trades,
    )
    engine.attach_execution_market(proc)
    proc.on_websocket_connected()
    return proc


def _book(proc: ExecutionMarketProcessor, *, mono: int | None = None) -> None:
    mono = mono or time.monotonic_ns()
    event = normalize_futures_book_ticker(
        {"u": mono, "b": "100.0", "a": "100.2", "E": 1},
        symbol="BTCUSDT",
        connection_session_id=proc.public_connection_session_id,
        receive_monotonic_ns=mono,
        receive_timestamp="2026-08-07T00:00:00Z",
    )
    proc._process_book_ticker(event)


def _agg(proc: ExecutionMarketProcessor, agg_id: int, price: float, *, mono: int | None = None) -> dict[str, Any]:
    mono = mono or time.monotonic_ns()
    event = normalize_futures_agg_trade(
        {"a": agg_id, "p": str(price), "q": "0.01", "T": 1, "m": False},
        symbol="BTCUSDT",
        connection_session_id=proc.market_connection_session_id,
        receive_monotonic_ns=mono,
        receive_timestamp="2026-08-07T00:00:00Z",
    )
    return proc._persist_and_dispatch_agg_trade(event)


def _ctx_start(env, engine: IntrabarPaperEngine, mono: int = 2_000_000):
    ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    return {
        "context_event_id": "CTX_entry_gate",
        "event_type": "CONTEXT_START",
        "timeframe": "M15",
        "previous_context": "OBSERVE",
        "new_context": "LONG_CONTEXT",
        "event_monotonic_ns": mono,
        "event_timestamp": ts,
        "decision_available_at": ts,
        "best_bid": 100.0,
        "best_ask": 100.2,
        "bbo_receive_monotonic_ns": mono - 1000,
        "book_update_id": "1",
        "lifecycle_episode_id": "ep_gate",
    }


def test_01_wal_before_dispatch(env):
    proc = _processor(env)
    _book(proc)
    proc.wal_append_log.clear()
    proc.dispatch_log.clear()
    _agg(proc, 100, 100.0)
    assert proc.wal_append_log
    assert proc.dispatch_log
    assert proc.wal_append_log[0] <= proc.dispatch_log[0][1]


def test_02_transient_reconnect_recovers(env):
    proc = _processor(env)
    _book(proc)
    _agg(proc, 100, 100.0)
    proc.state._set(ExecutionMarketState.HEALTHY, "seed")
    proc.on_websocket_disconnected()
    assert proc.state.state == ExecutionMarketState.DEGRADED
    proc.on_websocket_connected()
    _book(proc)
    _agg(proc, 101, 100.1)
    assert proc.state.state == ExecutionMarketState.HEALTHY
    assert proc.execution_market_ready_for_entry() is True


def test_03_gap_successful_backfill(env):
    def fetch(_symbol: str, start: int, end: int):
        return [{"a": i, "p": "100.0", "q": "0.01", "T": 1, "m": False} for i in range(start, end + 1)]

    proc = _processor(env, fetch_agg_trades=fetch)
    _book(proc)
    _agg(proc, 100, 100.0)
    proc.state._set(ExecutionMarketState.HEALTHY, "seed")
    actions = proc._process_agg_trade_live(
        normalize_futures_agg_trade(
            {"a": 105, "p": "100.0", "q": "0.01", "T": 1, "m": False},
            symbol="BTCUSDT",
            connection_session_id=proc.market_connection_session_id,
            receive_monotonic_ns=time.monotonic_ns(),
            receive_timestamp="2026-08-07T00:00:00Z",
        )
    )
    assert any(a.get("status") == "AGG_TRADE_DISPATCHED" for a in actions)
    assert proc.state.state == ExecutionMarketState.HEALTHY
    assert proc.wal.last_confirmed_agg_trade_id == 105


def test_04_unresolved_gap_blocks_entry(env):
    def fetch_fail(*_args, **_kwargs):
        raise RuntimeError("backfill unavailable")

    proc = _processor(env, fetch_agg_trades=fetch_fail)
    _book(proc)
    _agg(proc, 100, 100.0)
    proc.state._set(ExecutionMarketState.HEALTHY, "seed")
    actions = proc._process_agg_trade_live(
        normalize_futures_agg_trade(
            {"a": 105, "p": "100.0", "q": "0.01", "T": 1, "m": False},
            symbol="BTCUSDT",
            connection_session_id=proc.market_connection_session_id,
            receive_monotonic_ns=time.monotonic_ns(),
            receive_timestamp="2026-08-07T00:00:00Z",
        )
    )
    assert actions[0]["status"] == "BACKFILL_FAILED"
    assert proc.state.state == ExecutionMarketState.UNSAFE
    cfg, _repo, engine, _epoch_root, _ep = env
    engine.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=2_000_000,
        receive_timestamp="2026-08-07T00:00:00Z",
        book_update_id="1",
        domain="context",
    )
    blocked = engine.process_context_event(_ctx_start(env, engine))
    assert blocked[0]["status"] == "ENTRY_BLOCKED_EXECUTION_MARKET_NOT_READY"


def test_05_book_ticker_reconnect_without_backfill(env):
    proc = _processor(env)
    proc.on_websocket_disconnected()
    proc.on_websocket_connected()
    _book(proc)
    assert proc.state.last_book_ticker_monotonic_ns is not None


def test_06_wal_transient_write_error_recovers(env):
    proc = _processor(env)
    _book(proc)
    proc.wal.inject_fail_next_appends(1)
    result = _agg(proc, 100, 100.0)
    assert result["status"] == "AGG_TRADE_DISPATCHED"
    assert proc.state.state in {ExecutionMarketState.HEALTHY, ExecutionMarketState.DEGRADED, ExecutionMarketState.STARTING}


def test_07_persistent_wal_failure_blocks_entry(env):
    cfg, _repo, engine, epoch_root, ep = env
    engine.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=2_000_000,
        domain="context",
    )
    engine.process_context_event(_ctx_start(env, engine))
    proc = _processor(env)
    _book(proc)
    proc.wal.inject_fail_next_appends(4)
    _agg(proc, 99, 100.0)
    proc.wal.inject_fail_next_appends(2)
    result = _agg(proc, 100, 100.0)
    assert result["status"] == "WAL_APPEND_FAILED"
    assert proc.state.state == ExecutionMarketState.UNSAFE
    blocked = engine.process_context_event(
        {
            **_ctx_start(env, engine, mono=3_000_000),
            "context_event_id": "CTX_entry_blocked_2",
            "timeframe": "M30",
            "lifecycle_episode_id": "ep_gate_2",
        }
    )
    assert blocked[0]["status"] == "ENTRY_BLOCKED_EXECUTION_MARKET_NOT_READY"


def test_08_open_position_wal_failure_sl_still_executes(env):
    cfg, _repo, engine, _epoch_root, _ep = env
    engine.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=2_000_000,
        domain="context",
    )
    engine.process_context_event(_ctx_start(env, engine, mono=2_000_000))
    proc = _processor(env)
    pos = engine.positions["M15"]
    proc.wal.inject_fail_next_appends(10)
    result = _agg(proc, 200, float(pos.stop_loss_price) - 1.0)
    assert result["status"] == "PROTECTIVE_EXIT_DURABILITY_DEGRADED"
    assert "M15" not in engine.positions
    assert proc.state.state in {ExecutionMarketState.UNSAFE, ExecutionMarketState.DEGRADED}


def test_09_sl_normal_path_records_wal_provenance(env):
    cfg, _repo, engine, _epoch_root, _ep = env
    engine.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=2_000_000,
        domain="context",
    )
    engine.process_context_event(_ctx_start(env, engine, mono=2_000_000))
    proc = _processor(env)
    pos = engine.positions["M15"]
    _book(proc)
    _agg(proc, 300, float(pos.stop_loss_price) - 1.0)
    cmd = engine.last_command
    assert cmd is not None
    assert cmd["trigger_type"] == "SL"
    assert cmd["aggregate_trade_id"] == 300
    assert cmd["execution_market_wal_offset"] is not None
    assert cmd["execution_market_source"] == "BINANCE_FUTURES"


def test_10_book_ticker_alone_does_not_trigger_sl(env):
    cfg, _repo, engine, _epoch_root, _ep = env
    engine.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=2_000_000,
        domain="context",
    )
    engine.process_context_event(_ctx_start(env, engine, mono=2_000_000))
    proc = _processor(env)
    pos = engine.positions["M15"]
    _book(proc)
    assert "M15" in engine.positions
    event = normalize_futures_book_ticker(
        {"u": 999, "b": str(pos.stop_loss_price - 10), "a": str(pos.stop_loss_price - 9), "E": 1},
        symbol="BTCUSDT",
        connection_session_id=proc.public_connection_session_id,
        receive_monotonic_ns=time.monotonic_ns(),
        receive_timestamp="2026-08-07T00:00:00Z",
    )
    proc._process_book_ticker(event)
    assert "M15" in engine.positions


def test_11_crash_replay_is_idempotent(env):
    proc = _processor(env)
    _book(proc)
    _agg(proc, 100, 100.0)
    first_trades = len(proc.engine.books.read_all("trades"))
    proc2 = ExecutionMarketProcessor.create(
        engine=proc.engine,
        epoch_root=env[3],
        paper_epoch_id=env[4].paper_epoch_id,
        max_bbo_age_ms=env[0].max_bbo_age_ms,
        max_agg_trade_age_ms=env[0].max_agg_trade_age_ms,
    )
    assert len(proc2.engine.books.read_all("trades")) == first_trades


def test_12_duplicate_agg_trade_prevented(env):
    proc = _processor(env)
    _book(proc)
    _agg(proc, 100, 100.0)
    dup = proc._process_agg_trade_live(
        normalize_futures_agg_trade(
            {"a": 100, "p": "100.0", "q": "0.01", "T": 1, "m": False},
            symbol="BTCUSDT",
            connection_session_id=proc.market_connection_session_id,
            receive_monotonic_ns=time.monotonic_ns(),
            receive_timestamp="2026-08-07T00:00:00Z",
        )
    )
    assert dup[0]["status"] == "DUPLICATE_AGG_TRADE_SKIPPED"
