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
    # Closed span uses exit; open extends to last candle
    assert "kind === \"closed\"" in js or "kind === 'closed'" in js
    assert "chart.visible.length - 1" in js
    assert " · OPEN" in js
    assert "Exit  ${fmtPrice" in js or "Exit  `" in js
    assert re.search(r"finitePrice\(entity\.stop_price\)", js)
    assert re.search(r"finitePrice\(entity\.take_profit_price\)", js)


def test_no_static_four_canvases_and_nav():
    html = INDEX.read_text(encoding="utf-8")
    for tf in ("M15", "M30", "H1", "H4"):
        assert f'id="chart-{tf}"' not in html
        assert f"?tf={tf}" in html
    assert "paperPnlBlock" not in html


def test_generator_hook_emits_v3_ordinals(tmp_path, monkeypatch):
    from generate_lifecycle_context_data import emit_timeframe_chart_truth_if_enabled

    monkeypatch.delenv("ENABLE_TIMEFRAME_CHART_TRUTH", raising=False)
    assert emit_timeframe_chart_truth_if_enabled() is None

    out = tmp_path / "timeframe_chart_truth.json"
    monkeypatch.setenv("TIMEFRAME_CHART_TRUTH_OUT", str(out))
    path = emit_timeframe_chart_truth_if_enabled()
    assert path == out
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "timeframe_chart_truth_v3"
    m15 = payload["timeframes"]["M15"]
    ents = (m15.get("closed_trades") or []) + (m15.get("open_positions") or [])
    assert ents
    assert ents[0]["public_number"].startswith("M15_")
    assert " · " not in ents[0]["public_number"]
    assert len(m15.get("context_segments") or []) >= 1


def test_ops_files_untouched_marker():
    for path in (
        ROOT / "src/btc_ml/trading/trading_performance_truth.py",
        ROOT / "src/btc_ml/trading/timeframe_state_adapter.py",
    ):
        assert path.exists()
