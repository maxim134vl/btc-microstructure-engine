"""Trade-render fix — stable TF_N labels reject technical IDs; standalone DOM."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps" / "context_visualizer" / "public"
INDEX = PUBLIC / "index.html"
APP_JS = PUBLIC / "lifecycle_app.js"


def test_global_strip_absent_and_standalone_host():
    html = INDEX.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    assert 'id="globalLifecycleStrip"' not in html
    assert 'id="tfChartHost"' in html
    assert 'id="tfChartGrid"' not in html
    assert "mountStandalonePanel" in js
    assert "parseStandaloneTf" in js


def test_js_rejects_technical_marker_labels():
    js = APP_JS.read_text(encoding="utf-8")
    assert "isStableTfNumber" in js
    assert "ensureTfOrdinals" in js
    assert "function publicNumber" in js
    assert "Entry  ${fmtPrice(entry)}" in js
    assert "Never paint hex" in js


def test_tradingview_position_zone_contract_in_js():
    js = APP_JS.read_text(encoding="utf-8")
    assert "drawZoneRect" in js
    assert "rewardFill" in js
    assert "riskFill" in js
    assert "TP ${fmtPrice" in js or "TP `" in js
    assert "SL ${fmtPrice" in js or "SL `" in js
    assert "collectVisiblePriceExtras" in js
    assert "drawContextBands" in js
    assert "context_segments" in js
    assert re.search(r"fillRect\(x1,\s*g\.pad\.top,\s*width,\s*3\)", js)


def test_tf_nav_links_present():
    html = INDEX.read_text(encoding="utf-8")
    for tf in ("M15", "M30", "H1", "H4"):
        assert f"?tf={tf}" in html
    assert 'id="btnResetView"' in html
    assert 'id="btnFitView"' in html
    assert 'id="btnGoLatest"' in html
