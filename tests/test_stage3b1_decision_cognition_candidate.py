"""Stage 3B1 — decision cognition bridge candidate (event memory vs evaluation snapshot)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

import stage2_cognition_runtime_v1 as stage2


def _mtf_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-07-25 08:45:00", tz="UTC"),
                "synthesis_state": "INTERMEDIATE_REVERSAL",
                "trigger_event": "STOPPING_VOLUME",
                "persistence": "M30_CONFIRMED",
                "persistence_score": 0.5,
                "structural_rank": "MEDIUM",
                "alignment_score": 0.5,
                "location_bias": "LOWER_ABSORPTION",
            }
        ]
    )


def _candles(*ts: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"timestamp": [pd.Timestamp(t, tz="UTC") for t in ts]}
    )


def _auction(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp(ts, tz="UTC"),
                "auction_state": state,
                "interpretation": state,
            }
            for ts, state in rows
        ]
    )


def test_export_does_not_fabricate_mtf_events():
    mtf = _mtf_frame()
    out = stage2.export_runtime_cognition_memory(
        mtf,
        candle_structure=_candles(
            "2026-07-26 18:45:00",
            "2026-07-26 19:00:00",
        ),
        auction_synthesis=_auction([("2026-07-26 18:50:00", "NEUTRAL")]),
    )
    # Two evaluation rows, one underlying MTF event.
    assert len(out) == 2
    assert out["timestamp"].nunique() == 1  # temporarily event time before finalize
    assert set(out["evaluation_timestamp"]) == {
        pd.Timestamp("2026-07-26 18:45:00", tz="UTC"),
        pd.Timestamp("2026-07-26 19:00:00", tz="UTC"),
    }


def test_runtime_evaluation_advances_without_new_climax_or_auction_row():
    mtf = _mtf_frame()
    auction = _auction([("2026-07-26 17:00:00", "STRUCTURAL_COMPRESSION")])
    out = stage2.export_runtime_cognition_memory(
        mtf,
        candle_structure=_candles(
            "2026-07-26 18:30:00",
            "2026-07-26 18:45:00",
            "2026-07-26 19:00:00",
        ),
        auction_synthesis=auction,
    )
    ev = pd.to_datetime(out["evaluation_timestamp"], utc=True)
    assert list(ev) == [
        pd.Timestamp("2026-07-26 18:30:00", tz="UTC"),
        pd.Timestamp("2026-07-26 18:45:00", tz="UTC"),
        pd.Timestamp("2026-07-26 19:00:00", tz="UTC"),
    ]
    assert out["auction_state"].nunique() == 1
    assert out["auction_state"].iloc[0] == "STRUCTURAL_COMPRESSION"
    assert out["timestamp"].nunique() == 1


def test_auction_state_transition_consumed():
    mtf = _mtf_frame()
    auction = _auction(
        [
            ("2026-07-26 17:00:00", "BALANCED_DISTRIBUTION"),
            ("2026-07-26 18:00:00", "NEUTRAL"),
        ]
    )
    out = stage2.export_runtime_cognition_memory(
        mtf,
        candle_structure=_candles(
            "2026-07-26 17:30:00",
            "2026-07-26 18:30:00",
        ),
        auction_synthesis=auction,
    )
    assert list(out["auction_state"]) == ["BALANCED_DISTRIBUTION", "NEUTRAL"]


def test_missing_auction_does_not_invent_state():
    mtf = _mtf_frame()
    out = stage2.export_runtime_cognition_memory(
        mtf,
        candle_structure=_candles("2026-07-26 19:00:00"),
        auction_synthesis=pd.DataFrame(),
    )
    assert len(out) == 1
    assert pd.isna(out.iloc[0]["auction_state"])


def test_missing_mtf_does_not_invent_state():
    out = stage2.export_runtime_cognition_memory(
        pd.DataFrame(),
        candle_structure=_candles("2026-07-26 19:00:00"),
        auction_synthesis=_auction([("2026-07-26 18:00:00", "NEUTRAL")]),
    )
    assert len(out) == 0


def test_event_timestamp_not_overwritten_after_lineage_finalize():
    from runtime_lineage import apply_lineage_metadata

    mtf = _mtf_frame()
    raw = stage2.export_runtime_cognition_memory(
        mtf,
        candle_structure=_candles("2026-07-26 19:00:00"),
        auction_synthesis=_auction([("2026-07-26 19:10:00", "NEUTRAL")]),
    )
    evaluation = raw["evaluation_timestamp"].copy()
    domain = raw.drop(columns=["evaluation_timestamp"])
    domain = apply_lineage_metadata(
        domain,
        engine_name=stage2.STAGE2_ENGINE,
        source_parquet=stage2.SYNTHESIS_OUTPUT_PATH,
        dependency_chain=["candle", "auction", "stage2"],
        event_timestamp_col="timestamp",
    )
    domain["timestamp"] = pd.to_datetime(evaluation, utc=True).to_numpy()
    eval_ts = pd.to_datetime(domain.iloc[0]["timestamp"], utc=True)
    event_ts = pd.to_datetime(domain.iloc[0]["lineage_event_timestamp"], utc=True)
    assert eval_ts == pd.Timestamp("2026-07-26 19:00:00", tz="UTC")
    assert event_ts == pd.Timestamp("2026-07-25 08:45:00", tz="UTC")


def test_duplicate_evaluation_timestamps_collapsed():
    mtf = _mtf_frame()
    out = stage2.export_runtime_cognition_memory(
        mtf,
        candle_structure=_candles(
            "2026-07-26 19:00:00",
            "2026-07-26 19:00:00",
        ),
        auction_synthesis=_auction([("2026-07-26 18:00:00", "NEUTRAL")]),
    )
    assert len(out) == 1


def test_stage2_dependencies_include_auction_and_candle():
    from runtime_dependency_map import DEPENDENCIES

    deps = DEPENDENCIES["stage2_cognition_runtime_v1.py"]
    assert "candle_structure_memory.parquet" in deps
    assert "auction_synthesis_memory.parquet" in deps


def test_runtime_cognition_dependencies_include_mtf_memory():
    from runtime_dependency_map import DEPENDENCIES

    deps = DEPENDENCIES["runtime_cognition_engine_v1.py"]
    assert "runtime_cognition_memory.parquet" in deps
    assert "multi_timeframe_synthesis.parquet" in deps


def test_candidate_evidence_exists():
    root = Path("data/candidate/architecture_recovery/stage3b1_decision_cognition_candidate")
    assert (root / "scenario_b_decision_bridge.json").exists()
    assert (root / "frozen_input_manifest.json").exists()
