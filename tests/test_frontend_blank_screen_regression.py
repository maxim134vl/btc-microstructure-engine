"""Stage 14 — Frontend blank screen regression (static + null-safe contracts)."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "dashboard" / "frontend" / "src"
OPS_DASHBOARD = FRONTEND / "components" / "ops" / "OpsDashboard.tsx"
STATUS_INDEX = FRONTEND / "components" / "status" / "index.ts"
STATUS_MAPPERS = FRONTEND / "components" / "status" / "mappers.ts"
STATUS_TRANSLATE = FRONTEND / "components" / "status" / "translate.ts"
LIFECYCLE_APP = (
    ROOT
    / "apps"
    / "context_visualizer"
    / "public"
    / "lifecycle_app.js"
)
LIFECYCLE_INDEX = (
    ROOT
    / "apps"
    / "context_visualizer"
    / "public"
    / "index.html"
)
REFRESHER = ROOT / "scripts" / "research" / "run_market_context_visual_refresher.py"


def test_status_index_exports_stage13_translators():
    text = STATUS_INDEX.read_text(encoding="utf-8")
    assert "translateRuntimeStability" in text
    assert "translateHealthDimensionStatus" in text


def test_ops_dashboard_has_section_error_boundary():
    text = OPS_DASHBOARD.read_text(encoding="utf-8")
    assert "SectionErrorBoundary" in text
    assert "Section unavailable" in text
    assert "Runtime Health" in text
    assert "Research Pipeline" in text
    assert "Runtime Activity" in text


def test_mappers_null_safe_signatures():
    text = STATUS_MAPPERS.read_text(encoding="utf-8")
    assert "resolveHealthDimensionStatus(status?: string | null)" in text or re.search(
        r"resolveHealthDimensionStatus\(status\?: string \| null\)", text
    )
    assert "resolveRuntimeStability(input?:" in text
    assert 'status || "UNKNOWN"' in text or "(status || \"UNKNOWN\")" in text
    assert "resolveOpsLevel(level?: string | null" in text or "resolveOpsLevel(level?:" in text


def test_translate_handles_undefined_contract():
    text = STATUS_TRANSLATE.read_text(encoding="utf-8")
    assert "translateValidationLevel = (level?: string | null)" in text or "level?: string | null" in text
    assert "translateHealthDimensionStatus" in text
    assert "translateRuntimeStability" in text


def test_lifecycle_app_error_handlers_and_cache():
    js = LIFECYCLE_APP.read_text(encoding="utf-8")
    assert 'window.addEventListener("error"' in js
    assert 'window.addEventListener("unhandledrejection"' in js
    assert "showViewerError" in js
    assert 'cache: "no-store"' in js
    assert "Date.now()" in js
    assert "cacheBust" in js
    assert "Array.isArray" in js
    assert "state.candles" in js
    assert "state.episodes" in js


def test_lifecycle_index_has_visible_shell():
    html = LIFECYCLE_INDEX.read_text(encoding="utf-8")
    assert 'id="statusLine"' in html
    assert "Loading lifecycle context" in html
    assert 'id="viewerRoot"' in html or "lifecycle-shell" in html
    assert 'id="viewerErrorPanel"' in html


def test_refresher_logger_handlers_stable():
    # Import module and call get_refresher_logger twice — handler count must stay stable.
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "research"))
    mod = importlib.import_module("run_market_context_visual_refresher")
    importlib.reload(mod)
    logger_a = mod.get_refresher_logger()
    count_a = len(logger_a.handlers)
    logger_b = mod.get_refresher_logger()
    count_b = len(logger_b.handlers)
    assert logger_a is logger_b
    assert count_a == count_b
    assert count_a >= 1
    # Second configure path must not stack handlers.
    _ = mod.get_refresher_logger()
    assert len(mod.get_refresher_logger().handlers) == count_a


def test_refresher_log_line_skips_duplicate_file_when_not_tty(monkeypatch, tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "research"))
    mod = importlib.import_module("run_market_context_visual_refresher")
    importlib.reload(mod)

    log_path = tmp_path / "refresher.log"
    monkeypatch.setattr(mod, "LOG_PATH", log_path)

    class _NonTty:
        def isatty(self):
            return False

        def write(self, *_args, **_kwargs):
            return None

        def flush(self):
            return None

    monkeypatch.setattr(sys, "stdout", _NonTty())
    # print goes to fake stdout; file must not be written a second time.
    mod.log_line("[pass] once")
    assert not log_path.exists() or log_path.read_text(encoding="utf-8").count("[pass] once") <= 1


def test_python_null_safe_mapper_parity_via_source():
    """Document expected fallback labels for missing optional fields (static contract)."""
    text = STATUS_MAPPERS.read_text(encoding="utf-8")
    assert "MISSING_DATA" in text or "UNKNOWN" in text
    assert "INFORMATIONAL" in text or "operational" in text
    dash = OPS_DASHBOARD.read_text(encoding="utf-8")
    assert "safeHealth" in dash or "MISSING_DATA" in dash
    assert "dimensions?.runtime" in dash or "dimensions?.runtime?" in dash
