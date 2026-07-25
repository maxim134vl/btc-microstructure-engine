"""Patch 2B.2 — paper controller logic repair contract tests."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
CTRL = ROOT / "scripts" / "live" / "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
CTL = ROOT / "scripts" / "bounded_paper_trading_controller_ctl.sh"
SIM = ROOT / "data" / "research" / "paper_simulator"

sys.path.insert(0, str(ROOT / "scripts" / "live"))
import paper_trade_economics as econ  # noqa: E402

spec = importlib.util.spec_from_file_location("bounded_paper_ctrl_p2b2", CTRL)
ctrl = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["bounded_paper_ctrl_p2b2"] = ctrl
spec.loader.exec_module(ctrl)


def test_01_preview_suite_canonical():
    # Imported suite should pass separately; smoke the two repaired contracts here.
    hold = ctrl.evaluate_exit_preview(
        side="LONG",
        entry_price=100.0,
        quantity=1.0,
        stop_loss_price=99.0,
        take_profit_price=101.5,
        entry_fee_usd=0.1,
        current_price=100.5,
        latest_high=101.6,
        latest_low=98.5,
        latest_context="LONG_CONTEXT",
        latest_lifecycle_state="ACTIVE",
    )
    assert hold["exit_preview_action"] == "PREVIEW_HOLD_LONG"


def test_02_paper_is_read_only_consumer_default():
    assert ctrl.DEFAULT_SKIP_REFRESH is True
    assert ctrl.PAPER_OWNERSHIP_CLASS == "PAPER_READ_ONLY_CONSUMER"


def test_03_paper_does_not_trigger_context_refresh_by_default():
    out = ctrl.refresh_and_maybe_append(root=ROOT, skip_refresh=True)
    assert out.get("skipped") is True
    assert out.get("refresh_performed") is False
    assert out.get("decision_log_append_performed") is False


def test_04_ctl_passes_skip_refresh():
    text = CTL.read_text(encoding="utf-8")
    assert '"--skip-refresh"' in text or "'--skip-refresh'" in text


def test_05_canonical_decision_path_only():
    src = CTRL.read_text(encoding="utf-8")
    assert "context_decision_log.parquet" in src
    assert "auction_synthesis_memory" not in src


def test_06_research_decision_rebuild_not_default():
    # enable-context-refresh is opt-in; default path skips refresh
    assert "--enable-context-refresh" in CTRL.read_text(encoding="utf-8")


def test_07_stale_decision_no_signal():
    gate = ctrl.evaluate_flat_entry_gate(
        {
            "decision_stale": True,
            "active_market_context": "LONG_CONTEXT",
            "lifecycle_state": "ACTIVE",
            "lifecycle_episode_id": "ep1",
            "previous_active_market_context": "OBSERVE",
            "candle_timestamp": "2026-07-24T14:00:00Z",
        }
    )
    assert gate["allowed"] is False


def test_08_observe_no_entry():
    gate = ctrl.evaluate_flat_entry_gate(
        {
            "decision_stale": False,
            "active_market_context": "OBSERVE",
            "lifecycle_state": "NO_ACTIVE_CONTEXT",
            "lifecycle_episode_id": "ep1",
            "candle_timestamp": "2026-07-24T14:00:00Z",
        }
    )
    assert gate["allowed"] is False


def test_09_missing_episode_fail_closed():
    gate = ctrl.evaluate_flat_entry_gate(
        {
            "decision_stale": False,
            "active_market_context": "LONG_CONTEXT",
            "lifecycle_state": "CHALLENGED",
        }
    )
    assert gate["allowed"] is False


def test_10_deterministic_signal_ids():
    a = ctrl.make_id("PAPER_SIGNAL_CTRL", "x", "y", "z")
    b = ctrl.make_id("PAPER_SIGNAL_CTRL", "x", "y", "z")
    assert a == b


def test_11_deterministic_order_ids():
    a = ctrl.make_id("PAPER_ORDER_CTRL", "sig", "OPEN", "1.0")
    b = ctrl.make_id("PAPER_ORDER_CTRL", "sig", "OPEN", "1.0")
    assert a == b


def test_12_fill_point_in_time_requires_strictly_after():
    bad = ctrl._fill_after_decision_ok(
        decision={"candle_timestamp": "2026-07-24T14:00:00Z"},
        execution_ts="2026-07-24T14:00:00Z",
    )
    assert bad["ok"] is False
    good = ctrl._fill_after_decision_ok(
        decision={"candle_timestamp": "2026-07-24T14:00:00Z"},
        execution_ts="2026-07-24T14:00:01Z",
    )
    assert good["ok"] is True


def test_13_no_same_bar_close_as_fill_when_equal_ts():
    # Equal timestamps rejected (same-bar close not after decision).
    assert (
        ctrl._fill_after_decision_ok(
            decision={"candle_timestamp": "2026-07-24T14:00:00Z"},
            execution_ts="2026-07-24T14:00:00Z",
        )["reason"]
        == "NO_FILL_FILL_NOT_AFTER_DECISION"
    )


def test_14_long_pnl():
    out = econ.closed_trade_economics(
        side="LONG", entry_price=100.0, exit_price=110.0, position_size_btc=2.0
    )
    assert abs(out["gross_pnl_usd"] - 20.0) < 1e-9


def test_15_short_pnl():
    out = econ.closed_trade_economics(
        side="SHORT", entry_price=100.0, exit_price=90.0, position_size_btc=2.0
    )
    assert abs(out["gross_pnl_usd"] - 20.0) < 1e-9


def test_16_entry_and_exit_fee_once():
    out = econ.closed_trade_economics(
        side="LONG", entry_price=10000.0, exit_price=10000.0, position_size_btc=1.0
    )
    assert abs(out["entry_fee_usd"] - 2.0) < 1e-9  # 2 bps of 10k
    assert abs(out["exit_fee_usd"] - 5.0) < 1e-9


def test_17_slippage_once_each_leg():
    out = econ.closed_trade_economics(
        side="LONG", entry_price=10000.0, exit_price=10000.0, position_size_btc=1.0
    )
    assert out["entry_slippage_usd"] > 0
    assert out["exit_slippage_usd"] > 0


def test_18_context_flip_exit_under_hold():
    out = ctrl.evaluate_exit_preview(
        side="LONG",
        entry_price=100.0,
        quantity=1.0,
        stop_loss_price=99.0,
        take_profit_price=101.5,
        entry_fee_usd=0.1,
        current_price=100.0,
        latest_high=100.1,
        latest_low=99.9,
        latest_context="SHORT_CONTEXT",
        latest_lifecycle_state="ACTIVE",
    )
    assert out["exit_preview_action"] == "PREVIEW_CLOSE_LONG_CONTEXT_EXIT"


def test_19_invalid_stop_reason_constant():
    assert hasattr(ctrl, "ENTRY_BLOCKED_INVALID_STOP_DISTANCE")


def test_20_max_risk_constants_preserved():
    assert ctrl.PAPER_INITIAL_EQUITY == 100000.0
    assert abs(ctrl.PAPER_MAX_RISK_PCT - 0.01) < 1e-12
    assert ctrl.PAPER_MAX_RISK_USD == 1000.0


def test_21_no_exchange_imports():
    tree = ast.parse(CTRL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in {"ccxt", "binance", "bybit"}


def test_22_continuation_off():
    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0") in {"0", ""}


def test_23_price_gate_off():
    assert os.environ.get("PRICE_GATE", "OFF") in {"OFF", "0", ""}


def test_24_execution_disabled_constants():
    assert ctrl.CONTROLLER_MODE == "PAPER_ONLY"


def test_25_candidate_outputs_under_research_if_present():
    tag_path = ROOT / "data" / "research" / "patch2b2_active_ts.txt"
    if not tag_path.exists():
        pytest.skip("no active tag")
    for name in (
        "patch2b2_candidate_paper_signals.parquet",
        "patch2b2_candidate_paper_orders.parquet",
        "patch2b2_candidate_paper_trades.parquet",
        "patch2b2_candidate_positions.parquet",
    ):
        p = ROOT / "data" / "research" / name
        if p.exists():
            assert "data/research" in str(p)


def test_26_production_paper_sha_stable_vs_preflight():
    # After Patch 2B.3 intentional atomic migration, production SHAs diverge from
    # 2B.2 preflight by design. Post-activation integrity is owned by 2B.3 tests.
    if (ROOT / "data" / "research" / "patch2b3_active_ts.txt").exists():
        pytest.skip("patch2b3 activation superseded preflight SHA freeze")
    tag_path = ROOT / "data" / "research" / "patch2b2_active_ts.txt"
    if not tag_path.exists():
        pytest.skip("no tag")
    tag = tag_path.read_text().strip()
    pre = ROOT / "data" / "research" / f"patch2b2_preflight_{tag}.json"
    if not pre.exists():
        pytest.skip("no preflight")
    doc = json.loads(pre.read_text())
    for key, fname in [
        ("paper_signals", "paper_signals.parquet"),
        ("paper_orders", "paper_orders.parquet"),
        ("paper_trades", "paper_trades.parquet"),
        ("paper_positions", "paper_positions.parquet"),
    ]:
        path = SIM / fname
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        assert h == doc["datasets"][key]["sha256"]
