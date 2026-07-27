"""VIS3C — historical TF context + trade isolation + stable TF_N ordinals."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "context_visualizer"))
sys.path.insert(0, str(ROOT / "src"))

from timeframe_chart_truth import (  # noqa: E402
    TIMEFRAMES,
    assert_entities_tf_isolated,
    assign_tf_ordinals,
    build_tf_context_segments,
    build_timeframe_chart_truth,
)


@pytest.fixture(scope="module")
def truth():
    return build_timeframe_chart_truth(window_days=7)


def test_schema_and_visual_contract(truth):
    assert truth["schema_version"] == "timeframe_chart_truth_v3"
    assert truth["visual_contract"]["global_lifecycle_strip"] is False
    assert truth["visual_contract"]["per_tf_context_bands"] is True
    assert truth["visual_contract"]["standalone_tf_urls"] is True
    assert truth["visual_contract"]["trade_public_numbers"] is True
    assert truth["visual_contract"]["equal_grid"] is False
    assert truth["runtime"]["paper_only"] is True
    assert truth["runtime"]["execution_enabled"] is False


def test_context_segments_historical_per_tf_isolated(truth):
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        segs = block.get("context_segments") or []
        hist = block.get("context_history") or []
        assert segs == hist
        assert len(segs) >= 1, f"{tf} must have historical context segments"
        assert block.get("context_source") == "timeframe_command_memory"
        for seg in segs:
            assert seg["timeframe"] == tf
            assert seg.get("start_timestamp")
            assert seg.get("end_timestamp")
            assert seg.get("directional_state")
            assert seg.get("source") == "timeframe_command_memory"
        # Canonical memory has multiple transitions for active TFs
        if tf in ("M15", "M30", "H1"):
            assert len(segs) > 1, f"{tf} historical segment count must be > 1"


def test_context_builder_rejects_cross_tf():
    m15 = build_tf_context_segments("M15")
    m30 = build_tf_context_segments("M30")
    assert m15 and m30
    assert all(s["timeframe"] == "M15" for s in m15)
    assert all(s["timeframe"] == "M30" for s in m30)


def test_trade_isolation_zero_foreign(truth):
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        assert block.get("panel_status") == "OK"
        assert block.get("contamination") == []
        entities = (block.get("closed_trades") or []) + (block.get("open_positions") or [])
        foreign = [e for e in entities if e.get("timeframe") != tf]
        assert foreign == [], f"{tf} foreign entities: {foreign}"
        for entity in entities:
            assert entity["timeframe"] == tf
            assert entity.get("status") in {"CLOSED", "OPEN"}
            if entity["status"] == "OPEN":
                assert entity.get("exit_timestamp") is None
                assert entity.get("exit_price") is None


def test_public_ordinals_stable_and_deterministic(truth):
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        entities = (block.get("closed_trades") or []) + (block.get("open_positions") or [])
        if not entities:
            continue
        numbers = [e["public_number"] for e in entities]
        assert numbers[0] == f"{tf}_1" or f"{tf}_1" in numbers
        # First by sort key must be TF_1
        ordered = sorted(
            entities,
            key=lambda e: (
                e.get("entry_timestamp") or "",
                e.get("created_at") or e.get("entry_timestamp") or "",
                e.get("trade_id") or e.get("position_id") or "",
            ),
        )
        assert ordered[0]["public_number"] == f"{tf}_1"
        assert ordered[0]["ordinal"] == 1
        assert ordered[0]["display_label"] == f"{tf}_1"
        for e in entities:
            assert e["public_number"] == e["display_label"]
            assert e["public_number"].startswith(f"{tf}_")
            assert re_match_tf_n(e["public_number"], tf)
        # Rebuild ordinals — must be identical (deterministic)
        closed = [dict(e) for e in (block.get("closed_trades") or [])]
        opens = [dict(e) for e in (block.get("open_positions") or [])]
        for e in closed + opens:
            e["public_number"] = None
            e["ordinal"] = None
            e["display_label"] = None
        assign_tf_ordinals(tf, closed_trades=closed, open_positions=opens)
        rebuilt = {
            (e.get("trade_id") or e.get("position_id")): e["public_number"]
            for e in closed + opens
        }
        original = {
            (e.get("trade_id") or e.get("position_id")): e["public_number"]
            for e in entities
        }
        assert rebuilt == original


def re_match_tf_n(label: str, tf: str) -> bool:
    import re

    return bool(re.fullmatch(rf"{re.escape(tf)}_\d+", label))


def test_assert_entities_detects_contamination():
    bad = assert_entities_tf_isolated(
        [{"timeframe": "H1", "trade_id": "x"}],
        timeframe="M15",
    )
    assert len(bad) == 1
    assert bad[0]["timeframe_expected"] == "M15"


def test_global_lifecycle_payload_only_not_required_for_bands(truth):
    assert "global_lifecycle" in truth
    assert truth["visual_contract"]["global_lifecycle_strip"] is False
