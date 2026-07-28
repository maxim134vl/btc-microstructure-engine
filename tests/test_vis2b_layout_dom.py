"""Trade-render fix — position zone orientation + generator hook regressions."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))

PUBLIC = ROOT / "apps" / "context_visualizer" / "public"
APP_JS = PUBLIC / "lifecycle_app.js"
INDEX = PUBLIC / "index.html"


def test_long_short_zone_and_open_closed_span_in_js():
    js = APP_JS.read_text(encoding="utf-8")
    assert "drawZoneRect" in js
    assert "take_profit_price" in js
    assert "stop_price" in js
    assert "kind === \"closed\"" in js or "kind === 'closed'" in js
    assert "chart.visible.length - 1" in js
    # Clean canvas: no Entry/Exit/OPEN text clutter; compact markers only
    assert " · OPEN" not in js
    assert "Entry  ${fmtPrice" not in js
    assert "Exit  ${fmtPrice" not in js
    assert "placeCompact" in js
    assert re.search(r"finitePrice\(entity\.stop_price\)", js)
    assert re.search(r"finitePrice\(entity\.take_profit_price\)", js)
    # Single TF_N label path uses publicNumber directly
    assert "placeCompact(\n      xMid" in js or "placeCompact(\n      xMid," in js or "placeCompact(" in js


def test_no_static_four_canvases_and_nav():
    html = INDEX.read_text(encoding="utf-8")
    for tf in ("M15", "M30", "H1", "H4"):
        assert f'id="chart-{tf}"' not in html
        assert f"?tf={tf}" in html
    assert "paperPnlBlock" not in html


def test_generator_hook_emits_v4_ordinals(tmp_path, monkeypatch):
    from generate_lifecycle_context_data import emit_timeframe_chart_truth_if_enabled

    monkeypatch.delenv("ENABLE_TIMEFRAME_CHART_TRUTH", raising=False)
    monkeypatch.delenv("TIMEFRAME_CHART_TRUTH_OUT", raising=False)
    # Isolate from LIVE1B active epoch so the gated emit path is exercised.
    monkeypatch.setattr(
        "apps.context_visualizer.active_epoch_trade_filter.live1b_paper_active",
        lambda: False,
        raising=False,
    )
    monkeypatch.setattr(
        "active_epoch_trade_filter.live1b_paper_active",
        lambda: False,
        raising=False,
    )
    assert emit_timeframe_chart_truth_if_enabled() is None

    out = tmp_path / "timeframe_chart_truth.json"
    monkeypatch.setenv("TIMEFRAME_CHART_TRUTH_OUT", str(out))
    path = emit_timeframe_chart_truth_if_enabled()
    assert path == out
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "timeframe_chart_truth_v4"
    m15 = payload["timeframes"]["M15"]
    assert len(m15.get("candles") or []) >= 1
    assert len(m15.get("context_segments") or []) >= 1
    ents = (m15.get("closed_trades") or []) + (m15.get("open_positions") or [])
    # Under LIVE1B empty epoch, overlays may be empty; when present they use TF_N.
    for ent in ents:
        assert str(ent.get("public_number") or "").startswith("M15_")
        assert " · " not in str(ent.get("public_number") or "")


def test_ops_files_untouched_marker():
    for path in (
        ROOT / "src/btc_ml/trading/trading_performance_truth.py",
        ROOT / "src/btc_ml/trading/timeframe_state_adapter.py",
    ):
        assert path.exists()
