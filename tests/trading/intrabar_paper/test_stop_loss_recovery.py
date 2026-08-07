"""Tests for missed stop-loss ledger recovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.trading.intrabar_paper.books import EpochBooks
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.ops_adapter import build_intrabar_epoch_performance_summary
from btc_ml.trading.intrabar_paper.position_invalidation import latest_position_row
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger
from btc_ml.trading.intrabar_paper.stop_loss_recovery import (
    RECOVERY_REASON_SYSTEM_BUG_STOP_LOSS,
    find_recovery_trade,
    recover_missed_stop_loss,
)


def _seed_open_position(books: EpochBooks, *, position_id: str = "pos_ca1a44f61465480c") -> dict:
    row = {
        "position_id": position_id,
        "timeframe": "M30",
        "side": "LONG",
        "quantity": 1.3450564468071933,
        "entry_price": 65259.26,
        "stop_loss_price": 64606.6674,
        "take_profit_price": 66238.1489,
        "risk_amount_usd": 1008.5621924502044,
        "lifecycle_episode_id": "M30:prov:19",
        "entry_context_event_id": "CTX_2837b7021bc58a0654f3",
        "entry_fill_id": "fill_eb93477c99984e1c",
        "entry_command_id": "cmd_63975eacaa3f4910",
        "entry_monotonic_ns": 2_356_367_978_420_416,
        "opened_at": "2026-08-07T12:50:10.733022Z",
        "status": "OPEN",
    }
    books.append("positions", row)
    return row


@pytest.fixture
def recovery_env(tmp_path: Path):
    epoch_id = "TEST_EPOCH_SL_RECOVERY"
    repo = tmp_path / "repo"
    epoch_root = repo / "data" / "trading" / "intrabar_paper" / epoch_id
    books_dir = epoch_root / "books"
    books_dir.mkdir(parents=True)
    (repo / "config").mkdir(parents=True)
    cfg_src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    (repo / "config" / "intrabar_paper_execution.json").write_text(
        cfg_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    cfg = load_intrabar_paper_config(repo_root=repo)
    SleeveLedger.initialize(epoch_id=epoch_id, epoch_root=epoch_root, initial_equity_usd=100000.0)
    sleeves = SleeveLedger.load(epoch_root)
    assert sleeves is not None
    sleeves.mark_open("M30", "pos_ca1a44f61465480c", 1008.5621924502044)
    books = EpochBooks(books_dir, paper_epoch_id=epoch_id)
    return books, cfg, epoch_root, epoch_id, repo


def test_stop_loss_recovery_closes_position_and_updates_sleeves(recovery_env):
    books, cfg, epoch_root, epoch_id, repo = recovery_env
    _seed_open_position(books)

    result = recover_missed_stop_loss(
        books,
        position_id="pos_ca1a44f61465480c",
        exit_price=64606.6674,
        cfg=cfg,
        epoch_root=epoch_root,
    )

    assert result["status"] == "RECOVERED"
    latest = latest_position_row(books, "pos_ca1a44f61465480c")
    assert latest is not None
    assert latest["status"] == "CLOSED"
    assert latest["exit_reason"] == "SL"
    assert latest["exit_price"] == pytest.approx(64606.6674)
    assert latest["recovery_reason"] == RECOVERY_REASON_SYSTEM_BUG_STOP_LOSS
    assert latest["stop_trigger_time_known"] is False

    trade = find_recovery_trade(books, "pos_ca1a44f61465480c")
    assert trade is not None
    assert trade["exit_reason"] == "SL"
    assert trade["exit_price"] == pytest.approx(64606.6674)
    assert trade["net_pnl_usd"] == pytest.approx(-1008.5621924502044)
    assert trade["r_multiple"] == pytest.approx(-1.0) if "r_multiple" in trade else True

    fill_rows = [r for r in books.read_all("fills") if r.get("position_id") is None and r.get("trigger_type") == "SL"]
    assert len(fill_rows) == 1
    assert fill_rows[0]["paper_fill_price"] == pytest.approx(64606.6674)
    assert fill_rows[0]["gross_exit_price"] == pytest.approx(64606.6674)

    sleeves = SleeveLedger.load(epoch_root)
    assert sleeves is not None
    m30 = sleeves.get("M30")
    assert m30.open_position_id is None
    assert m30.closed_trades_count == 1
    assert m30.cumulative_realized_net_pnl_usd == pytest.approx(-1008.5621924502044)

    assert books.open_positions() == []
    assert len(books.read_all("positions")) == 2

    summary = build_intrabar_epoch_performance_summary(
        epoch={
            "paper_epoch_id": epoch_id,
            "initial_equity_usd": 400000.0,
            "rule_contract_version": "INTRABAR_RULES_V1",
            "epoch_status": "ACTIVE",
        },
        repo_root=repo,
    )
    assert summary["trades_count"] == 1
    assert summary["realized_pnl_usd"] == pytest.approx(-1008.5621924502044)
    assert summary["active_positions"] == 0


def test_stop_loss_recovery_is_idempotent(recovery_env):
    books, cfg, epoch_root, _, _ = recovery_env
    _seed_open_position(books)

    first = recover_missed_stop_loss(
        books,
        position_id="pos_ca1a44f61465480c",
        exit_price=64606.6674,
        cfg=cfg,
        epoch_root=epoch_root,
    )
    second = recover_missed_stop_loss(
        books,
        position_id="pos_ca1a44f61465480c",
        exit_price=64606.6674,
        cfg=cfg,
        epoch_root=epoch_root,
    )

    assert first["status"] == "RECOVERED"
    assert second["status"] == "ALREADY_RECOVERED"
    assert len([r for r in books.read_all("trades") if r.get("position_id") == "pos_ca1a44f61465480c"]) == 1
    assert len([r for r in books.read_all("fills") if r.get("trigger_type") == "SL"]) == 1
