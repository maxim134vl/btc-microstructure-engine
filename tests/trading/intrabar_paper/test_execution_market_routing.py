"""Targeted tests for LIVE1B dual Futures WebSocket routing (PUBLIC + MARKET)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch
from btc_ml.trading.intrabar_paper.execution_market_processor import ExecutionMarketProcessor
from btc_ml.trading.intrabar_paper.execution_market_state import ExecutionMarketState
from btc_ml.trading.intrabar_paper.execution_market_wal import EVENT_AGG_TRADE, EVENT_BOOK_TICKER


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
        create_epoch(epochs_root=cfg.epochs_root, initial_equity_usd=cfg.initial_equity_usd, utc_stamp="ROUTETEST"),
        epochs_root=cfg.epochs_root,
    )
    engine = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    epoch_root = cfg.books_root / ep.paper_epoch_id
    return cfg, repo, engine, epoch_root, ep


def _processor(env, *, fetch_agg_trades=None) -> ExecutionMarketProcessor:
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
    return proc


def _public_book_payload() -> dict:
    return {
        "stream": "btcusdt@bookTicker",
        "data": {"u": 1, "b": "100.0", "a": "100.2", "E": 1},
    }


def _market_agg_payload(agg_id: int, price: float = 100.0) -> dict:
    return {
        "stream": "btcusdt@aggTrade",
        "data": {"e": "aggTrade", "a": agg_id, "p": str(price), "q": "0.01", "T": 1, "m": False},
    }


def test_a_public_bookticker_route(env):
    proc = _processor(env)
    proc.on_public_websocket_connected()
    actions = proc.handle_public_ws_payload(_public_book_payload())
    assert actions[0]["status"] == "BOOK_TICKER_DISPATCHED"
    assert proc.dispatch_log[-1][0] == EVENT_BOOK_TICKER
    assert proc.wal.last_offset >= 1
    wal_event = next(proc.wal.iter_from_offset(0))
    assert wal_event["event_type"] == EVENT_BOOK_TICKER
    assert wal_event["connection_session_id"] == proc.public_connection_session_id


def test_b_market_aggtrade_route(env):
    proc = _processor(env)
    proc.on_public_websocket_connected()
    proc.on_market_websocket_connected()
    proc.handle_public_ws_payload(_public_book_payload())
    actions = proc.handle_market_ws_payload(_market_agg_payload(100))
    assert actions[0]["status"] == "AGG_TRADE_DISPATCHED"
    assert proc.dispatch_log[-1][0] == EVENT_AGG_TRADE
    assert proc.wal.last_confirmed_agg_trade_id == 100
    wal_event = next(e for e in proc.wal.iter_from_offset(0) if e["event_type"] == EVENT_AGG_TRADE)
    assert wal_event["connection_session_id"] == proc.market_connection_session_id


def test_c_public_connected_market_disconnected_not_healthy(env):
    proc = _processor(env)
    proc.on_public_websocket_connected()
    proc.handle_public_ws_payload(_public_book_payload())
    proc.handle_market_ws_payload(_market_agg_payload(100))
    assert proc.state.state != ExecutionMarketState.HEALTHY
    assert proc.execution_market_ready_for_entry() is False


def test_d_market_connected_public_disconnected_protective_still_works(env):
    from datetime import datetime, timedelta, timezone

    cfg, _repo, engine, _epoch_root, _ep = env
    ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    engine.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=2_000_000,
        receive_timestamp=ts,
        book_update_id="1",
        domain="context",
    )
    engine.process_context_event(
        {
            "context_event_id": "CTX_route_d",
            "event_type": "CONTEXT_START",
            "timeframe": "M15",
            "previous_context": "OBSERVE",
            "new_context": "LONG_CONTEXT",
            "event_monotonic_ns": 2_000_000,
            "event_timestamp": ts,
            "decision_available_at": ts,
            "best_bid": 100.0,
            "best_ask": 100.2,
            "bbo_receive_monotonic_ns": 1_999_000,
            "book_update_id": "1",
            "lifecycle_episode_id": "ep_route_d",
        }
    )
    proc = _processor(env)
    proc.on_market_websocket_connected()
    pos = engine.positions["M15"]
    actions = proc.handle_market_ws_payload(_market_agg_payload(200, float(pos.stop_loss_price) - 1.0))
    assert actions[0]["status"] == "AGG_TRADE_DISPATCHED"
    assert "M15" not in engine.positions
    assert proc.state.state != ExecutionMarketState.HEALTHY
    assert proc.execution_market_ready_for_entry() is False


def test_e_market_reconnect_continuous_id_becomes_healthy(env):
    proc = _processor(env)
    proc.on_public_websocket_connected()
    proc.on_market_websocket_connected()
    proc.handle_public_ws_payload(_public_book_payload())
    proc.handle_market_ws_payload(_market_agg_payload(100))
    proc.state._set(ExecutionMarketState.HEALTHY, "seed")
    proc.on_market_websocket_disconnected()
    assert proc.state.state == ExecutionMarketState.DEGRADED
    proc.on_market_websocket_connected()
    proc.handle_public_ws_payload(_public_book_payload())
    proc.handle_market_ws_payload(_market_agg_payload(101))
    assert proc.state.state == ExecutionMarketState.HEALTHY
    assert proc.execution_market_ready_for_entry() is True


def test_f_market_reconnect_gap_triggers_backfill(env):
    def fetch(_symbol: str, start: int, end: int):
        return [{"a": i, "p": "100.0", "q": "0.01", "T": 1, "m": False} for i in range(start, end + 1)]

    proc = _processor(env, fetch_agg_trades=fetch)
    proc.on_public_websocket_connected()
    proc.on_market_websocket_connected()
    proc.handle_public_ws_payload(_public_book_payload())
    proc.handle_market_ws_payload(_market_agg_payload(100))
    proc.state._set(ExecutionMarketState.HEALTHY, "seed")
    proc.on_market_websocket_disconnected()
    proc.on_market_websocket_connected()
    actions = proc.handle_market_ws_payload(_market_agg_payload(105))
    assert any(a.get("status") == "AGG_TRADE_DISPATCHED" for a in actions)
    assert proc.wal.last_confirmed_agg_trade_id == 105
    assert proc.state.state == ExecutionMarketState.HEALTHY
