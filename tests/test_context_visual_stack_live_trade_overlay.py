#!/usr/bin/env python3
"""Tests for live context + paper trade visual stack (visual-only)."""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFRESHER = ROOT / "scripts" / "live" / "run_market_context_visual_refresher.py"
VIEWER = ROOT / "scripts" / "live" / "run_context_visual_viewer_server.py"
CTL = ROOT / "scripts" / "context_visual_stack_ctl.sh"
PUBLIC = ROOT / "apps" / "context_visualizer" / "public"
APP_JS = PUBLIC / "lifecycle_app.js"
INDEX = PUBLIC / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_scripts_exist():
    assert REFRESHER.exists()
    assert VIEWER.exists()
    assert CTL.exists()
    assert APP_JS.exists()
    assert INDEX.exists()


def test_refresher_is_visual_only_no_forbidden_writes():
    src = _read(REFRESHER)
    tree = ast.parse(src)
    # Must declare visual-only and forbid ledger/decision/live refresh.
    assert "visual-only" in src.lower() or "visual_only" in src
    assert "paper_ledger_write_performed" in src
    assert "decision_log_write_performed" in src
    assert "live_refresh_performed" in src
    assert "bounded_paper_controller_touched" in src
    # Must not invoke shadow-chain rebuild or decision log append helpers.
    assert "build_market_context_shadow_chain" not in src
    assert "append_context_decision" not in src
    assert "exchange" in src.lower()  # safety flags present
    # Forbidden write globs declared
    assert "paper_*.parquet" in src
    assert "context_decision_log.parquet" in src


def test_viewer_no_cache_headers_and_bind():
    src = _read(VIEWER)
    assert "no-store, no-cache, must-revalidate, max-age=0" in src
    assert "Pragma" in src
    assert "Expires" in src
    assert "127.0.0.1" in src
    assert "8765" in src
    assert "runtime_context_viewer.pid" in src


def test_refresher_lock_and_outputs():
    src = _read(REFRESHER)
    assert "runtime_context_visual_refresher.lock" in src
    assert "paper_trade_overlays.json" in src
    assert "restated_paper_trades.json" in src or "RESTATED_TRADES_OUT" in src
    assert "open_positions.json" in src
    assert "closed_trades.json" in src
    assert "controller_cycles.json" in src
    assert "visual_status.json" in src
    assert "DEGRADED_LAST_GOOD_DATA" in src
    assert "SOURCE_WAITING" in src
    assert "VISUAL_DATA_STALE" in src
    assert "source_lag_minutes" in src
    assert "visual_refresh_age_seconds" in src
    assert "100000" in src  # synthetic filter


def test_ui_cache_bust_and_overlays():
    js = _read(APP_JS)
    assert "cacheBust" in js
    assert "Date.now()" in js
    assert "paper_trade_overlays.json" in js
    assert "visual_status.json" in js
    assert "SOURCE WAITING" in js
    assert "STALE" in js
    assert "is-stale" in js
    assert "inspector" in js.lower()
    html = _read(INDEX)
    assert "inspectorPanel" in html
    assert "controllerTimeline" in html


def test_ctl_does_not_touch_controller():
    src = _read(CTL)
    assert "bounded paper controller NOT touched" in src or "NOT touched" in src
    assert "run_market_context_visual_refresher.py" in src
    assert "run_context_visual_viewer_server.py" in src
    assert "8765" in src
    # Must not start/stop paper controller
    assert "bounded_paper_trading_controller_ctl" not in src


def test_ctl_macos_safe_no_setsid_and_nohup_pid_files():
    src = _read(CTL)
    code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    assert "setsid" not in code
    assert "nohup" in src
    assert "nohup_start" in src
    assert "runtime_context_viewer.pid" in src
    assert "runtime_context_visual_refresher.pid" in src
    assert "duplicate start blocked" in src
    assert "foreign" in src.lower()
    assert "viewer_alive=" in src
    assert "refresher_alive=" in src
    assert "port_8765_listening=" in src
    assert "visual_refresh_age_seconds" in src
    assert "dedupe_tail" in src
    assert "left untouched" in src or "Refusing to kill foreign" in src
    # Header comment documents removal; executable code must not invoke it.
    assert any("no setsid" in ln for ln in src.splitlines() if ln.lstrip().startswith("#"))


