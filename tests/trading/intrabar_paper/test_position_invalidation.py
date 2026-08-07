"""Tests for bug-generated position invalidation (Fix 3)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from btc_ml.live.intrabar.closed_bar_event_bridge import DELIVERY_MODE_RECOVERY, materialize_closed_bar_events
from btc_ml.live.intrabar.context_event_journal import ContextEventJournal
from btc_ml.trading.intrabar_paper.books import EpochBooks
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch
from btc_ml.trading.intrabar_paper.ops_adapter import build_intrabar_epoch_performance_summary
from btc_ml.trading.intrabar_paper.performance_eligibility import counts_toward_strategy_performance
from btc_ml.trading.intrabar_paper.position_invalidation import (
    INVALIDATION_REASON_SYSTEM_BUG,
    SYSTEM_CORRECTION_TELEGRAM_TEXT,
    invalidate_open_position,
    latest_position_row,
)
from btc_ml.live.intrabar.closed_bar_event_bridge import load_per_tf_recovery_watermarks as bridge_watermarks


def _utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def books(tmp_path: Path):
    epoch_id = "TEST_EPOCH_FIX3"
    repo = tmp_path / "repo"
    books_dir = repo / "data" / "trading" / "intrabar_paper" / epoch_id / "books"
    books_dir.mkdir(parents=True)
    return EpochBooks(books_dir, paper_epoch_id=epoch_id), epoch_id, repo


def _seed_open_bug_position(books: EpochBooks, *, position_id: str = "pos_74dd6b85bdc2434a") -> dict:
    row = {
        "position_id": position_id,
        "timeframe": "M15",
        "side": "SHORT",
        "quantity": 0.0154321,
        "entry_price": 64796.005,
        "stop_loss_price": 64148.045,
        "take_profit_price": 65567.945,
        "risk_amount_usd": 1000.0,
        "lifecycle_episode_id": "960.0",
        "entry_context_event_id": "CTX_6822f717283be583126f",
        "entry_fill_id": "fill_bug_entry",
        "entry_command_id": "cmd_bug_entry",
        "entry_monotonic_ns": 2_203_065_966_062_833,
        "opened_at": "2026-08-05T18:15:04.034358Z",
        "status": "OPEN",
        "internal_diagnostic_label": "M15_8",
    }
    books.append("positions", row)
    return row


def test_a_void_position_without_normal_trade_close(books):
    books_obj, _, _ = books
    _seed_open_bug_position(books_obj)
    result = invalidate_open_position(
        books_obj,
        position_id="pos_74dd6b85bdc2434a",
        invalidation_detail="Replay catch-up entry excluded from strategy performance.",
    )
    latest = latest_position_row(books_obj, "pos_74dd6b85bdc2434a")
    assert latest is not None
    assert latest["status"] == "VOID"
    assert latest["invalidation_reason"] == INVALIDATION_REASON_SYSTEM_BUG
    assert latest["strategy_pnl_included"] is False
    assert latest["statistics_included"] is False
    assert books_obj.open_positions() == []
    assert books_obj.read_all("trades") == []
    assert books_obj.read_all("fills") == []
    assert result["position"]["entry_context_event_id"] == "CTX_6822f717283be583126f"


def test_b_performance_exclusion(books):
    books_obj, epoch_id, repo = books
    _seed_open_bug_position(books_obj)
    books_obj.append(
        "trades",
        {
            "trade_id": "trade_good",
            "position_id": "pos_good",
            "timeframe": "M30",
            "side": "LONG",
            "quantity": 0.01,
            "entry_price": 100.0,
            "exit_price": 110.0,
            "gross_pnl_usd": 0.1,
            "net_pnl_usd": 0.08,
            "fees_usd": 0.01,
            "slippage_usd": 0.01,
            "entry_ts": "2026-08-06T01:00:00Z",
            "exit_ts": "2026-08-06T02:00:00Z",
            "status": "CLOSED",
            "lifecycle_episode_id": "ep_good",
        },
    )
    books_obj.append(
        "trades",
        {
            "trade_id": "trade_void",
            "position_id": "pos_74dd6b85bdc2434a",
            "timeframe": "M15",
            "side": "SHORT",
            "quantity": 0.01,
            "entry_price": 100.0,
            "exit_price": 90.0,
            "gross_pnl_usd": 0.1,
            "net_pnl_usd": 0.09,
            "fees_usd": 0.01,
            "slippage_usd": 0.01,
            "entry_ts": "2026-08-06T03:00:00Z",
            "exit_ts": "2026-08-06T04:00:00Z",
            "status": "VOID",
            "statistics_included": False,
            "strategy_pnl_included": False,
            "lifecycle_episode_id": "960.0",
        },
    )
    invalidate_open_position(books_obj, position_id="pos_74dd6b85bdc2434a")

    eligible = [t for t in books_obj.read_all("trades") if counts_toward_strategy_performance(t)]
    assert len(eligible) == 1
    assert eligible[0]["trade_id"] == "trade_good"
    summary = build_intrabar_epoch_performance_summary(
        epoch={
            "paper_epoch_id": epoch_id,
            "initial_equity_usd": 100000.0,
            "rule_contract_version": "INTRABAR_RULES_V1",
            "epoch_status": "ACTIVE",
        },
        repo_root=repo,
    )
    assert summary["trades_count"] == 1
    assert summary["realized_pnl_usd"] == pytest.approx(0.08)
    assert summary["active_positions"] == 0


def test_c_metrics_unchanged_by_void_record(books, tmp_path: Path):
    books_obj, epoch_id, repo = books
    books_obj.append(
        "trades",
        {
            "trade_id": "trade_only",
            "position_id": "pos_only",
            "timeframe": "M30",
            "side": "LONG",
            "quantity": 0.01,
            "entry_price": 100.0,
            "exit_price": 120.0,
            "gross_pnl_usd": 0.2,
            "net_pnl_usd": 0.15,
            "fees_usd": 0.03,
            "slippage_usd": 0.02,
            "entry_ts": "2026-08-06T01:00:00Z",
            "exit_ts": "2026-08-06T02:00:00Z",
            "status": "CLOSED",
            "lifecycle_episode_id": "ep_only",
        },
    )
    books_obj.append(
        "equity_snapshots",
        {
            "snapshot_ts": "2026-08-06T02:00:00Z",
            "equity_usd": 100000.15,
            "realized_pnl_usd": 0.15,
            "unrealized_pnl_usd": 0.0,
        },
    )
    before = build_intrabar_epoch_performance_summary(
        epoch={
            "paper_epoch_id": epoch_id,
            "initial_equity_usd": 100000.0,
            "rule_contract_version": "INTRABAR_RULES_V1",
            "epoch_status": "ACTIVE",
        },
        repo_root=repo,
    )
    _seed_open_bug_position(books_obj)
    invalidate_open_position(books_obj, position_id="pos_74dd6b85bdc2434a")
    after = build_intrabar_epoch_performance_summary(
        epoch={
            "paper_epoch_id": epoch_id,
            "initial_equity_usd": 100000.0,
            "rule_contract_version": "INTRABAR_RULES_V1",
            "epoch_status": "ACTIVE",
        },
        repo_root=repo,
    )
    assert before["trades_count"] == after["trades_count"] == 1
    assert before["realized_pnl_usd"] == after["realized_pnl_usd"] == pytest.approx(0.15)


def test_d_recovery_flip_after_void_has_no_economic_effect(tmp_path: Path, books):
    books_obj, epoch_id, repo = books
    cfg_src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    (repo / "config").mkdir(parents=True, exist_ok=True)
    (repo / "config" / "intrabar_paper_execution.json").write_text(json.dumps(raw, indent=2) + "\n")
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    cfg = load_intrabar_paper_config(repo_root=repo)
    ep = activate_epoch(
        create_epoch(epochs_root=cfg.epochs_root, initial_equity_usd=cfg.initial_equity_usd, utc_stamp="FIX3"),
        epochs_root=cfg.epochs_root,
    )
    eng = IntrabarPaperEngine(cfg=cfg, epoch=ep, books=books_obj, activation_monotonic_ns=6_000_000)
    _seed_open_bug_position(books_obj)
    invalidate_open_position(books_obj, position_id="pos_74dd6b85bdc2434a")
    eng = IntrabarPaperEngine(cfg=cfg, epoch=ep, books=books_obj, activation_monotonic_ns=6_000_000)
    assert "M15" not in eng.positions

    journal = ContextEventJournal(repo / "data" / "cognition" / "intrabar_context_events")
    journal.append(
        {
            "context_event_id": "CTX_6822f717283be583126f",
            "event_type": "CONTEXT_START",
            "timeframe": "M15",
            "previous_context": "OBSERVE",
            "new_context": "SHORT_CONTEXT",
            "lifecycle_episode_id": "960.0",
            "source_bar_timestamp": "2026-08-05T17:45:00Z",
            "decision_available_at": "2026-08-05T18:01:52.335375Z",
            "event_timestamp": "2026-08-05T18:01:52.335375Z",
            "direction": "SHORT",
            "provider_id": "LIVE1A_CANONICAL_INTRABAR_CONTEXT",
            "epoch_id": epoch_id,
            "source_decision_id": "ba8ff62d-0ce2-4281-8d36-79f50a005c7c",
        }
    )
    watermarks = bridge_watermarks(journal.path)
    flip_row = {
        "source_timeframe": "15m",
        "candle_timestamp": "2026-08-06T05:00:00Z",
        "decision_written_at_utc": "2026-08-06T05:16:59.773003Z",
        "decision_id": "m15-8-causal-long",
        "active_market_context": "LONG_CONTEXT",
        "previous_active_market_context": "OBSERVE",
        "lifecycle_episode_id": "963.0",
        "paper_action_candidate": "INTENT_OPEN_LONG",
        "intended_side": "LONG",
        "signal_eligibility_status": "ELIGIBLE_DIRECTIONAL_SIGNAL",
        "context_origin_timestamp": "2026-08-06T05:00:00Z",
        "close": 64920.5,
    }
    bridge_result = materialize_closed_bar_events(
        [flip_row],
        journal=journal,
        provider_id="LIVE1A_CANONICAL_INTRABAR_CONTEXT",
        epoch_id=epoch_id,
        current_bbo={
            "best_bid": 65100.0,
            "best_ask": 65100.01,
            "book_update_id": "recovery",
            "bbo_receive_monotonic_ns": 6_000_000,
            "bbo_receive_timestamp": "2026-08-06T06:00:00Z",
        },
        bridge_activated_at="2026-08-06T06:00:00Z",
        recovery_watermarks=watermarks,
        active_positions_by_timeframe=set(),
        traded_episodes=set(),
    )
    recovered = bridge_result.emitted[0]
    recovered["event_monotonic_ns"] = 6_000_000
    recovered["best_bid"] = 65100.0
    recovered["best_ask"] = 65100.01
    recovered["bbo_receive_monotonic_ns"] = 6_000_000
    eng.bbo.update_from_book_ticker(
        best_bid=65100.0,
        best_ask=65100.01,
        receive_monotonic_ns=6_000_000,
        receive_timestamp="2026-08-06T06:00:00Z",
        book_update_id="recovery",
        domain="context",
    )
    acts = eng.process_context_event(recovered)
    assert recovered["delivery_mode"] == DELIVERY_MODE_RECOVERY
    assert acts == [] or all(a.get("status") != "EXITED" for a in acts)
    assert "M15" not in eng.positions
    assert books_obj.read_all("trades") == []


def test_e_telegram_message_uses_m15_not_internal_ordinal(books):
    books_obj, _, _ = books
    _seed_open_bug_position(books_obj)
    result = invalidate_open_position(books_obj, position_id="pos_74dd6b85bdc2434a")
    event = result["telegram_event"]
    assert event is not None
    assert event["event_type"] == "SYSTEM_CORRECTION"
    assert event["severity"] == "WARNING"
    assert event["timeframe"] == "M15"
    assert "M15_8" not in event["message"]
    assert event["timeframe"] == "M15"
    assert "позиции M15" in SYSTEM_CORRECTION_TELEGRAM_TEXT


def test_f_audit_preservation(books):
    books_obj, _, _ = books
    original = _seed_open_bug_position(books_obj)
    invalidate_open_position(books_obj, position_id="pos_74dd6b85bdc2434a")
    rows = books_obj.read_all("positions")
    assert len(rows) == 2
    assert rows[0]["status"] == "OPEN"
    assert rows[1]["status"] == "VOID"
    void_row = rows[1]
    assert void_row["entry_context_event_id"] == original["entry_context_event_id"]
    assert void_row["entry_price"] == original["entry_price"]
    assert void_row["lifecycle_episode_id"] == original["lifecycle_episode_id"]
    assert void_row["invalidation_reason"] == INVALIDATION_REASON_SYSTEM_BUG
    audit_rows = [r for r in books_obj.read_all("metrics") if r.get("metric_type") == "POSITION_INVALIDATION"]
    assert len(audit_rows) == 1
    assert audit_rows[0]["position_id"] == "pos_74dd6b85bdc2434a"
