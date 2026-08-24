"""Tests for missed take-profit ledger recovery."""

from __future__ import annotations

from pathlib import Path

from btc_ml.trading.intrabar_paper.books import EpochBooks
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.position_invalidation import latest_position_row
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger
from btc_ml.trading.intrabar_paper.take_profit_recovery import (
    find_recovery_trade,
    find_strategy_trade_for_position,
    recover_missed_take_profit,
)


def _seed_open_position(books: EpochBooks, *, position_id: str = "pos_tp_open") -> dict:
    row = {
        "position_id": position_id,
        "timeframe": "M15",
        "side": "LONG",
        "quantity": 0.5,
        "entry_price": 78338.7,
        "stop_loss_price": 77555.313,
        "take_profit_price": 79513.78,
        "risk_amount_usd": 521.33,
        "lifecycle_episode_id": "M15:551",
        "entry_context_event_id": "CTX_test",
        "entry_fill_id": "fill_test",
        "entry_command_id": "cmd_test",
        "entry_monotonic_ns": 1,
        "opened_at": "2026-08-24T11:36:27.905730Z",
        "status": "OPEN",
    }
    books.append("positions", row)
    return row


def _seed_closed_wrong(books: EpochBooks, *, position_id: str = "pos_tp_closed") -> dict:
    open_row = _seed_open_position(books, position_id=position_id)
    books.append(
        "trades",
        {
            "trade_id": "trd_wrong",
            "position_id": position_id,
            "timeframe": "M15",
            "side": "LONG",
            "quantity": open_row["quantity"],
            "entry_price": open_row["entry_price"],
            "exit_price": 78721.1,
            "gross_pnl_usd": 221.48,
            "net_pnl_usd": 162.32,
            "fees_usd": 31.87,
            "slippage_usd": 27.29,
            "entry_fee_usd": 9.07,
            "exit_fee_usd": 22.8,
            "risk_amount_usd": open_row["risk_amount_usd"],
            "exit_reason": "S41_COMMAND_CLOSE",
            "status": "CLOSED",
        },
    )
    closed = dict(open_row)
    closed.update(
        {
            "status": "CLOSED",
            "exit_price": 78721.1,
            "exit_reason": "S41_COMMAND_CLOSE",
            "closed_at": "2026-08-24T17:28:22.815989Z",
        }
    )
    books.append("positions", closed)
    return closed


def _env(tmp_path: Path):
    epoch_id = "TEST_EPOCH_TP_RECOVERY"
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
    books = EpochBooks(books_dir, paper_epoch_id=epoch_id)
    return books, cfg, epoch_root


def test_open_position_take_profit_recovery(tmp_path: Path) -> None:
    books, cfg, epoch_root = _env(tmp_path)
    _seed_open_position(books)
    result = recover_missed_take_profit(
        books,
        position_id="pos_tp_open",
        exit_price=79513.78,
        cfg=cfg,
        epoch_root=epoch_root,
    )
    assert result["status"] == "RECOVERED"
    latest = latest_position_row(books, "pos_tp_open")
    assert latest is not None
    assert latest["status"] == "CLOSED"
    assert float(latest["exit_price"]) == 79513.78
    assert latest["exit_reason"] == "TP"


def test_wrong_close_restatement_supersedes_old_trade(tmp_path: Path) -> None:
    books, cfg, epoch_root = _env(tmp_path)
    _seed_closed_wrong(books)
    result = recover_missed_take_profit(
        books,
        position_id="pos_tp_closed",
        exit_price=79513.78,
        cfg=cfg,
        epoch_root=epoch_root,
    )
    assert result["status"] == "RECOVERED"
    assert result["superseded_trade_id"] == "trd_wrong"
    effective = find_strategy_trade_for_position(books, "pos_tp_closed")
    assert effective is not None
    assert effective["trade_id"] != "trd_wrong"
    assert float(effective["exit_price"]) == 79513.78
    assert effective["exit_reason"] == "TP"
    assert find_recovery_trade(books, "pos_tp_closed") is not None
    assert len(books.closed_trades()) == 1
