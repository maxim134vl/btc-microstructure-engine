"""Chart paints only LONG_CONTEXT / SHORT_CONTEXT / OBSERVE."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps" / "context_visualizer" / "public"
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))

from timeframe_chart_truth import (  # noqa: E402
    CANONICAL_VISUAL_CONTEXTS,
    canonicalize_visual_context,
    fill_observe_context_zones,
)


def test_canonicalize_dumps_legacy_labels() -> None:
    assert canonicalize_visual_context("LONG") == "LONG_CONTEXT"
    assert canonicalize_visual_context("SHORT_CONTEXT") == "SHORT_CONTEXT"
    assert canonicalize_visual_context("OBSERVE") == "OBSERVE"
    for raw in (
        "STAND_ASIDE",
        "NONE",
        "NO_ACTIVE_CONTEXT",
        "NEUTRAL",
        "CHALLENGED",
        "DEVELOPING",
        "CANDIDATE",
        "BULLISH",
        "BEARISH",
        "ACCUMULATION",
    ):
        assert canonicalize_visual_context(raw) == "OBSERVE"
    assert CANONICAL_VISUAL_CONTEXTS == {"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"}


def test_observe_gaps_fill_between_directional_zones() -> None:
    zones = [
        {
            "timeframe": "M15",
            "direction": "LONG",
            "directional_state": "LONG_CONTEXT",
            "start_timestamp": "2026-09-10T10:00:00Z",
            "end_timestamp": "2026-09-10T11:00:00Z",
            "active": False,
        },
        {
            "timeframe": "M15",
            "direction": "SHORT",
            "directional_state": "SHORT_CONTEXT",
            "start_timestamp": "2026-09-10T12:00:00Z",
            "end_timestamp": "2026-09-10T13:00:00Z",
            "active": False,
        },
    ]
    out = fill_observe_context_zones(
        zones,
        timeframe="M15",
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-10T14:00:00Z",
        tip_context="OBSERVE",
    )
    states = [z["directional_state"] for z in out]
    assert states == [
        "OBSERVE",
        "LONG_CONTEXT",
        "OBSERVE",
        "SHORT_CONTEXT",
        "OBSERVE",
    ]
    assert out[0]["active"] is False
    assert out[-1]["active"] is True
    assert out[-1]["end_timestamp"] is None


def test_no_trailing_observe_when_tip_is_live_long() -> None:
    zones = [
        {
            "timeframe": "H4",
            "direction": "LONG",
            "directional_state": "LONG_CONTEXT",
            "start_timestamp": "2026-09-11T08:00:00Z",
            "end_timestamp": None,
            "active": True,
        }
    ]
    out = fill_observe_context_zones(
        zones,
        timeframe="H4",
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-11T12:00:00Z",
        tip_context="LONG_CONTEXT",
    )
    assert [z["directional_state"] for z in out] == ["OBSERVE", "LONG_CONTEXT"]
    assert out[-1]["active"] is True
    assert not any(z["directional_state"] == "OBSERVE" and z.get("active") for z in out)


def test_observe_gaps_ignore_timezone_suffix_mismatch() -> None:
    zones = [
        {
            "timeframe": "M15",
            "direction": "LONG",
            "directional_state": "LONG_CONTEXT",
            "start_timestamp": "2026-09-10T10:00:00+00:00",
            "end_timestamp": "2026-09-10T11:00:00+00:00",
            "active": False,
        }
    ]
    out = fill_observe_context_zones(
        zones,
        timeframe="M15",
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-10T12:00:00Z",
        tip_context="OBSERVE",
    )
    assert [z["directional_state"] for z in out] == [
        "OBSERVE",
        "LONG_CONTEXT",
        "OBSERVE",
    ]


def test_js_paints_only_canonical_contexts() -> None:
    js = (PUBLIC / "lifecycle_app.js").read_text(encoding="utf-8")
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    stub = (PUBLIC / "legacy_app.js").read_text(encoding="utf-8")
    debug = (PUBLIC / "debug.html").read_text(encoding="utf-8")
    assert "function canonicalVisualContext" in js
    assert 'vis === "LONG_CONTEXT"' in js
    assert 'vis === "SHORT_CONTEXT"' in js
    assert "observeZone" in js
    assert 'fillText("CHALLENGED"' not in js
    assert "if (name.includes(\"OBSERVE\")" not in js
    assert "canonical-lso-2" in html
    assert "archived" in stub.lower()
    assert "legacy_app.js" not in debug or "archived" in debug
    assert "<script src=\"./legacy_app.js\">" not in debug
    assert "context_segments" in js
    assert "tfBlock.context_history" not in js.split("function contextBandSegments")[1].split("function drawContextBands")[0]


def test_legacy_app_is_archived() -> None:
    archived = ROOT / "apps" / "context_visualizer" / "archive" / "legacy_app.js"
    assert archived.is_file()
    text = archived.read_text(encoding="utf-8")
    assert "ARCHIVED 2026-09-11" in text
    assert "BULLISH" in text
    assert "Do not restore" in text or "Do not load" in text
