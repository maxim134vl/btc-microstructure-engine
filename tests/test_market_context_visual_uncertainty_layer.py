"""Tests for the Market Context Viewer uncertainty / doubt visualization layer.

Shadow-only visual layer. These tests confirm the visual generator surfaces
CANDIDATE / CHALLENGED / INVALIDATED / AUCTION_NEUTRALIZATION states as
overlay segments/markers, that confirmed context rendering stays intact, and
that no execution / action_allowed semantics are introduced by the overlay.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEN_PATH = ROOT / "apps" / "context_visualizer" / "generate_lifecycle_context_data.py"
VIEWER_DIR = ROOT / "apps" / "context_visualizer" / "public"
APP_JS = VIEWER_DIR / "lifecycle_app.js"
INDEX_HTML = VIEWER_DIR / "index.html"
LIFECYCLE_CSS = VIEWER_DIR / "lifecycle.css"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_lifecycle_context_data", GEN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_lifecycle_context_data"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


def _row(ts_unix: int, **overrides):
    base = {
        "timestamp": f"unix-{ts_unix}",
        "time": ts_unix,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1.0,
        "active_market_context": "OBSERVE",
        "lifecycle_state": "NO_ACTIVE_CONTEXT",
        "raw_market_context": "OBSERVE",
        "raw_context_status": "OBSERVE",
        "candidate_context": None,
        "challenge_context": None,
        "auction_episode": "BALANCE",
        "auction_episode_status": "OBSERVE",
        "cognitive_market_state": "BALANCE",
        "cognitive_state_status": "NEUTRAL",
        "previous_active_market_context": None,
        "invalidation_type": "NONE",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Generator: uncertainty segments
# --------------------------------------------------------------------------- #


def test_candidate_rows_not_dropped():
    rows = [
        _row(1000, lifecycle_state="CANDIDATE", raw_market_context="LONG_CONTEXT",
             raw_context_status="DEVELOPING", candidate_context="LONG_CONTEXT"),
        _row(1900, lifecycle_state="CANDIDATE", raw_market_context="LONG_CONTEXT",
             raw_context_status="DEVELOPING", candidate_context="LONG_CONTEXT"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    candidates = [s for s in segments if s["visual_type"] == "CANDIDATE"]
    assert candidates, "CANDIDATE rows must not be dropped from visual data"


def test_candidate_long_creates_segment():
    rows = [
        _row(2000, active_market_context="OBSERVE", lifecycle_state="CANDIDATE",
             raw_market_context="LONG_CONTEXT", raw_context_status="DEVELOPING",
             candidate_context="LONG_CONTEXT"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    assert len(segments) == 1
    seg = segments[0]
    assert seg["visual_type"] == "CANDIDATE"
    assert seg["direction"] == "LONG_CONTEXT"
    assert seg["label"] == "CANDIDATE LONG"
    assert seg["shadow_only"] is True


def test_candidate_short_creates_segment():
    rows = [
        _row(3000, active_market_context="OBSERVE", lifecycle_state="CANDIDATE",
             raw_market_context="SHORT_CONTEXT", raw_context_status="DEVELOPING",
             candidate_context="SHORT_CONTEXT"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    assert len(segments) == 1
    seg = segments[0]
    assert seg["visual_type"] == "CANDIDATE"
    assert seg["direction"] == "SHORT_CONTEXT"
    assert seg["label"] == "CANDIDATE SHORT"


def test_developing_directional_without_candidate_flag_is_candidate():
    # raw directional + DEVELOPING but lifecycle not yet flagged CANDIDATE and active OBSERVE.
    rows = [
        _row(3500, active_market_context="OBSERVE", lifecycle_state="NO_ACTIVE_CONTEXT",
             raw_market_context="SHORT_CONTEXT", raw_context_status="DEVELOPING"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    assert len(segments) == 1
    assert segments[0]["visual_type"] == "CANDIDATE"
    assert segments[0]["direction"] == "SHORT_CONTEXT"


def test_challenged_creates_visible_segment():
    rows = [
        _row(4000, active_market_context="SHORT_CONTEXT", lifecycle_state="CHALLENGED",
             challenge_context="LONG_CONTEXT", raw_market_context="LONG_CONTEXT"),
        _row(4900, active_market_context="SHORT_CONTEXT", lifecycle_state="CHALLENGED",
             challenge_context="LONG_CONTEXT", raw_market_context="LONG_CONTEXT"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    challenged = [s for s in segments if s["visual_type"] == "CHALLENGED"]
    assert len(challenged) == 1
    assert challenged[0]["direction"] == "SHORT_CONTEXT"  # follows active context
    assert challenged[0]["label"] == "CHALLENGED SHORT"


def test_invalidated_creates_marker():
    rows = [
        _row(5000, active_market_context="OBSERVE", lifecycle_state="INVALIDATED",
             invalidation_type="NONE", previous_active_market_context="LONG_CONTEXT"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    markers = [s for s in segments if s["visual_type"] == "INVALIDATED"]
    assert len(markers) == 1
    # A marker is a boundary point, not a directional region.
    assert markers[0]["direction"] == "OBSERVE"
    assert markers[0]["start_time_unix"] == markers[0]["end_time_unix"]


def test_auction_neutralization_creates_marker():
    rows = [
        _row(6000, active_market_context="OBSERVE", lifecycle_state="INVALIDATED",
             invalidation_type="AUCTION_NEUTRALIZATION",
             previous_active_market_context="LONG_CONTEXT"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    markers = [s for s in segments if s["visual_type"] == "AUCTION_NEUTRALIZATION"]
    assert len(markers) == 1
    assert markers[0]["label"] == "AUCTION NEUTRALIZATION"
    assert markers[0]["direction"] == "OBSERVE"


def test_persistent_neutralization_does_not_spam_markers():
    # invalidation_type stays AUCTION_NEUTRALIZATION for many OBSERVE bars — only the
    # rising edge should produce a marker (boundary event), not every bar.
    rows = [
        _row(7000, invalidation_type="NONE"),
        _row(7900, invalidation_type="AUCTION_NEUTRALIZATION"),
        _row(8800, invalidation_type="AUCTION_NEUTRALIZATION"),
        _row(9700, invalidation_type="AUCTION_NEUTRALIZATION"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    markers = [s for s in segments if s["visual_type"] == "AUCTION_NEUTRALIZATION"]
    assert len(markers) == 1, "persistent neutralization must collapse to one boundary marker"


def test_confirmed_active_context_not_duplicated_as_uncertainty():
    # ACTIVE + directional confirmed context must stay on the episode layer and
    # NOT appear as an uncertainty segment.
    rows = [
        _row(10000, active_market_context="LONG_CONTEXT", lifecycle_state="ACTIVE",
             raw_market_context="LONG_CONTEXT", raw_context_status="ACTIVE"),
        _row(10900, active_market_context="LONG_CONTEXT", lifecycle_state="ACTIVE",
             raw_market_context="LONG_CONTEXT", raw_context_status="ACTIVE"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    regions = [s for s in segments if s["visual_type"] in {"CANDIDATE", "CHALLENGED"}]
    assert regions == [], "confirmed ACTIVE context must not become an uncertainty region"


def test_segments_are_shadow_only_and_no_action_semantics():
    rows = [
        _row(11000, lifecycle_state="CANDIDATE", raw_market_context="LONG_CONTEXT",
             raw_context_status="DEVELOPING", candidate_context="LONG_CONTEXT"),
    ]
    segments = gen.build_uncertainty_segments(rows)
    for seg in segments:
        assert seg["shadow_only"] is True
        # Uncertainty overlay must never introduce execution / action semantics.
        assert "action_allowed" not in seg


def test_episode_fill_confirmed_rendering_unchanged():
    # episodeFill-equivalent (Python side): confirmed context blocks build unchanged.
    # Guard the source so confirmed episode building keeps LONG/SHORT counting.
    src = GEN_PATH.read_text(encoding="utf-8")
    assert 'ep.get("context") in {"LONG_CONTEXT", "SHORT_CONTEXT"}' in src


# --------------------------------------------------------------------------- #
# Viewer JS / HTML / CSS static regressions (clean mode)
# --------------------------------------------------------------------------- #


def test_viewer_js_renders_uncertainty_as_hatched_regions_only():
    src = APP_JS.read_text(encoding="utf-8")
    assert "drawUncertaintySegments" in src
    assert "state.uncertainty" in src
    assert "lifecycle_uncertainty_segments.json" in src
    assert "cache: \"no-store\"" in src
    # Clean mode: no vertical marker spam, no chart text labels on regions.
    assert "drawUncertaintyMarkers" not in src
    assert "AUCTION NEUTRALIZATION" not in src
    assert "fillText(String(segment.label" not in src
    assert "pinnedRow" not in src
    assert "renderInspector" not in src


def test_viewer_js_compact_hover_only():
    src = APP_JS.read_text(encoding="utf-8")
    assert "updateHover" in src
    assert "active_market_context" in src
    assert "lifecycle_state" in src
    # Bulky multi-field inspector card must not be the default clean hover.
    assert "inspectorField" not in src
    assert "auction_episode_status" not in src


def test_generator_candle_rows_carry_inspector_fields():
    src = GEN_PATH.read_text(encoding="utf-8")
    for field in (
        '"raw_context_status"',
        '"auction_episode"',
        '"auction_episode_status"',
        '"cognitive_market_state"',
        '"cognitive_state_status"',
    ):
        assert field in src, f"candle rows must include {field}"


def test_viewer_legend_is_compact_clean():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "Green = active long context" in html
    assert "Red = active short context" in html
    assert "Faded = uncertain / challenged" in html
    assert "No fill = observe" in html
    # Clean legend must not advertise neutralization / candidate sub-types.
    assert "Auction Neutralization" not in html
    assert "Candidate Long" not in html


def test_viewer_css_clean_no_marker_legend():
    css = LIFECYCLE_CSS.read_text(encoding="utf-8")
    assert ".swatch.long" in css
    assert ".swatch.short" in css
    assert ".swatch.faded" in css
    assert ".swatch.observe" in css
    assert ".swatch.neutralization" not in css
    assert ".lifecycle-inspector-row" not in css


def test_clean_mode_hatch_mapping_in_js():
    src = APP_JS.read_text(encoding="utf-8")
    assert "uncertaintyHatchColor" in src
    assert 'direction === "LONG_CONTEXT"' in src
    assert 'direction === "SHORT_CONTEXT"' in src
    assert 'type !== "CANDIDATE" && type !== "CHALLENGED"' in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
