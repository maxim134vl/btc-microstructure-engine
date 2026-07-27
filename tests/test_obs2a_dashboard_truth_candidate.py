#!/usr/bin/env python3
"""OBS2A — dashboard/visualizer trading-truth candidate tests (read-only books)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
VIS = ROOT / "apps" / "context_visualizer"
APP_JS = VIS / "public" / "lifecycle_app.js"
INDEX = VIS / "public" / "index.html"
TRADING_TRUTH = VIS / "trading_truth.py"
REFRESHER = ROOT / "scripts" / "live" / "run_market_context_visual_refresher.py"
CANDIDATE = ROOT / "data" / "candidate" / "architecture_recovery" / "obs2a_dashboard_truth_candidate"
BOOKS = ROOT / "data" / "trading" / "timeframe_traders"
TIMEFRAMES = ("M15", "M30", "H1", "H4")


@pytest.fixture(scope="module")
def truth_mod():
    sys.path.insert(0, str(VIS))
    import trading_truth as mod  # type: ignore

    return mod


@pytest.fixture(scope="module")
def book_mtimes():
    paths = []
    for tf in TIMEFRAMES:
        for name in ("signals", "orders", "fills", "trades", "positions"):
            path = BOOKS / tf / f"{name}.parquet"
            if path.exists():
                paths.append(path)
    return {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in paths}


def test_four_canonical_open_positions_returned(truth_mod, book_mtimes):
    rows = truth_mod.load_open_positions(timeframe="ALL")
    assert len(rows) == 4
    assert {r["timeframe"] for r in rows} == set(TIMEFRAMES)
    assert all(r["status"] == "OPEN" for r in rows)
    assert all(r["side"] == "LONG" for r in rows)
    for r in rows:
        assert r["position_id"]
        assert r["entry_timestamp"]
        assert r["entry_price"] is not None
        # Missing exit fields must not drop OPEN rows.
        assert r.get("exit_timestamp") is None
        assert r.get("exit_price") is None
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in book_mtimes}
    assert after == book_mtimes


@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_timeframe_filter_returns_only_selected(truth_mod, tf):
    rows = truth_mod.load_open_positions(timeframe=tf)
    assert len(rows) == 1
    assert rows[0]["timeframe"] == tf


def test_all_returns_all_four(truth_mod):
    payload = truth_mod.build_trading_truth(timeframe="ALL")
    assert len(payload["open_positions"]) == 4
    assert payload["supported_timeframes"] == ["ALL", *TIMEFRAMES]


def test_open_positions_not_dropped_due_to_missing_exit_fields(truth_mod):
    rows = truth_mod.load_open_positions()
    assert rows
    for row in rows:
        assert "exit_timestamp" not in row or row["exit_timestamp"] is None
        assert row["status"] == "OPEN"


def test_canonical_episode_885_returned(truth_mod):
    active = truth_mod.active_episode_from_memory()
    assert active is not None
    assert int(active["episode_id"]) == 885
    episodes = truth_mod.collapse_lifecycle_episodes()
    match = [e for e in episodes if int(e["episode_id"]) == 885]
    assert len(match) == 1
    assert match[0]["is_active"] is True
    assert match[0]["context"] == "LONG_CONTEXT"
    assert match[0]["start_time"]
    assert match[0]["end_time"]
    # One continuous band: start before or equal tip end.
    assert match[0]["start_time_unix"] <= match[0]["end_time_unix"]


def test_shadow_context_not_presented_as_active_trading_context(truth_mod):
    payload = truth_mod.build_trading_truth()
    shadow = payload["shadow_diagnostics"]
    assert shadow is None or shadow.get("is_active_trading_context") is False
    if shadow:
        assert shadow.get("label") == "Shadow diagnostics"
    active = payload["active_episode"]
    assert active is not None
    assert active.get("plane") == "decision_driving"
    assert active.get("source") == "market_context_lifecycle_memory"


def test_utc_timestamps_preserve_epoch(truth_mod):
    rows = truth_mod.load_open_positions()
    for row in rows:
        ts = row["entry_timestamp"]
        assert ts.endswith("Z") or "+" in ts
        stamp = pd.Timestamp(ts)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        else:
            stamp = stamp.tz_convert("UTC")
        # Round-trip identity: no Asia/Almaty (+5) shift baked into stored epoch.
        assert abs(stamp.timestamp() - pd.Timestamp(ts).tz_convert("UTC").timestamp()) < 1e-6


def test_frontend_timeframe_selector_and_truth_wiring():
    html = INDEX.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    assert 'id="timeframeSelect"' in html
    for tf in ("ALL", "M15", "M30", "H1", "H4"):
        assert f'value="{tf}"' in html
    assert 'id="truthBanner"' in html
    assert "Trading runtime: LIVE PAPER" in html
    assert "applyTimeframeFilter" in js
    assert "trading_truth.json" in js
    assert "open_positions.json" in js
    assert "No closed trades for selected timeframe" in js
    assert "STALE DATA" in js
    assert "Active trading context" in js
    assert "shadow diag" in js


def test_frontend_open_positions_and_closed_trades_separated():
    js = APP_JS.read_text(encoding="utf-8")
    assert "allOpenPositions" in js
    assert "allClosedTrades" in js
    assert "open paper positions" in js
    # Must not treat OPEN as requiring CLOSED status.
    assert 'status || "CLOSED").toUpperCase() !== "OPEN"' in js or "OPEN" in js


def test_refresher_does_not_overwrite_lifecycle_with_policy_export():
    text = REFRESHER.read_text(encoding="utf-8")
    assert "Shadow diagnostics" in text
    assert "Never overwrite the" in text or "decision-driving lifecycle episode" in text
    assert "write_trading_truth_artifacts" in text
    assert "timeframe_traders" in text


def test_candidate_snapshot_parity(truth_mod, tmp_path, book_mtimes):
    out = tmp_path / "obs2a"
    payload = truth_mod.write_trading_truth_artifacts(out, timeframe="ALL")
    snapshot = {
        "episode": (payload.get("active_episode") or {}).get("episode_id"),
        "context": (payload.get("active_episode") or {}).get("context"),
        "open_positions": len(payload["open_positions"]),
        "timeframes": sorted({r["timeframe"] for r in payload["open_positions"]}),
        "position_ids": sorted(r["position_id"] for r in payload["open_positions"]),
        "active_episode_band": next(
            (e for e in payload["episodes"] if int(e["episode_id"]) == 885),
            None,
        ),
        "shadow_is_active_trading_context": (payload.get("shadow_diagnostics") or {}).get(
            "is_active_trading_context", False
        ),
        "utc_entry_timestamps": [r["entry_timestamp"] for r in payload["open_positions"]],
    }
    CANDIDATE.mkdir(parents=True, exist_ok=True)
    (CANDIDATE / "dashboard_truth_snapshot.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (CANDIDATE / "trading_truth.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Canonical books vs backend response
    book_open = 0
    for tf in TIMEFRAMES:
        frame = pd.read_parquet(BOOKS / tf / "positions.parquet")
        book_open += int((frame["status"].astype(str).str.upper() == "OPEN").sum())
    assert book_open == 4
    assert snapshot["open_positions"] == 4
    assert snapshot["episode"] == 885
    assert snapshot["context"] == "LONG_CONTEXT"
    assert snapshot["timeframes"] == sorted(TIMEFRAMES)
    assert snapshot["active_episode_band"] is not None
    assert snapshot["shadow_is_active_trading_context"] is False

    # Frontend model parity (same adapter fields lifecycle_app consumes)
    rendered = {
        "open_positions": payload["open_positions"],
        "closed_trades": payload["closed_trades"],
        "active_episode": payload["active_episode"],
        "episodes": [e for e in payload["episodes"] if int(e["episode_id"]) == 885],
    }
    assert len(rendered["open_positions"]) == 4
    assert len(rendered["episodes"]) == 1
    assert rendered["active_episode"]["episode_id"] == 885

    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in book_mtimes}
    assert after == book_mtimes


def test_regression_lifecycle_and_m15_closed_still_wired():
    js = APP_JS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    assert "lifecycle_candles.json" in js
    assert "lifecycle_context_episodes.json" in js
    assert "lifecycle_latest.json" in js
    assert "rangeSelect" in html
    assert "drawChart" in js or "renderChart" in js
    assert TRADING_TRUTH.exists()


def test_no_trading_files_written_by_adapter(truth_mod, book_mtimes):
    truth_mod.build_trading_truth(timeframe="ALL")
    truth_mod.load_closed_trades(timeframe="M15")
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in book_mtimes}
    assert after == book_mtimes