def test_viewer_log_avoids_duplicate_file_mirror_when_redirected():
    src = _read(VIEWER)
    assert "sys.stdout.isatty()" in src
    assert "avoids duplicate" in src.lower() or "When launched under" in src


def test_ctl_status_fields_contract():
    src = _read(CTL)
    for field in (
        "viewer_pid=",
        "viewer_alive=",
        "refresher_pid=",
        "refresher_alive=",
        "port_8765_listening=",
        "visual_status=",
        "visual_refresh_age_seconds=",
    ):
        assert field in src


def test_refresh_once_builds_overlays_without_ledger_mutation(tmp_path, monkeypatch):
    """Run refresher once against real repo data if present; assert visual outputs + ledger mtimes."""
    import importlib.util

    paper_dir = ROOT / "data" / "research" / "paper_simulator"
    ledger_files = [
        paper_dir / "paper_signals.parquet",
        paper_dir / "paper_orders.parquet",
        paper_dir / "paper_trades.parquet",
        paper_dir / "paper_positions.parquet",
        paper_dir / "paper_equity_curve.parquet",
    ]
    if not all(p.exists() for p in ledger_files):
        return  # skip soft if data absent

    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in ledger_files}
    decision = ROOT / "data" / "live" / "context_decision_log.parquet"
    decision_before = (decision.stat().st_mtime_ns, decision.stat().st_size) if decision.exists() else None
    ctrl_pid = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
    ctrl_before = ctrl_pid.read_text(encoding="utf-8") if ctrl_pid.exists() else None

    spec = importlib.util.spec_from_file_location("visual_refresher", REFRESHER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    # Isolate lock/pid into tmp to avoid clobbering a live refresher during tests.
    monkeypatch.setattr(mod, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(mod, "PID_PATH", tmp_path / "pid")
    monkeypatch.setattr(mod, "LOG_PATH", tmp_path / "refresher.log")

    code = mod.main(["--once"])
    assert code in (0, 1)  # 1 allowed if degraded once, but usually 0

    overlays = json.loads((PUBLIC / "data" / "paper_trade_overlays.json").read_text(encoding="utf-8"))
    open_pos = json.loads((PUBLIC / "data" / "open_positions.json").read_text(encoding="utf-8"))
    closed = json.loads((PUBLIC / "data" / "closed_trades.json").read_text(encoding="utf-8"))
    cycles = json.loads((PUBLIC / "data" / "controller_cycles.json").read_text(encoding="utf-8"))
    status = json.loads((PUBLIC / "data" / "visual_status.json").read_text(encoding="utf-8"))

    assert overlays.get("execution_enabled") is False
    assert overlays.get("paper_only") is True
    assert "entries" in overlays and "exits" in overlays
    assert "open_positions" in open_pos
    assert "closed_trades" in closed
    assert "cycles" in cycles and "actions" in cycles
    assert status.get("paper_ledger_write_performed") is False
    assert status.get("decision_log_write_performed") is False
    assert status.get("live_refresh_performed") is False
    assert status.get("bounded_paper_controller_touched") is False
    assert status.get("execution_enabled") is False
    assert "source_lag_minutes" in status
    assert "visual_refresh_age_seconds" in status
    assert status.get("visual_data_status") in {
        "LIVE_OK",
        "SOURCE_WAITING_NO_NEW_BAR",
        "VISUAL_DATA_STALE",
        "DEGRADED_LAST_GOOD_DATA",
    }

    # Synthetic 100000 absent from overlay prices
    def collect_prices(obj):
        out = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in {"price", "entry_price", "exit_price", "stop_loss_price", "take_profit_price", "fill_price", "mark_price"}:
                    if v is not None:
                        try:
                            out.append(float(v))
                        except (TypeError, ValueError):
                            pass
                else:
                    out.extend(collect_prices(v))
        elif isinstance(obj, list):
            for item in obj:
                out.extend(collect_prices(item))
        return out

    all_prices = collect_prices(overlays) + collect_prices(open_pos) + collect_prices(closed)
    assert all(not (99000.0 <= p <= 101000.0) for p in all_prices)
    assert overlays.get("synthetic_price_100000_absent") is True
    # At least one real closed trade should carry stop/take lines.
    closed_with_lines = [c for c in closed.get("closed_trades", []) if c.get("stop_take_lines")]
    assert closed_with_lines, "expected stop/take lines on real closed trade overlay"

    # Real restated trade prices preserved (context-start entries).
    prices = []
    for m in overlays.get("entries", []) + overlays.get("exits", []):
        if m.get("price") is not None:
            prices.append(float(m["price"]))
    for p in closed.get("closed_trades", []):
        if p.get("entry_price") is not None:
            prices.append(float(p["entry_price"]))
        if p.get("exit_price") is not None:
            prices.append(float(p["exit_price"]))
        assert p.get("stop_take_lines") is not None
        assert "realized_pnl_usd" in p
        assert "unrealized_pnl_usd" in p
        insp = p.get("inspector") or {}
        for field in (
            "signal_id",
            "order_id",
            "trade_id",
            "position_id",
            "side",
            "status",
            "paper_only",
            "execution_enabled",
        ):
            assert field in insp
        assert insp.get("paper_only") is True
        assert insp.get("execution_enabled") is False
    assert any(abs(p - 65751.56) < 0.05 or abs(p - 66333.99) < 0.05 for p in prices)

    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in ledger_files}
    assert after == before
    if decision_before is not None:
        assert (decision.stat().st_mtime_ns, decision.stat().st_size) == decision_before
    if ctrl_before is not None:
        assert ctrl_pid.read_text(encoding="utf-8") == ctrl_before


def test_duplicate_refresher_blocked_by_lock(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("visual_refresher2", REFRESHER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    lock = tmp_path / "lock"
    pid = tmp_path / "pid"
    monkeypatch.setattr(mod, "LOCK_PATH", lock)
    monkeypatch.setattr(mod, "PID_PATH", pid)
    monkeypatch.setattr(mod, "LOG_PATH", tmp_path / "log")
    # Fake another live holder PID (not this process).
    foreign_pid = os.getpid() + 10_000_001
    lock.write_text(f"{foreign_pid}\n", encoding="utf-8")
    monkeypatch.setattr(mod, "_pid_is_visual_refresher", lambda p: p == foreign_pid)
    assert mod.acquire_lock() is False


def test_freshness_separates_source_and_visual_age():
    import importlib.util
    from datetime import datetime, timedelta, timezone

    spec = importlib.util.spec_from_file_location("visual_refresher3", REFRESHER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    now = datetime.now(timezone.utc)
    old_source = (now - timedelta(minutes=45)).isoformat().replace("+00:00", "Z")
    fresh_visual = (now - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    stale_visual = (now - timedelta(seconds=200)).isoformat().replace("+00:00", "Z")

    waiting = mod.compute_freshness(
        live_ts=old_source,
        decision_ts=old_source,
        last_visual_refresh_ts=fresh_visual,
        visual_stale_seconds=90,
    )
    assert waiting["visual_data_status"] == "SOURCE_WAITING_NO_NEW_BAR"
    assert waiting["source_lag_minutes"] > 30
    assert waiting["visual_refresh_age_seconds"] < 90

    stale = mod.compute_freshness(
        live_ts=old_source,
        decision_ts=old_source,
        last_visual_refresh_ts=stale_visual,
        visual_stale_seconds=90,
    )
    assert stale["visual_data_status"] == "VISUAL_DATA_STALE"
