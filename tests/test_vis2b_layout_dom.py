"""VIS3C — marker contract + generator hook + DOM single-chart regression (replaces VIS2B GRID asserts)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))

PUBLIC = ROOT / "apps" / "context_visualizer" / "public"
INDEX = PUBLIC / "index.html"
APP_JS = PUBLIC / "lifecycle_app.js"


def test_tradingview_marker_contract_in_js():
    js = APP_JS.read_text(encoding="utf-8")
    assert "drawLongEntryMarker" in js
    assert "drawShortEntryMarker" in js
    assert "drawExitMarker" in js
    assert "▲" in js
    assert "▼" in js
    assert "×" in js
    assert "public_number" in js
    assert "OPEN" in js
    assert "display_label" in js


def test_single_chart_host_no_static_foreign_canvases():
    html = INDEX.read_text(encoding="utf-8")
    # Static HTML must not pre-create four canvases
    for tf in ("M15", "M30", "H1", "H4"):
        assert f'id="chart-{tf}"' not in html
    assert 'id="tfChartHost"' in html
    assert "tf-nav" in html
    assert 'id="lifecycleCanvas"' not in html
    assert "paperPnlBlock" not in html
    assert "modelMetricsBlock" not in html


def test_js_standalone_api():
    js = APP_JS.read_text(encoding="utf-8")
    assert "parseStandaloneTf" in js
    assert "mountStandalonePanel" in js
    assert "foreignChartsInDom" in js
    assert "preserveViewportAcrossReload" in js
    assert "__VIS3C__" in js


def test_generator_hook_default_off(tmp_path, monkeypatch):
    from generate_lifecycle_context_data import emit_timeframe_chart_truth_if_enabled

    monkeypatch.delenv("ENABLE_TIMEFRAME_CHART_TRUTH", raising=False)
    monkeypatch.delenv("TIMEFRAME_CHART_TRUTH_OUT", raising=False)
    assert emit_timeframe_chart_truth_if_enabled() is None


def test_generator_hook_explicit_candidate_path(tmp_path, monkeypatch):
    from generate_lifecycle_context_data import emit_timeframe_chart_truth_if_enabled

    out = tmp_path / "timeframe_chart_truth.json"
    monkeypatch.setenv("TIMEFRAME_CHART_TRUTH_OUT", str(out))
    monkeypatch.delenv("ENABLE_TIMEFRAME_CHART_TRUTH", raising=False)
    path = emit_timeframe_chart_truth_if_enabled()
    assert path == out
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "timeframe_chart_truth_v3" in text or "timeframe_chart_truth_v2" in text
    payload = json.loads(text)
    assert "M15" in payload.get("timeframes", {})
    assert "context_segments" in (payload["timeframes"]["M15"] or {})
    if payload.get("schema_version") == "timeframe_chart_truth_v3":
        ents = (payload["timeframes"]["M15"].get("closed_trades") or []) + (
            payload["timeframes"]["M15"].get("open_positions") or []
        )
        if ents:
            assert ents[0].get("public_number", "").startswith("M15_")


def test_ops_files_untouched_marker():
    forbidden = [
        ROOT / "src/btc_ml/trading/trading_performance_truth.py",
        ROOT / "src/btc_ml/trading/timeframe_state_adapter.py",
        ROOT / "multi_timeframe_availability.py",
    ]
    for path in forbidden:
        assert path.exists()


def test_marker_pairing_uses_same_public_number():
    js = APP_JS.read_text(encoding="utf-8")
    assert "publicNumber(entity)" in js
    assert re.search(r"drawExitMarker\(ctx,\s*x2,\s*y,\s*label", js)
    assert "selectedTradeKey" in js
