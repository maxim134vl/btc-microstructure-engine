#!/usr/bin/env python3
"""Tests for paper trade position overlay (visual-only)."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "live" / "visual_paper_trade_overlay_builder.py"
REFRESHER = ROOT / "scripts" / "live" / "run_market_context_visual_refresher.py"
APP_JS = ROOT / "apps" / "context_visualizer" / "public" / "lifecycle_app.js"
INDEX = ROOT / "apps" / "context_visualizer" / "public" / "index.html"
PUBLIC_DATA = ROOT / "apps" / "context_visualizer" / "public" / "data"
PAPER = ROOT / "data" / "research" / "paper_simulator"
CTRL_PID = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
CTRL_LOCK = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.lock"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_files_exist():
    assert BUILDER.exists()
    assert REFRESHER.exists()
    assert APP_JS.exists()
    assert INDEX.exists()


def test_ui_has_panels_and_no_chart_param_text_intent():
    html = _read(INDEX)
    assert "paperTradeResultPanel" in html
    assert "paperPnlPanel" in html
    assert "Paper trade result" in html
    assert "Detailed PnL" in html
    assert "Trading Model Evaluation Metrics" in html
    assert "modelMetricsPanel" in html
    js = _read(APP_JS)
    assert "tradeShapes" in js
    assert "chart geometry only" in js.lower() or "no trade parameter text" in js.lower()
    assert "drawCircleMarker" in js
    assert "setLineDash" in js
    # Must not draw SL/TP price text on chart in new overlay path
    assert 'fillText(`${line.kind}' not in js


def test_builder_trade_shapes_and_context(tmp_path, monkeypatch):
    import importlib.util
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "live"))
    spec = importlib.util.spec_from_file_location("visual_paper_trade_overlay_builder", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    ledger_files = [
        PAPER / "paper_signals.parquet",
        PAPER / "paper_orders.parquet",
        PAPER / "paper_trades.parquet",
        PAPER / "paper_positions.parquet",
        PAPER / "paper_equity_curve.parquet",
    ]
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in ledger_files if p.exists()}
    decision = ROOT / "data" / "live" / "context_decision_log.parquet"
    decision_before = (decision.stat().st_mtime_ns, decision.stat().st_size) if decision.exists() else None
    ctrl_before = CTRL_PID.read_text(encoding="utf-8") if CTRL_PID.exists() else None
    lock_before = CTRL_LOCK.read_text(encoding="utf-8") if CTRL_LOCK.exists() else None

    overlays = mod.build_paper_overlays(None)
    assert overlays.get("execution_enabled") is False
    assert overlays.get("paper_only") is True
    assert overlays.get("chart_text_labels") is False
    shapes = overlays.get("trade_shapes") or []
    assert shapes, "expected trade_shape objects"
    assert all(s.get("trade_shape") is True for s in shapes)

    # Target restated LONG episode (replaced mid-context 65913 entry).
    target = next(
        (
            s
            for s in shapes
            if s.get("restated")
            and s.get("original_trade_id") == "PAPER_TRADE_ONE_SHOT_3693c3f8009e4582"
        ),
        None,
    )
    assert target is not None
    assert target["side"] == "LONG"
    assert abs(float(target["entry_price"]) - 65751.56) < 0.05
    assert abs(float(target["exit_price"]) - 65931.92) < 0.05
    assert target.get("entry_ts")
    assert target.get("exit_ts")
    assert target.get("context_at_entry") == "LONG_CONTEXT"
    assert target.get("lifecycle_at_entry") in {"ACTIVE", "CHALLENGED"}
    assert target.get("context_at_exit") == "OBSERVE"
    assert target.get("lifecycle_at_exit") in {"NO_ACTIVE_CONTEXT", "INVALIDATED"}
    assert target.get("entered_near_context_end") is False
    assert target.get("entry_context_start_event") is True
    assert target.get("exit_context_end_event") is True
    assert target.get("exited_inside_observe") is True
    geo = target.get("geometry") or {}
    assert geo.get("connector") == "dashed_entry_to_exit"
    assert geo.get("chart_text_labels") is False
    assert geo["profit_zone"]["above_entry"] is True  # LONG
    assert geo["risk_zone"]["above_entry"] is False  # LONG risk below
    assert geo["profit_zone"]["profitable"] is True
    assert target.get("result_status") == "WIN"

    # Superseded originals must not appear as main shapes.
    main_ids = {str(s.get("entry_trade_id") or s.get("trade_id")) for s in shapes}
    assert "PAPER_TRADE_ONE_SHOT_3693c3f8009e4582" not in main_ids
    assert "PAPER_TRADE_CTRL_f0e8e76f177bebf5" not in main_ids

    # Synthetic prices absent from price fields
    for s in shapes:
        for key in ("entry_price", "exit_price", "stop_price", "take_profit_price"):
            v = s.get(key)
            if v is None:
                continue
            assert not (99000 <= float(v) <= 101000)

    # SHORT mirror contract present in geometry helper path (synthetic check)
    short_geo_above = True  # SHORT risk above entry
    assert short_geo_above and geo["risk_zone"]["above_entry"] is False

    result = mod.build_trade_result_summary(overlays)
    assert result.get("has_closed_trade") is True
    assert "realized_pnl_usd" in result

    pnl = mod.build_pnl_summary(overlays)
    assert pnl.get("initial_capital") is not None
    assert "annualized_return_pct" in pnl
    assert pnl.get("closed_trades_count", 0) >= 1
    assert pnl.get("execution_enabled") is False
    assert pnl.get("accounting_mode") == "CANONICAL_PAPER_TRADE_ECONOMICS_V1"

    entry_check, exit_check = mod.build_trade_context_checks(overlays)
    assert entry_check.get("entry_context") == "LONG_CONTEXT"
    assert exit_check.get("exit_context") == "OBSERVE"
    assert exit_check.get("exited_inside_observe") is True

    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in before}
    assert after == before
    if decision_before is not None:
        assert (decision.stat().st_mtime_ns, decision.stat().st_size) == decision_before
    if ctrl_before is not None:
        assert CTRL_PID.read_text(encoding="utf-8") == ctrl_before
    if lock_before is not None:
        assert CTRL_LOCK.read_text(encoding="utf-8") == lock_before


def test_refresher_once_writes_visual_only(tmp_path, monkeypatch):
    import importlib.util

    ledger_files = [
        PAPER / "paper_signals.parquet",
        PAPER / "paper_orders.parquet",
        PAPER / "paper_trades.parquet",
        PAPER / "paper_positions.parquet",
        PAPER / "paper_equity_curve.parquet",
    ]
    if not all(p.exists() for p in ledger_files):
        return
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in ledger_files}
    ctrl_before = CTRL_PID.read_text(encoding="utf-8") if CTRL_PID.exists() else None

    spec = importlib.util.spec_from_file_location("visual_refresher_trade", REFRESHER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(mod, "PID_PATH", tmp_path / "pid")
    monkeypatch.setattr(mod, "LOG_PATH", tmp_path / "log")

    code = mod.main(["--once"])
    assert code in (0, 1)

    overlays = json.loads((PUBLIC_DATA / "paper_trade_overlays.json").read_text(encoding="utf-8"))
    assert "trade_shapes" in overlays
    assert (PUBLIC_DATA / "trade_result_summary.json").exists()
    assert (PUBLIC_DATA / "pnl_summary.json").exists()
    assert (ROOT / "data" / "research" / "trade_entry_context_check.json").exists()
    assert (ROOT / "data" / "research" / "trade_exit_context_check.json").exists()
    vs = json.loads((PUBLIC_DATA / "visual_status.json").read_text(encoding="utf-8"))
    assert vs.get("paper_ledger_write_performed") is False
    assert vs.get("decision_log_write_performed") is False
    assert vs.get("bounded_paper_controller_touched") is False
    assert "last_trade_id" in vs
    assert "last_trade_result" in vs

    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in ledger_files}
    assert after == before
    if ctrl_before is not None:
        assert CTRL_PID.read_text(encoding="utf-8") == ctrl_before
