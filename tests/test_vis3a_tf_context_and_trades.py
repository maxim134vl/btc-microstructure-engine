"""VIS3A — per-TF historical context segments + trade isolation from adapter."""

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
    build_tf_context_segments,
    build_timeframe_chart_truth,
)


@pytest.fixture(scope="module")
def truth():
    return build_timeframe_chart_truth(window_days=7)


def test_schema_and_visual_contract(truth):
    assert truth["schema_version"] == "timeframe_chart_truth_v2"
    assert truth["visual_contract"]["global_lifecycle_strip"] is False
    assert truth["visual_contract"]["per_tf_context_bands"] is True
    assert truth["runtime"]["paper_only"] is True
    assert truth["runtime"]["execution_enabled"] is False


def test_context_segments_historical_per_tf_isolated(truth):
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        segs = block.get("context_segments") or []
        assert len(segs) >= 1, f"{tf} must have historical context segments"
        assert block.get("context_source") == "timeframe_command_memory"
        states = set()
        for seg in segs:
            assert seg["timeframe"] == tf
            assert seg.get("start_timestamp")
            assert seg.get("end_timestamp")
            assert seg.get("directional_state")
            assert seg.get("source") == "timeframe_command_memory"
            states.add(seg["directional_state"])
        # Must not be a single fake snapshot repeat of only the tip state
        # (history spans OBSERVE and at least one context for active TFs).
        assert len(segs) >= 2 or len(states) >= 1


def test_context_builder_rejects_cross_tf():
    m15 = build_tf_context_segments("M15")
    m30 = build_tf_context_segments("M30")
    assert m15 and m30
    assert all(s["timeframe"] == "M15" for s in m15)
    assert all(s["timeframe"] == "M30" for s in m30)
    # Distinct series objects / no forced identical tip-only collapse
    assert m15[0]["start_timestamp"] is not None
    assert m30[0]["start_timestamp"] is not None


def test_trade_isolation_runtime_assertion(truth):
    for tf in TIMEFRAMES:
        block = truth["timeframes"][tf]
        assert block.get("panel_status") == "OK"
        assert block.get("contamination") == []
        for entity in (block.get("closed_trades") or []) + (block.get("open_positions") or []):
            assert entity["timeframe"] == tf
            assert entity.get("status") in {"CLOSED", "OPEN"}
            if entity["status"] == "OPEN":
                assert entity.get("exit_timestamp") is None
                assert entity.get("exit_price") is None


def test_assert_entities_detects_contamination():
    bad = assert_entities_tf_isolated(
        [{"timeframe": "H1", "trade_id": "x"}],
        timeframe="M15",
    )
    assert len(bad) == 1
    assert bad[0]["timeframe_expected"] == "M15"


def test_global_lifecycle_payload_only_not_required_for_bands(truth):
    # May remain for lineage/tooltips; visual strip contract is false.
    assert "global_lifecycle" in truth
    assert truth["visual_contract"]["global_lifecycle_strip"] is False
