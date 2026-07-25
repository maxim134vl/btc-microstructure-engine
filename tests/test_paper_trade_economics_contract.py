#!/usr/bin/env python3
"""Canonical paper trade economics contract tests."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "scripts" / "live"
CTRL = LIVE / "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"

sys.path.insert(0, str(LIVE))

from paper_trade_economics import (  # noqa: E402
    ENTRY_FEE_BPS,
    EXIT_FEE_BPS,
    INITIAL_CAPITAL_USD,
    MAX_RISK_USD,
    NORMAL_ENTRY_SLIPPAGE_BPS,
    NORMAL_EXIT_SLIPPAGE_BPS,
    STOP_FORCED_EXIT_SLIPPAGE_BPS,
    closed_trade_economics,
    resolve_risk_sizing,
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_cost_aware_stop_sizing_targets_minus_one_r_after_fees_and_slippage():
    sizing = resolve_risk_sizing(
        side="LONG",
        entry_price=65000.0,
        stop_loss_price=64350.0,
        take_profit_price=65975.0,
    )

    assert sizing.allowed is True
    expected_per_btc = (
        650.0
        + 65000.0 * (ENTRY_FEE_BPS / 10000.0)
        + 64350.0 * (EXIT_FEE_BPS / 10000.0)
        + 65000.0 * (NORMAL_ENTRY_SLIPPAGE_BPS / 10000.0)
        + 64350.0 * (STOP_FORCED_EXIT_SLIPPAGE_BPS / 10000.0)
    )
    assert math.isclose(sizing.position_size_btc, MAX_RISK_USD / expected_per_btc, rel_tol=1e-12)

    stop_economics = closed_trade_economics(
        side="LONG",
        entry_price=65000.0,
        exit_price=64350.0,
        position_size_btc=sizing.position_size_btc,
        stop_loss_price=64350.0,
        take_profit_price=65975.0,
        exit_reason="STOP_LOSS_HIT",
        exit_execution_source="stop_loss_event",
    )
    assert math.isclose(stop_economics["net_pnl_after_fees_slippage"], -MAX_RISK_USD, rel_tol=1e-12, abs_tol=1e-6)
    assert math.isclose(stop_economics["R"], -1.0, rel_tol=1e-12, abs_tol=1e-9)


def test_closed_trade_net_equals_gross_minus_fees_minus_slippage_and_normal_slippage_is_3_bps_each_side():
    sizing = resolve_risk_sizing(
        side="SHORT",
        entry_price=65000.0,
        stop_loss_price=65650.0,
        take_profit_price=64025.0,
    )
    econ = closed_trade_economics(
        side="SHORT",
        entry_price=65000.0,
        exit_price=64025.0,
        position_size_btc=sizing.position_size_btc,
        stop_loss_price=65650.0,
        take_profit_price=64025.0,
        exit_reason="CONTEXT_END",
        exit_execution_source="event_price",
    )

    assert econ["entry_slippage_bps"] == NORMAL_ENTRY_SLIPPAGE_BPS
    assert econ["exit_slippage_bps"] == NORMAL_EXIT_SLIPPAGE_BPS
    assert econ["slippage_bps"] == NORMAL_ENTRY_SLIPPAGE_BPS + NORMAL_EXIT_SLIPPAGE_BPS
    assert math.isclose(
        econ["net_pnl_after_fees_slippage"],
        econ["gross_pnl_before_fees_slippage"] - econ["fees_usd"] - econ["slippage_usd"],
        rel_tol=1e-12,
        abs_tol=1e-6,
    )


def test_stop_forced_and_candle_close_fallback_use_degraded_slippage_semantics():
    stop_econ = closed_trade_economics(
        side="LONG",
        entry_price=65000.0,
        exit_price=64350.0,
        position_size_btc=1.0,
        stop_loss_price=64350.0,
        exit_reason="FORCED_STOP_EXIT",
        exit_execution_source="stop_loss_event",
    )
    fallback_econ = closed_trade_economics(
        side="LONG",
        entry_price=65000.0,
        exit_price=65100.0,
        position_size_btc=1.0,
        stop_loss_price=64350.0,
        exit_reason="CONTEXT_END",
        exit_execution_source="candle_close_fallback",
        fallback_slippage_bps=2.0,
    )

    assert stop_econ["exit_slippage_bps"] == STOP_FORCED_EXIT_SLIPPAGE_BPS
    assert stop_econ["slippage_bps"] == NORMAL_ENTRY_SLIPPAGE_BPS + STOP_FORCED_EXIT_SLIPPAGE_BPS
    assert fallback_econ["exit_slippage_bps"] >= 5.0
    assert fallback_econ["execution_quality_status"] == "DEGRADED"


def test_paper_pnl_engine_uses_canonical_slippage_contract():
    pnl_engine = _load("paper_pnl_engine_economics_contract", LIVE / "paper_pnl_engine.py")
    math_row = pnl_engine.compute_trade_math(
        side="LONG",
        entry_price=65000.0,
        exit_price=65500.0,
        stop_loss_price=64350.0,
        take_profit_price=65975.0,
        exit_reason="CONTEXT_END",
        exit_execution_source="event_price",
    )

    assert math_row.entry_slippage > 0.0
    assert math_row.exit_slippage > 0.0
    assert math_row.slippage_bps == NORMAL_ENTRY_SLIPPAGE_BPS + NORMAL_EXIT_SLIPPAGE_BPS
    assert math.isclose(math_row.net_pnl, math_row.gross_pnl - math_row.fees - math_row.slippage, rel_tol=1e-12, abs_tol=1e-6)


def test_canonical_policy_metrics_recalculate_costs_from_same_contract():
    policy = _load("policy_context_canonical_bar_policy_lib_economics_contract", ROOT / "scripts" / "research" / "policy_context_canonical_bar_policy_lib.py")
    frame = pd.DataFrame(
        [
            {
                "trade_id": "T1",
                "included_in_primary_canonical_bar_policy_pnl": True,
                "side": "LONG",
                "entry_price": 65000.0,
                "exit_price": 65500.0,
                "position_size_btc": 1.0,
                "risk_amount_usd": 1000.0,
            }
        ]
    )

    out = policy._recalculate_cost_accounting(frame).iloc[0].to_dict()

    expected_fees = 65000.0 * (ENTRY_FEE_BPS / 10000.0) + 65500.0 * (EXIT_FEE_BPS / 10000.0)
    expected_slippage = 65000.0 * (NORMAL_ENTRY_SLIPPAGE_BPS / 10000.0) + 65500.0 * (NORMAL_EXIT_SLIPPAGE_BPS / 10000.0)
    assert math.isclose(out["fees_usd"], expected_fees, rel_tol=1e-12, abs_tol=1e-6)
    assert math.isclose(out["slippage_usd"], expected_slippage, rel_tol=1e-12, abs_tol=1e-6)
    assert math.isclose(out["net_pnl_after_fees_slippage"], 500.0 - expected_fees - expected_slippage, rel_tol=1e-12, abs_tol=1e-6)
    assert out["entry_execution_source"] == policy.ENTRY_PRICE_POLICY
    assert out["exit_execution_source"] == policy.EXIT_PRICE_POLICY


def test_live_controller_cash_accounting_does_not_double_count_entry_costs(tmp_path: Path):
    ctrl = _load("bounded_paper_controller_economics_contract", CTRL)
    decision = {
        "candle_timestamp": "2026-07-23T13:00:00Z",
        "latest_decision_log_ts": "2026-07-23T13:00:00Z",
        "active_market_context": "LONG_CONTEXT",
        "lifecycle_state": "CHALLENGED",
        "stop_loss_price": 64350.0,
        "take_profit_price": 65975.0,
    }
    written = ctrl.write_open_position_chain(
        research=tmp_path,
        decision=decision,
        side="LONG",
        entry_price=65000.0,
        entry_price_source="event_price",
        market_ts="2026-07-23T13:00:00Z",
        entry_execution_ts="2026-07-23T13:00:00Z",
    )
    assert written["fixed_notional_used"] is False
    assert not math.isclose(written["notional_usd"], ctrl.PAPER_NOTIONAL, rel_tol=0.0, abs_tol=1e-9)

    open_pos = ctrl.load_open_positions(tmp_path)[0]
    close = ctrl.write_close_position_chain(
        research=tmp_path,
        open_pos=open_pos,
        exit_preview={
            "suggested_exit_price": 65500.0,
            "exit_preview_reason": "CONTEXT_END",
            "exit_preview_action": "PREVIEW_CLOSE_LONG_CONTEXT_EXIT",
        },
        decision={
            "candle_timestamp": "2026-07-23T13:15:00Z",
            "latest_decision_log_ts": "2026-07-23T13:15:00Z",
            "active_market_context": "OBSERVE",
            "lifecycle_state": "NO_ACTIVE_CONTEXT",
        },
        market={"current_price": 65500.0},
        market_snapshot={"source": "event_price", "observed_at_utc": "2026-07-23T13:15:00Z"},
    )

    qty = written["quantity_btc"]
    expected = closed_trade_economics(
        side="LONG",
        entry_price=65000.0,
        exit_price=65500.0,
        position_size_btc=qty,
        stop_loss_price=64350.0,
        take_profit_price=65975.0,
        exit_reason="CONTEXT_END",
        exit_execution_source="event_price",
    )
    trades = pd.read_parquet(tmp_path / "paper_trades.parquet")
    positions = pd.read_parquet(tmp_path / "paper_positions.parquet")
    equity = pd.read_parquet(tmp_path / "paper_equity_curve.parquet")
    close_trade = trades.iloc[-1].to_dict()
    position = positions.iloc[-1].to_dict()

    assert close_trade["fee_bps"] == EXIT_FEE_BPS
    assert close_trade["slippage_bps"] == NORMAL_EXIT_SLIPPAGE_BPS
    assert math.isclose(close_trade["realized_pnl"], expected["net_pnl_after_fees_slippage"], rel_tol=1e-12, abs_tol=1e-6)
    assert math.isclose(position["fees_paid"], expected["fees_usd"], rel_tol=1e-12, abs_tol=1e-6)
    assert math.isclose(position["slippage_paid"], expected["slippage_usd"], rel_tol=1e-12, abs_tol=1e-6)
    assert math.isclose(equity.iloc[-1]["equity"], INITIAL_CAPITAL_USD + expected["net_pnl_after_fees_slippage"], rel_tol=1e-12, abs_tol=1e-6)
    assert math.isclose(close["pnl_usd"], expected["net_pnl_after_fees_slippage"], rel_tol=1e-12, abs_tol=1e-6)


def test_visual_overlay_shape_contains_required_economics_fields(monkeypatch):
    refresher = _load("run_market_context_visual_refresher_economics_contract", LIVE / "run_market_context_visual_refresher.py")
    monkeypatch.setattr(refresher, "_configured_paper_deposit_usd", lambda: INITIAL_CAPITAL_USD)
    normalized = refresher._render_closed_canonical_row(
        {
            "trade_id": "POLICY_CONTEXT_CANONICAL_BAR_TRADE_TEST",
            "context_id": 1,
            "entry_ts": "2026-07-23T13:00:00Z",
            "exit_ts": "2026-07-23T13:15:00Z",
            "side": "LONG",
            "entry_price": 65000.0,
            "exit_price": 65500.0,
            "stop_loss_price": 64350.0,
            "take_profit_price": 65975.0,
            "entry_execution_source": "event_price",
            "exit_execution_source": "event_price",
            "context_quality": "CHALLENGED",
            "paper_entry_basis": "ACTIVE_DIRECTIONAL_CONTEXT",
        }
    )
    shape = refresher._shape_from_normalized_trade(normalized)
    required = {
        "trade_id",
        "side",
        "entry_price",
        "exit_price",
        "stop_loss_price",
        "take_profit_price",
        "position_size_btc",
        "position_notional_usd",
        "risk_amount_usd",
        "stop_distance_usd",
        "entry_fee_usd",
        "exit_fee_usd",
        "fees_usd",
        "entry_slippage_usd",
        "exit_slippage_usd",
        "slippage_usd",
        "slippage_bps",
        "slippage_R",
        "gross_pnl_before_fees_slippage",
        "net_pnl_after_fees_slippage",
        "R",
        "entry_execution_source",
        "exit_execution_source",
        "execution_quality_status",
        "context_quality",
        "paper_entry_basis",
    }
    missing = sorted(k for k in required if shape.get(k) is None)
    assert missing == []


def test_public_pnl_summary_reconciles_to_normalized_overlay_rows():
    builder = _load("visual_paper_trade_overlay_builder_economics_contract", LIVE / "visual_paper_trade_overlay_builder.py")
    trade = {
        "trade_id": "T1",
        "entry_ts": "2026-07-23T13:00:00Z",
        "exit_ts": "2026-07-23T13:15:00Z",
        "gross_pnl_before_fees_slippage": 500.0,
        "fees_usd": 45.0,
        "slippage_usd": 39.0,
        "net_pnl_after_fees_slippage": 416.0,
        "R": 0.416,
    }
    pnl = builder.build_pnl_summary({"closed_trades": [trade], "open_positions": [], "renderer_source": "unit"})

    assert pnl["pnl_source"] == "paper_trade_overlays.closed_trades"
    assert pnl["fees_paid"] == 45.0
    assert pnl["slippage_paid"] == 39.0
    assert pnl["net_after_costs"] == 416.0
    assert pnl["gross_minus_fees_minus_slippage_equals_net"] is True
    assert pnl["detailed_pnl"]["current_equity_usd"] == INITIAL_CAPITAL_USD + 416.0
    assert pnl["model_evaluation_metrics"]["metrics_recomputed_from_net_pnl"] is True
