"""VIS3A — equal GRID contract, global strip removed, navigation controls present."""

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
    assert 'getElementById("globalLifecycleCanvas")' not in js


def test_equal_grid_css_contract():
    html = INDEX.read_text(encoding="utf-8")
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in html
    assert "grid-template-rows: repeat(2, minmax(0, 1fr))" in html
    assert re.search(r"\.tf-chart-panel\s*\{[^}]*min-width:\s*0", html, re.S)
    assert re.search(r"\.tf-chart-panel\s*\{[^}]*min-height:\s*0", html, re.S)
    assert ".tf-chart-empty[hidden] { display: none !important; }" in html


def test_four_panels_and_nav_controls():
    html = INDEX.read_text(encoding="utf-8")
    for tf in ("M15", "M30", "H1", "H4"):
        assert f'id="chart-{tf}"' in html
        assert f'data-tf="{tf}"' in html
    assert 'id="btnResetView"' in html
    assert 'id="btnFitView"' in html
    assert 'id="btnGoLatest"' in html
    assert 'value="GRID"' in html
    js = APP_JS.read_text(encoding="utf-8")
    assert "followLatest" in js
    assert "preserveViewportAcrossReload" in js
    assert "Go to latest" in html or "btnGoLatest" in html
    assert "TP ↑" in js or "TP ↑" in APP_JS.read_text(encoding="utf-8")
    assert "drawContextBands" in js
    assert "TF_SOURCE_CONTAMINATION" in js


def test_no_ctx_trade_identity_and_no_ops_false_claim():
    js = APP_JS.read_text(encoding="utf-8")
    assert "function contextNumber" not in js
    assert re.search(r"CTX \$\{", js) is None
    assert "OPS3A" in js  # deferred OPS summary acknowledged, not claimed complete
    html = INDEX.read_text(encoding="utf-8")
    assert "paperPnlBlock" not in html
    assert "modelMetricsBlock" not in html
