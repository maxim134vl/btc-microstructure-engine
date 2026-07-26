"""Stage 2B1.1B — integrated 26-step synthesis-input candidate (not live)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from btc_ml.runtime import pipeline as pipeline_mod  # noqa: E402
from runtime_hardening import (  # noqa: E402
    ACTIVATED_PIPELINE_STEP_COUNT,
    BASE_CANONICAL_PIPELINE_ORDER,
    BASE_PIPELINE_STEP_COUNT,
    STAGE2_INTEGRATED_PIPELINE_STEP_COUNT,
    STAGE2_SYNTHESIS_INPUT_ENGINES,
    validate_canonical_pipeline_order,
)
from runtime_dependency_map import DEPENDENCIES  # noqa: E402
from storage.path_registry import PARQUET_REGISTRY, resolve_canonical  # noqa: E402

CAND = (
    REPO
    / "data/candidate/architecture_recovery/stage2b11b_integrated_synthesis_candidate"
)
MAY = pd.Timestamp("2026-05-13 12:45:00", tz="UTC")


def _evidence() -> dict:
    path = CAND / "evidence.json"
    if not path.exists():
        pytest.skip("integrated candidate evidence missing")
    return json.loads(path.read_text())


def _candidate() -> list[str]:
    return pipeline_mod.canonical_pipeline_with_stage2_synthesis_inputs_candidate()


def test_default_pipeline_remains_21():
    assert len(pipeline_mod.CANONICAL_PIPELINE) == 21
    assert pipeline_mod.EXPECTED_CANONICAL_PIPELINE_STEP_COUNT == 21
    for eng in STAGE2_SYNTHESIS_INPUT_ENGINES:
        assert eng not in pipeline_mod.CANONICAL_PIPELINE


def test_candidate_pipeline_has_26_unique_stage2_engines():
    cand = _candidate()
    assert len(cand) == 26 == STAGE2_INTEGRATED_PIPELINE_STEP_COUNT
    for eng in STAGE2_SYNTHESIS_INPUT_ENGINES:
        assert cand.count(eng) == 1


def test_hardening_20_21_26_pass():
    assert (
        validate_canonical_pipeline_order(
            list(BASE_CANONICAL_PIPELINE_ORDER), BASE_PIPELINE_STEP_COUNT
        )
        == []
    )
    assert (
        validate_canonical_pipeline_order(
            pipeline_mod.CANONICAL_PIPELINE, ACTIVATED_PIPELINE_STEP_COUNT
        )
        == []
    )
    assert (
        validate_canonical_pipeline_order(_candidate(), STAGE2_INTEGRATED_PIPELINE_STEP_COUNT)
        == []
    )


def test_relative_order_invariants():
    c = _candidate()
    assert c.index("candle_structure_engine_v1.py") < c.index(
        "volume_localization_engine_v1.py"
    )
    assert c.index("volume_localization_engine_v1.py") < c.index(
        "liquidity_cluster_engine_v1.py"
    )
    assert c.index("live_volume_flow_engine_v1.py") < c.index(
        "flow_liquidity_interaction_engine_v3.py"
    )
    assert c.index("liquidity_cluster_engine_v1.py") < c.index(
        "flow_liquidity_interaction_engine_v3.py"
    )
    assert c.index("htf_structure_engine_v1.py") < c.index("htf_ltf_context_engine_v1.py")
    assert c.index("flow_liquidity_interaction_engine_v3.py") < c.index(
        "htf_ltf_context_engine_v1.py"
    )
    assert c.index("htf_ltf_context_engine_v1.py") < c.index(
        "auction_synthesis_engine_v1.py"
    )


def test_negative_missing_flow_fails():
    bad = [e for e in _candidate() if e != "live_volume_flow_engine_v1.py"]
    failures = validate_canonical_pipeline_order(bad, STAGE2_INTEGRATED_PIPELINE_STEP_COUNT)
    assert any("live_volume_flow" in f for f in failures)


def test_negative_missing_cluster_fails():
    bad = [e for e in _candidate() if e != "liquidity_cluster_engine_v1.py"]
    failures = validate_canonical_pipeline_order(bad, STAGE2_INTEGRATED_PIPELINE_STEP_COUNT)
    assert any("liquidity_cluster" in f for f in failures)


def test_negative_interaction_before_flow_fails():
    bad = _candidate()
    i_flow = bad.index("live_volume_flow_engine_v1.py")
    i_inter = bad.index("flow_liquidity_interaction_engine_v3.py")
    bad[i_flow], bad[i_inter] = bad[i_inter], bad[i_flow]
    failures = validate_canonical_pipeline_order(bad, STAGE2_INTEGRATED_PIPELINE_STEP_COUNT)
    assert any("relative order" in f for f in failures)


def test_negative_context_before_htf_structure_fails():
    bad = _candidate()
    i_h = bad.index("htf_structure_engine_v1.py")
    i_c = bad.index("htf_ltf_context_engine_v1.py")
    bad[i_h], bad[i_c] = bad[i_c], bad[i_h]
    failures = validate_canonical_pipeline_order(bad, STAGE2_INTEGRATED_PIPELINE_STEP_COUNT)
    assert any("relative order" in f for f in failures)


def test_negative_synthesis_before_context_fails():
    bad = _candidate()
    i_ctx = bad.index("htf_ltf_context_engine_v1.py")
    i_syn = bad.index("auction_synthesis_engine_v1.py")
    bad[i_ctx], bad[i_syn] = bad[i_syn], bad[i_ctx]
    failures = validate_canonical_pipeline_order(bad, STAGE2_INTEGRATED_PIPELINE_STEP_COUNT)
    assert any("relative order" in f for f in failures)


def test_negative_duplicate_producer_fails():
    bad = _candidate() + ["htf_structure_engine_v1.py"]
    failures = validate_canonical_pipeline_order(bad, len(bad))
    assert any("step count" in f or "duplicat" in f for f in failures)


def test_dependency_map_covers_stage2_producers():
    for eng in STAGE2_SYNTHESIS_INPUT_ENGINES:
        assert eng in DEPENDENCIES
    assert "volume_localization_v2_memory.parquet" not in json.dumps(DEPENDENCIES)
    assert DEPENDENCIES["liquidity_cluster_engine_v1.py"] == [
        "volume_localization_memory.parquet"
    ]


def test_canonical_paths_for_stage2_artifacts():
    assert PARQUET_REGISTRY["live_volume_flow_memory.parquet"] == "cognition"
    assert PARQUET_REGISTRY["liquidity_clusters_memory.parquet"] == "cognition"
    assert PARQUET_REGISTRY["flow_liquidity_interaction_memory.parquet"] == "cognition"
    assert PARQUET_REGISTRY["htf_structure_memory.parquet"] == "diagnostics"
    assert PARQUET_REGISTRY["htf_ltf_context_memory.parquet"] == "diagnostics"
    assert "data/cognition" in resolve_canonical("liquidity_clusters_memory.parquet")


def test_evidence_integrated_behavior_gates():
    ev = _evidence()
    assert ev["status"] == "STAGE2B11B_INTEGRATED_SYNTHESIS_CANDIDATE_READY"
    assert ev["legacy_consumed"] == 0
    assert ev["live_writes"] == 0
    acc = ev["accept"]
    assert pd.Timestamp(acc["flow_tip"]) > MAY
    assert acc["containing_price"] > 0
    assert acc["non_neutral"] > 0
    assert acc["matched"] > 0
    assert pd.Timestamp(acc["htf_tip"]) > MAY
    assert pd.Timestamp(acc["ctx_tip"]) > MAY
    assert acc["derived"] > 0
    assert acc["FAILED_EXPANSION"] > 0
    assert ev["signature"]["cycle2_all_skipped"] is True
    assert ev["signature"]["false_skips"] == 0


def test_candidate_artifacts_under_isolated_root():
    for rel in (
        "cognition/live_volume_flow_memory.parquet",
        "cognition/liquidity_clusters_memory.parquet",
        "cognition/flow_liquidity_interaction_memory.parquet",
        "diagnostics/htf_structure_memory.parquet",
        "diagnostics/htf_ltf_context_memory.parquet",
    ):
        assert (CAND / rel).exists()
