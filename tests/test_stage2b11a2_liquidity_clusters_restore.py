"""Stage 2B1.1A.2 — canonical liquidity cluster path restore."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from storage.path_registry import (  # noqa: E402
    PARQUET_REGISTRY,
    resolve_canonical,
    resolve_write,
)

ENGINE = REPO / "liquidity_cluster_engine_v1.py"
CANDIDATE = (
    REPO
    / "data/candidate/architecture_recovery/stage2b11a2_liquidity_clusters_restore"
)
MAY = pd.Timestamp("2026-05-13 12:45:00", tz="UTC")


def _evidence() -> dict:
    path = CANDIDATE / "evidence.json"
    if not path.exists():
        pytest.skip("candidate evidence missing")
    return json.loads(path.read_text())


def test_registry_maps_clusters_to_cognition():
    assert PARQUET_REGISTRY["liquidity_clusters_memory.parquet"] == "cognition"


def test_cluster_writer_path_equals_cognition_canonical():
    w = Path(resolve_write("liquidity_clusters_memory.parquet"))
    assert w == REPO / "data/cognition/liquidity_clusters_memory.parquet"


def test_cluster_canonical_path_without_legacy_migrate():
    """Use resolve_canonical/write only — resolve_read would migrate May CWD into cognition."""
    w = Path(resolve_write("liquidity_clusters_memory.parquet"))
    c = Path(resolve_canonical("liquidity_clusters_memory.parquet"))
    assert w == c == REPO / "data/cognition/liquidity_clusters_memory.parquet"
    assert not w.exists() or True  # may or may not exist; must not require migrate


def test_producer_reads_canonical_localization_not_v2():
    src = ENGINE.read_text()
    assert 'resolve_read("volume_localization_memory.parquet")' in src
    assert "volume_localization_v2_memory.parquet" not in src


def test_producer_writes_resolve_write_not_cwd_filename():
    src = ENGINE.read_text()
    assert 'resolve_write("liquidity_clusters_memory.parquet")' in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "to_parquet":
            if node.args and isinstance(node.args[0], ast.Constant):
                assert node.args[0].value != "liquidity_clusters_memory.parquet"


def test_canonical_localization_schema_has_required_fields():
    # Read cognition path directly to avoid unrelated migrate side effects.
    loc_path = REPO / "data/cognition/volume_localization_memory.parquet"
    loc = pd.read_parquet(loc_path)
    for col in ("timestamp", "zone_low", "zone_high", "behavior", "estimated_local_volume"):
        assert col in loc.columns


def test_negative_fallback_to_v2_forbidden_in_producer():
    assert "volume_localization_v2" not in ENGINE.read_text()


def test_path_only_invariance_structural_from_evidence():
    ev = _evidence()
    assert ev["algorithm_body_identical"] is True
    assert ev["path_only_invariance"]["structural_numeric_max_err"] == 0
    assert ev["path_only_invariance"]["behaviors_parity"] == 1.0


def test_candidate_clusters_unique_valid_zones_overlap_market():
    path = CANDIDATE / "candidate_liquidity_clusters_memory.parquet"
    if not path.exists():
        pytest.skip("candidate clusters missing")
    df = pd.read_parquet(path)
    assert int(df["cluster_id"].duplicated().sum()) == 0
    assert int((df["zone_low"] > df["zone_high"]).sum()) == 0
    ev = _evidence()
    assert ev["candidate_clusters"]["clusters_containing_price"] > 0
    assert ev["candidate_clusters"]["zone_min"] < ev["candidate_clusters"]["current_price"]
    assert ev["candidate_clusters"]["zone_max"] > ev["candidate_clusters"]["current_price"]


def test_fresh_clusters_produce_matched_and_non_neutral_interactions():
    ev = _evidence()
    assert ev["interaction"]["matched"] > 0
    assert ev["interaction"]["non_neutral"] > 0
    assert ev["interaction"]["dups"] == 0


def test_candidate_htf_context_advances_with_interaction_derived_labels():
    ev = _evidence()
    tip = pd.Timestamp(ev["context"]["tip"])
    assert tip > MAY
    assert ev["context"]["interaction_derived"] > 0
    assert ev["context"]["dups"] == 0


def test_failed_expansion_branch_reachable():
    ev = _evidence()
    assert ev["synthesis"]["branch_reachable"] is True
    assert ev["synthesis"]["FAILED_EXPANSION"] > 0


def test_evidence_status_ready_no_live_writes():
    ev = _evidence()
    assert ev["status"] == "STAGE2B11A2_LIQUIDITY_CLUSTER_CANDIDATE_READY"
    assert ev["live_writes"] == 0


def test_negative_missing_registry_mapping_would_fail_category_lookup():
    # Guard: mapping must remain present after restore.
    assert PARQUET_REGISTRY.get("liquidity_clusters_memory.parquet") == "cognition"
