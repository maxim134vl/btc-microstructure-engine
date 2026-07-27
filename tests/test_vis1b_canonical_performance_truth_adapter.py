#!/usr/bin/env python3
"""VIS1B — canonical trading performance truth adapter tests."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.trading_performance_truth import (  # noqa: E402
    EXCLUDED_SOURCE_CATEGORIES,
    MTM_BASIS_GROSS,
    build_trading_performance_truth,
    write_candidate_artifacts,
)
from btc_ml.trading.paper_core import (  # noqa: E402
    ENTRY_FEE_BPS,
    EXIT_FEE_BPS,
    INITIAL_CAPITAL_USD,
    closed_trade_economics,
)
from btc_ml.trading.trader_book import PRODUCTION_BOOKS_ROOT  # noqa: E402


def _write_book(tf_dir: Path, *, signals, orders, fills, positions, trades=None) -> None:
    tf_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(signals).to_parquet(tf_dir / "signals.parquet", index=False)
    pd.DataFrame(orders).to_parquet(tf_dir / "orders.parquet", index=False)
    pd.DataFrame(fills).to_parquet(tf_dir / "fills.parquet", index=False)
    pd.DataFrame(positions).to_parquet(tf_dir / "positions.parquet", index=False)
    if trades is not None:
        pd.DataFrame(trades).to_parquet(tf_dir / "trades.parquet", index=False)


def _closed_chain(
    *,
    tf: str,
    suffix: str,
    episode: str,
    side: str = "LONG",
    entry: float = 100.0,
    exit_: float = 110.0,
    qty: float = 1.0,
) -> dict[str, list[dict]]:
    cmd = f"TF_CMD_{suffix}"
    sig = f"TF_SIGNAL_{tf}_{suffix}"
    order = f"TF_ORDER_{tf}_{suffix}"
    entry_fill = f"TF_FILL_{tf}_{suffix}_E"
    exit_fill = f"TF_FILL_{tf}_{suffix}_X"
    pos = f"TF_POSITION_{tf}_{suffix}"
    trade = f"TF_TRADE_{tf}_{suffix}"
    econ = closed_trade_economics(
        side=side, entry_price=entry, exit_price=exit_, position_size_btc=qty, risk_amount_usd=250.0
    )
    order_side_entry = "BUY" if side == "LONG" else "SELL"
    order_side_exit = "SELL" if side == "LONG" else "BUY"
    return {
        "signals": [
            {
                "signal_id": sig,
                "command_id": cmd,
                "context_episode_id": episode,
                "side": side,
                "signal_status": "ACCEPTED",
            }
        ],
        "orders": [
            {
                "paper_order_id": order,
                "command_id": cmd,
                "side": order_side_entry,
                "status": "FILLED",
                "timeframe": tf,
            }
        ],
        "fills": [
            {
                "paper_trade_id": entry_fill,
                "paper_order_id": order,
                "position_id": pos,
                "timestamp": "2026-07-21T00:00:00Z",
                "side": order_side_entry,
                "quantity": qty,
                "price": entry,
                "fee": econ["entry_fee_usd"],
                "slippage": econ["entry_slippage_usd"],
                "command_id": cmd,
            },
            {
                "paper_trade_id": exit_fill,
                "paper_order_id": order,
                "position_id": pos,
                "timestamp": "2026-07-21T01:00:00Z",
                "side": order_side_exit,
                "quantity": qty,
                "price": exit_,
                "fee": econ["exit_fee_usd"],
                "slippage": econ["exit_slippage_usd"],
                "command_id": cmd,
            },
        ],
        "positions": [
            {
                "position_id": pos,
                "status": "CLOSED",
                "direction": side,
                "quantity": qty,
                "entry_price": entry,
                "exit_price": exit_,
                "opened_at": "2026-07-21T00:00:00Z",
                "closed_at": "2026-07-21T01:00:00Z",
                "command_id": cmd,
                "paper_only": True,
                "execution_enabled": False,
            }
        ],
        "trades": [
            {
                "trade_id": trade,
                "timeframe": tf,
                "position_id": pos,
                "command_id": cmd,
                "lifecycle_episode_id": episode,
                "side": side,
                "quantity": qty,
                "entry_ts": "2026-07-21T00:00:00Z",
                "exit_ts": "2026-07-21T01:00:00Z",
                "entry_price": entry,
                "exit_price": exit_,
                "fees_usd": econ["fees_usd"],
                "slippage_usd": econ["slippage_usd"],
                "gross_pnl_usd": econ["gross_pnl_usd"],
                "net_pnl_usd": econ["net_pnl_usd"],
                "risk_amount_usd": 250.0,
                "entry_fill_id": entry_fill,
                "exit_fill_id": exit_fill,
                "exit_reason": "TEST",
                "paper_only": True,
                "execution_enabled": False,
            }
        ],
    }


def test_research_legacy_dashboard_excluded_categories():
    for name in (
        "RESEARCH_BAR_POLICY",
        "LEGACY_PAPER_CONTROLLER",
        "DASHBOARD_DERIVATION",
        "QUARANTINE_BACKUP",
    ):
        assert name in EXCLUDED_SOURCE_CATEGORIES


def test_contamination_fixture_keeps_closed_count_six(tmp_path: Path):
    """6 canonical + presence of excluded categories must not inflate closed count."""
    books = tmp_path / "books"
    # six canonical closed across TFs
    specs = [
        ("M15", "a1", "M15:743", 100.0, 110.0),
        ("M30", "a2", "M30:743", 100.0, 110.0),
        ("H1", "a3", "H1:743", 100.0, 110.0),
        ("M15", "b1", "M15:741", 100.0, 90.0),
        ("M30", "b2", "M30:741", 100.0, 90.0),
        ("H1", "b3", "H1:740", 100.0, 101.0),
    ]
    by_tf: dict[str, dict[str, list]] = {
        tf: {"signals": [], "orders": [], "fills": [], "positions": [], "trades": []}
        for tf in ("M15", "M30", "H1", "H4")
    }
    for tf, suffix, ep, entry, exit_ in specs:
        chain = _closed_chain(tf=tf, suffix=suffix, episode=ep, entry=entry, exit_=exit_)
        for k in by_tf[tf]:
            by_tf[tf][k].extend(chain[k])
    # H4 empty open book
    by_tf["H4"] = {
        "signals": [],
        "orders": [],
        "fills": [],
        "positions": [],
        "trades": [],
    }
    for tf, payload in by_tf.items():
        if payload["signals"] or tf == "H4":
            _write_book(
                books / tf,
                signals=payload["signals"]
                or [{"signal_id": "x", "command_id": "y", "context_episode_id": "H4:0", "side": "LONG", "signal_status": "X"}],
                orders=payload["orders"]
                or [{"paper_order_id": "o", "command_id": "y", "side": "BUY", "status": "NEW", "timeframe": tf}],
                fills=payload["fills"]
                or [
                    {
                        "paper_trade_id": "f",
                        "paper_order_id": "o",
                        "position_id": "p",
                        "timestamp": "2026-07-21T00:00:00Z",
                        "side": "BUY",
                        "quantity": 0.0,
                        "price": 0.0,
                        "fee": 0.0,
                        "slippage": 0.0,
                        "command_id": "y",
                    }
                ],
                positions=payload["positions"]
                or [
                    {
                        "position_id": "p",
                        "status": "FLAT",
                        "direction": "LONG",
                        "quantity": 0.0,
                        "entry_price": 0.0,
                        "command_id": "y",
                        "paper_only": True,
                        "execution_enabled": False,
                    }
                ],
                trades=payload["trades"] or None,
            )
    # Fake research/legacy files on disk must be ignored (adapter never reads them).
    research = tmp_path / "research"
    research.mkdir()
    (research / "policy_context_canonical_bar_policy_trades.json").write_text(
        json.dumps({"trades": [{"trade_id": f"R{i}"} for i in range(11)]})
    )
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "closed_trades.json").write_text(
        json.dumps({"closed_trades": [{"lineage_status": "LEGACY_GLOBAL"} for _ in range(4)]})
    )
    payload = build_trading_performance_truth(
        books_root=books,
        portfolio_summary_path=tmp_path / "missing_portfolio.json",
        mark_price=105.0,
        mark_timestamp="2026-07-21T02:00:00Z",
        excluded_research_count=11,
        excluded_legacy_count=4,
    )
    assert payload["portfolio"]["closed_trade_count"] == 6
    assert payload["data_quality"]["excluded_research_count"] == 11
    assert payload["data_quality"]["excluded_legacy_count"] == 4
    assert "RESEARCH_BAR_POLICY" in payload["source_policy"]["excluded_sources"]


def test_episode_743_multi_tf_retained(tmp_path: Path):
    books = tmp_path / "books"
    for tf, suffix in (("M15", "m15"), ("M30", "m30"), ("H1", "h1")):
        chain = _closed_chain(tf=tf, suffix=suffix, episode=f"{tf}:743", entry=100.0, exit_=110.0)
        _write_book(books / tf, **chain)
    # empty H4
    _write_book(
        books / "H4",
        signals=[{"signal_id": "s", "command_id": "c", "context_episode_id": "H4:0", "side": "LONG", "signal_status": "X"}],
        orders=[{"paper_order_id": "o", "command_id": "c", "side": "BUY", "status": "NEW", "timeframe": "H4"}],
        fills=[
            {
                "paper_trade_id": "f",
                "paper_order_id": "o",
                "position_id": "p",
                "timestamp": "2026-07-21T00:00:00Z",
                "side": "BUY",
                "quantity": 0.0,
                "price": 0.0,
                "fee": 0.0,
                "slippage": 0.0,
                "command_id": "c",
            }
        ],
        positions=[
            {
                "position_id": "p",
                "status": "FLAT",
                "direction": "LONG",
                "quantity": 0.0,
                "entry_price": 0.0,
                "command_id": "c",
                "paper_only": True,
                "execution_enabled": False,
            }
        ],
        trades=None,
    )
    payload = build_trading_performance_truth(
        books_root=books,
        portfolio_summary_path=tmp_path / "none.json",
        mark_price=100.0,
    )
    rows_743 = [r for r in payload["closed_trades"] if r.get("episode_id") == 743]
    assert len(rows_743) == 3
    assert len({r["trade_id"] for r in rows_743}) == 3
    assert len({r["position_id"] for r in rows_743}) == 3
    assert payload["data_quality"]["duplicate_count"] == 0


def test_same_trade_id_duplicate_in_tf_rejected(tmp_path: Path):
    books = tmp_path / "books"
    chain = _closed_chain(tf="M15", suffix="dup", episode="M15:1", entry=100.0, exit_=110.0)
    # duplicate same trade_id twice in trades parquet
    chain["trades"].append(dict(chain["trades"][0]))
    _write_book(books / "M15", **chain)
    for tf in ("M30", "H1", "H4"):
        empty = _closed_chain(tf=tf, suffix=f"e{tf}", episode=f"{tf}:9", entry=100.0, exit_=100.5)
        empty["trades"] = []
        empty["positions"][0]["status"] = "FLAT"
        _write_book(books / tf, **empty)
    payload = build_trading_performance_truth(
        books_root=books,
        portfolio_summary_path=tmp_path / "none.json",
        mark_price=100.0,
    )
    assert payload["portfolio"]["closed_trade_count"] == 1
    assert payload["data_quality"]["duplicate_count"] >= 1


def test_long_short_fees_slippage_and_unrealised(tmp_path: Path):
    books = tmp_path / "books"
    long_c = _closed_chain(tf="M15", suffix="long", episode="M15:1", side="LONG", entry=100.0, exit_=110.0, qty=2.0)
    short_c = _closed_chain(tf="M30", suffix="short", episode="M30:2", side="SHORT", entry=100.0, exit_=90.0, qty=2.0)
    _write_book(books / "M15", **long_c)
    _write_book(books / "M30", **short_c)
    # open long on H1
    cmd = "TF_CMD_open"
    open_payload = {
        "signals": [
            {
                "signal_id": "TF_SIGNAL_H1_open",
                "command_id": cmd,
                "context_episode_id": "H1:879",
                "side": "LONG",
                "signal_status": "ACCEPTED",
            }
        ],
        "orders": [
            {
                "paper_order_id": "TF_ORDER_H1_open",
                "command_id": cmd,
                "side": "BUY",
                "status": "FILLED",
                "timeframe": "H1",
            }
        ],
        "fills": [
            {
                "paper_trade_id": "TF_FILL_H1_open",
                "paper_order_id": "TF_ORDER_H1_open",
                "position_id": "TF_POSITION_H1_open",
                "timestamp": "2026-07-26T20:45:00Z",
                "side": "BUY",
                "quantity": 1.0,
                "price": 100.0,
                "fee": 0.02,
                "slippage": 0.03,
                "command_id": cmd,
            }
        ],
        "positions": [
            {
                "position_id": "TF_POSITION_H1_open",
                "status": "OPEN",
                "direction": "LONG",
                "quantity": 1.0,
                "entry_price": 100.0,
                "opened_at": "2026-07-26T20:45:00Z",
                "command_id": cmd,
                "paper_only": True,
                "execution_enabled": False,
            }
        ],
        "trades": None,
    }
    _write_book(books / "H1", **open_payload)
    # open short on H4
    cmd2 = "TF_CMD_open2"
    short_open = {
        "signals": [
            {
                "signal_id": "TF_SIGNAL_H4_open",
                "command_id": cmd2,
                "context_episode_id": "H4:881",
                "side": "SHORT",
                "signal_status": "ACCEPTED",
            }
        ],
        "orders": [
            {
                "paper_order_id": "TF_ORDER_H4_open",
                "command_id": cmd2,
                "side": "SELL",
                "status": "FILLED",
                "timeframe": "H4",
            }
        ],
        "fills": [
            {
                "paper_trade_id": "TF_FILL_H4_open",
                "paper_order_id": "TF_ORDER_H4_open",
                "position_id": "TF_POSITION_H4_open",
                "timestamp": "2026-07-27T00:15:00Z",
                "side": "SELL",
                "quantity": 1.0,
                "price": 100.0,
                "fee": 0.02,
                "slippage": 0.03,
                "command_id": cmd2,
            }
        ],
        "positions": [
            {
                "position_id": "TF_POSITION_H4_open",
                "status": "OPEN",
                "direction": "SHORT",
                "quantity": 1.0,
                "entry_price": 100.0,
                "opened_at": "2026-07-27T00:15:00Z",
                "command_id": cmd2,
                "paper_only": True,
                "execution_enabled": False,
            }
        ],
        "trades": None,
    }
    _write_book(books / "H4", **short_open)

    payload = build_trading_performance_truth(
        books_root=books,
        portfolio_summary_path=tmp_path / "none.json",
        mark_price=105.0,
        mark_timestamp="2026-07-27T12:00:00Z",
    )
    assert payload["portfolio"]["closed_trade_count"] == 2
    assert payload["portfolio"]["open_position_count"] == 2
    long_t = next(r for r in payload["closed_trades"] if r["side"] == "LONG")
    short_t = next(r for r in payload["closed_trades"] if r["side"] == "SHORT")
    assert long_t["gross_realised_pnl_usd"] == pytest.approx(20.0)
    assert short_t["gross_realised_pnl_usd"] == pytest.approx(20.0)
    assert long_t["entry_fee_usd"] == pytest.approx(entry_notional_fee(100.0, 2.0, ENTRY_FEE_BPS))
    assert long_t["exit_fee_usd"] == pytest.approx(entry_notional_fee(110.0, 2.0, EXIT_FEE_BPS))
    assert long_t["slippage_cost_usd"] > 0
    open_long = next(r for r in payload["open_positions"] if r["side"] == "LONG")
    open_short = next(r for r in payload["open_positions"] if r["side"] == "SHORT")
    assert open_long["gross_unrealised_pnl_usd"] == pytest.approx(5.0)
    assert open_short["gross_unrealised_pnl_usd"] == pytest.approx(-5.0)
    assert payload["portfolio"]["mtm_basis"] == MTM_BASIS_GROSS


def entry_notional_fee(price: float, qty: float, bps: float) -> float:
    return price * qty * (bps / 10_000.0)


def test_missing_mark_nulls_unrealised(tmp_path: Path):
    books = tmp_path / "books"
    chain = _closed_chain(tf="M15", suffix="only", episode="M15:1")
    # convert to open-only book
    chain["trades"] = None
    chain["positions"][0]["status"] = "OPEN"
    chain["positions"][0]["exit_price"] = None
    chain["fills"] = [chain["fills"][0]]
    _write_book(books / "M15", **chain)
    for tf in ("M30", "H1", "H4"):
        empty = _closed_chain(tf=tf, suffix=tf, episode=f"{tf}:0")
        empty["trades"] = None
        empty["positions"][0]["status"] = "FLAT"
        _write_book(books / tf, **empty)
    payload = build_trading_performance_truth(
        books_root=books,
        portfolio_summary_path=tmp_path / "none.json",
        mark_price=None,
    )
    assert payload["portfolio"]["mark_status"] == "MARK_UNAVAILABLE"
    assert payload["portfolio"]["unrealised_gross_pnl_usd"] is None
    assert payload["open_positions"][0]["gross_unrealised_pnl_usd"] is None
    assert payload["open_positions"][0]["unrealised_status"] == "MARK_UNAVAILABLE"


def test_metrics_statuses_and_no_nan_infinity(tmp_path: Path):
    books = tmp_path / "books"
    # n=0
    for tf in ("M15", "M30", "H1", "H4"):
        empty = _closed_chain(tf=tf, suffix=tf, episode=f"{tf}:0")
        empty["trades"] = None
        empty["positions"][0]["status"] = "FLAT"
        _write_book(books / tf, **empty)
    empty_payload = build_trading_performance_truth(
        books_root=books,
        portfolio_summary_path=tmp_path / "none.json",
        mark_price=100.0,
    )
    assert empty_payload["descriptive_metrics"]["status"] == "NO_CLOSED_TRADES"
    assert empty_payload["risk_adjusted_metrics"]["sharpe"]["value"] is None
    assert empty_payload["risk_adjusted_metrics"]["calmar"]["value"] is None

    # n=6 all wins → profit factor must not be Infinity
    books2 = tmp_path / "books2"
    for i, tf in enumerate(("M15", "M30", "H1")):
        for j in range(2):
            chain = _closed_chain(
                tf=tf,
                suffix=f"{tf}{j}",
                episode=f"{tf}:{700+j}",
                entry=100.0,
                exit_=110.0,
            )
            existing = books2 / tf
            if existing.exists() and (existing / "trades.parquet").exists():
                # merge
                prev = {
                    "signals": pd.read_parquet(existing / "signals.parquet").to_dict("records"),
                    "orders": pd.read_parquet(existing / "orders.parquet").to_dict("records"),
                    "fills": pd.read_parquet(existing / "fills.parquet").to_dict("records"),
                    "positions": pd.read_parquet(existing / "positions.parquet").to_dict("records"),
                    "trades": pd.read_parquet(existing / "trades.parquet").to_dict("records"),
                }
                for k in chain:
                    if chain[k] is None:
                        continue
                    prev[k].extend(chain[k])
                _write_book(existing, **prev)
            else:
                _write_book(books2 / tf, **chain)
    empty = _closed_chain(tf="H4", suffix="h4", episode="H4:0")
    empty["trades"] = None
    empty["positions"][0]["status"] = "FLAT"
    _write_book(books2 / "H4", **empty)

    payload = build_trading_performance_truth(
        books_root=books2,
        portfolio_summary_path=tmp_path / "none.json",
        mark_price=100.0,
    )
    assert payload["portfolio"]["closed_trade_count"] == 6
    assert payload["descriptive_metrics"]["status"] == "PRELIMINARY"
    assert payload["descriptive_metrics"]["profit_factor"]["status"] == "PRELIMINARY"
    assert payload["descriptive_metrics"]["profit_factor"]["value"] is None  # no losses → not infinity
    assert payload["risk_adjusted_metrics"]["sharpe"]["value"] is None
    assert payload["risk_adjusted_metrics"]["sharpe"]["status"] == "INSUFFICIENT_SAMPLE"
    assert payload["risk_adjusted_metrics"]["calmar"]["status"] == "INSUFFICIENT_HISTORY"
    assert payload["risk_adjusted_metrics"]["annualised_return"]["status"] == "INSUFFICIENT_HISTORY"
    assert payload["risk_adjusted_metrics"]["decision_grade"] is False

    out = tmp_path / "out"
    written = write_candidate_artifacts(payload, out_dir=out)
    text = Path(written["trading_performance_truth.json"]).read_text(encoding="utf-8")
    assert "NaN" not in text
    assert "Infinity" not in text
    assert "null" in text


def test_live_parity_with_books_and_manager():
    payload = build_trading_performance_truth()
    # closed/open from live books
    closed = 0
    opens = 0
    realised = 0.0
    for tf in ("M15", "M30", "H1", "H4"):
        trades = Path(PRODUCTION_BOOKS_ROOT / tf / "trades.parquet")
        positions = Path(PRODUCTION_BOOKS_ROOT / tf / "positions.parquet")
        if trades.exists():
            closed += len(pd.read_parquet(trades))
        if positions.exists():
            pos = pd.read_parquet(positions)
            opens += int((pos["status"].astype(str).str.upper() == "OPEN").sum())
            if trades.exists():
                tr = pd.read_parquet(trades)
                if len(tr) and "net_pnl_usd" in tr.columns:
                    realised += float(pd.to_numeric(tr["net_pnl_usd"], errors="coerce").fillna(0).sum())
    assert payload["portfolio"]["closed_trade_count"] == closed
    assert payload["portfolio"]["open_position_count"] == opens
    assert payload["portfolio"]["realised_net_pnl_usd"] == pytest.approx(realised)
    # manager unrealised parity on gross
    mgr = json.loads((ROOT / "data/trading/manager/portfolio_summary.json").read_text())
    assert payload["portfolio"]["unrealised_gross_pnl_usd"] == pytest.approx(float(mgr["unrealized_pnl"]))
    assert payload["portfolio"]["mark_price"] == pytest.approx(float(mgr["mark_price"]))
    assert payload["portfolio"]["mtm_basis"] == MTM_BASIS_GROSS
    assert payload["portfolio"]["initial_equity_usd"] == INITIAL_CAPITAL_USD
    # episode 743 multi-tf retained if present
    rows = [r for r in payload["closed_trades"] if r.get("episode_id") == 743]
    if rows:
        assert len(rows) >= 2
        assert len({r["trade_id"] for r in rows}) == len(rows)


def test_adapter_does_not_write_books(tmp_path: Path):
    books = tmp_path / "books"
    chain = _closed_chain(tf="M15", suffix="rw", episode="M15:1")
    _write_book(books / "M15", **chain)
    for tf in ("M30", "H1", "H4"):
        empty = _closed_chain(tf=tf, suffix=tf, episode=f"{tf}:0")
        empty["trades"] = None
        empty["positions"][0]["status"] = "FLAT"
        _write_book(books / tf, **empty)
    before = {}
    for path in books.rglob("*.parquet"):
        before[str(path)] = path.stat().st_mtime_ns
    _ = build_trading_performance_truth(
        books_root=books,
        portfolio_summary_path=tmp_path / "none.json",
        mark_price=100.0,
    )
    for path, mtime in before.items():
        assert Path(path).stat().st_mtime_ns == mtime


def test_portfolio_equals_tf_sum_live():
    payload = build_trading_performance_truth()
    tf_realised = sum(float(v["realised_net_pnl_usd"] or 0) for v in payload["timeframes"].values())
    tf_unreal = sum(float(v["unrealised_gross_pnl_usd"] or 0) for v in payload["timeframes"].values())
    assert tf_realised == pytest.approx(float(payload["portfolio"]["realised_net_pnl_usd"]))
    assert tf_unreal == pytest.approx(float(payload["portfolio"]["unrealised_gross_pnl_usd"] or 0))
