"""VIS3C — standalone TF URLs: one chart in DOM, TF nav links, no GRID hide pattern."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps" / "context_visualizer" / "public"
INDEX = PUBLIC / "index.html"
APP_JS = PUBLIC / "lifecycle_app.js"


def test_global_lifecycle_strip_absent():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="globalLifecycleStrip"' not in html
    assert 'id="globalLifecycleCanvas"' not in html
    assert html.count("globalLifecycle") == 0
    js = APP_JS.read_text(encoding="utf-8")
    assert "renderGlobalStrip" not in js
    assert 'getElementById("globalLifecycleStrip")' not in js


def test_standalone_url_nav_links():
    html = INDEX.read_text(encoding="utf-8")
    for tf in ("M15", "M30", "H1", "H4"):
        assert f'href="./index.html?tf={tf}"' in html
        assert f'data-tf="{tf}"' in html
    assert 'id="tfNav"' in html
    assert 'id="tfChartHost"' in html
    # No static multi-panel GRID of four canvases
    assert 'id="tfChartGrid"' not in html
    assert 'value="GRID"' not in html
    assert 'id="timeframeSelect"' not in html
    # Host starts empty — panel mounted by JS for active TF only
    assert re.search(r'id="tfChartHost"[^>]*>\s*</div>', html, re.S)


def test_js_mounts_only_active_tf():
    js = APP_JS.read_text(encoding="utf-8")
    assert "parseStandaloneTf" in js
    assert "mountStandalonePanel" in js
    assert "activeTimeframes" in js
    assert "VIS3C" in js or "__VIS3C__" in js
    assert "foreignChartsInDom" in js
    assert "drawLongEntryMarker" in js
    assert "drawShortEntryMarker" in js
    assert "▲ ${label}" in js or "▲ ${" in js
    assert "▼ ${label}" in js or "▼ ${" in js
    assert "× ${label}" in js or "× ${" in js
    assert "preserveViewportAcrossReload" in js
    assert "followLatest" in js
    # Must not keep GRID hide-via-CSS pattern as primary architecture
    assert 'data-mode="GRID"' not in js
    assert "VALID_MODES" not in js or "standalone" in js.lower()


def test_viewport_controls_present():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="btnResetView"' in html
    assert 'id="btnFitView"' in html
    assert 'id="btnGoLatest"' in html
    assert ".tf-chart-empty[hidden] { display: none !important; }" in html


def test_no_ops_pnl_panels():
    html = INDEX.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    assert "paperPnlBlock" not in html
    assert "modelMetricsBlock" not in html
    assert "function contextNumber" not in js
    assert re.search(r"CTX \$\{", js) is None
