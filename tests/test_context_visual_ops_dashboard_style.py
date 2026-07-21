#!/usr/bin/env python3
"""Tests for context visual ops-dashboard style polish (visual-only)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps" / "context_visualizer" / "public"
CSS = PUBLIC / "lifecycle.css"
HTML = PUBLIC / "index.html"
JS = PUBLIC / "lifecycle_app.js"
PUBLIC_DATA = PUBLIC / "data"
PAPER = ROOT / "data" / "research" / "paper_simulator"
DECISION = ROOT / "data" / "live" / "context_decision_log.parquet"
CTRL_PID = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
CTRL_LOCK = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.lock"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_theme_variables_and_modes_exist():
    css = _read(CSS)
    assert "--font-sans" in css
    assert "--font-mono" in css
    assert "--bg-primary" in css
    assert "--panel-bg" in css
    assert "--accent-positive" in css
    assert "--accent-negative" in css
    assert "--radius-md" in css
    assert 'html[data-theme="dark"]' in css
    assert 'html[data-theme="light"]' in css


def test_light_theme_tones_are_softened():
    css = _read(CSS)
    light = css.split('html[data-theme="light"]', 1)[1].split("/* Compat aliases", 1)[0]
    # Soft / muted greens & reds — not neon Apple green/red
    assert "#2f7a4a" in light or "47, 122, 74" in light
    assert "#c24b42" in light or "194, 75, 66" in light
    assert "#34c759" not in light
    assert "#ff3b30" not in light
    # Lower fill opacities for zones
    assert "0.065" in light or "0.07" in light
    assert "0.055" in light or "0.038" in light
    # Dark theme still carries bright operational hues
    root_dark = css.split('html[data-theme="light"]', 1)[0]
    assert "#30d158" in root_dark
    assert "#ff453a" in root_dark


def test_theme_toggle_and_persistence():
    html = _read(HTML)
    js = _read(JS)
    assert 'id="themeSelect"' in html
    assert "System" in html and "Dark" in html and "Light" in html
    assert "btcml-context-visual-theme" in html
    assert "btcml-context-visual-theme" in js
    assert "localStorage" in js
    assert "prefers-color-scheme" in js
    assert "applyThemeMode" in js
    assert "initThemeControls" in js


def test_panels_and_overlay_load_preserved():
    html = _read(HTML)
    js = _read(JS)
    assert "paperTradeResultPanel" in html
    assert "paperPnlPanel" in html
    assert "Paper trade result" in html
    assert "Paper PnL" in html
    assert "Controller actions" in html
    assert "paper_trade_overlays.json" in js
    assert "trade_result_summary.json" in js
    assert "pnl_summary.json" in js
    assert "cacheBust" in js
    assert 'cache: "no-store"' in js
    assert "tradeShapes" in js
    assert "chart geometry only" in js.lower() or "no trade parameter text" in js.lower()


def test_no_forbidden_writes_and_no_synthetic_trade_price(tmp_path=None):
    paper_files = [
        PAPER / "paper_signals.parquet",
        PAPER / "paper_orders.parquet",
        PAPER / "paper_trades.parquet",
        PAPER / "paper_positions.parquet",
        PAPER / "paper_equity_curve.parquet",
    ]
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in paper_files if p.exists()}
    decision_before = (DECISION.stat().st_mtime_ns, DECISION.stat().st_size) if DECISION.exists() else None
    ctrl_before = CTRL_PID.read_text(encoding="utf-8") if CTRL_PID.exists() else None
    lock_before = CTRL_LOCK.read_text(encoding="utf-8") if CTRL_LOCK.exists() else None

    # Style polish must not require ledger mutation; re-read overlays only.
    overlays_path = PUBLIC_DATA / "paper_trade_overlays.json"
    assert overlays_path.exists()
    overlays = json.loads(overlays_path.read_text(encoding="utf-8"))
    shapes = overlays.get("trade_shapes") or []
    assert shapes, "trade overlay shapes must remain present"
    for shape in shapes:
        for key in ("entry_price", "exit_price", "stop_price", "take_profit_price"):
            val = shape.get(key)
            if val is None:
                continue
            num = float(val)
            assert not (99000 <= num <= 101000), f"synthetic-looking price in {key}: {num}"

    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in paper_files if p.exists()}
    assert before == after
    if decision_before is not None:
        assert (DECISION.stat().st_mtime_ns, DECISION.stat().st_size) == decision_before
    if ctrl_before is not None:
        assert CTRL_PID.read_text(encoding="utf-8") == ctrl_before
    if lock_before is not None:
        assert CTRL_LOCK.read_text(encoding="utf-8") == lock_before


def test_ops_style_inventory_exists():
    inv = ROOT / "data" / "research" / "visual_ops_style_inventory.json"
    assert inv.exists()
    payload = json.loads(inv.read_text(encoding="utf-8"))
    assert payload.get("discovered_ops_dashboard_files")
    assert "SF Pro Text" in payload.get("font_family", "")
