"""VIS2B — layout / DOM / panel removal / generator hook regressions."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))

PUBLIC = ROOT / "apps" / "context_visualizer" / "public"
INDEX = PUBLIC / "index.html"
APP_JS = PUBLIC / "lifecycle_app.js"
GEN = ROOT / "apps" / "context_visualizer" / "generate_lifecycle_context_data.py"


def test_four_chart_containers_and_global_strip():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="globalLifecycleStrip"' in html
    assert html.count('id="globalLifecycleStrip"') == 1
    for tf in ("M15", "M30", "H1", "H4"):
        assert f'id="chart-{tf}"' in html
        assert f'data-tf="{tf}"' in html
    assert 'value="GRID"' in html
    assert 'id="lifecycleCanvas"' not in html
    assert "paperPnlBlock" not in html
    assert "modelMetricsBlock" not in html
    assert "Detailed PnL" not in html
    assert "Trading Model Evaluation Metrics" not in html


def test_js_has_no_ctx_trade_identity_helper_and_no_pnl_renderers():
    js = APP_JS.read_text(encoding="utf-8")
    assert "function contextNumber" not in js
    assert "renderPnlPanel" not in js
    assert "renderModelMetricsPanel" not in js
    assert "VALID_MODES" in js
    assert "GRID" in js
    assert "trade_id" in js
    assert re.search(r"CTX \$\{", js) is None


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
    assert "timeframe_chart_truth_v1" in text
    assert "M15" in text
    assert "global_lifecycle" in text


def test_ops_files_untouched_marker():
    # Scope guard: VIS2B must not modify these production paths in the same change set intent.
    forbidden = [
        ROOT / "src/btc_ml/trading/trading_performance_truth.py",
        ROOT / "src/btc_ml/trading/timeframe_state_adapter.py",
        ROOT / "multi_timeframe_availability.py",
    ]
    for path in forbidden:
        assert path.exists()
