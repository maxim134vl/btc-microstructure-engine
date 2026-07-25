"""Read-only / candidate tests for write-plane consolidation artifacts.

Does not write production memories or alter flags/trading semantics.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

OWNERSHIP = ROOT / "config" / "runtime_dataset_ownership.candidate.json"
OWNERSHIP_MIRROR = ROOT / "data" / "research" / "dataset_ownership_registry.json"
PATH_MAP = ROOT / "data" / "research" / "canonical_path_map.csv"
CONFLICTS = ROOT / "data" / "research" / "write_conflicts.csv"
FRESHNESS = ROOT / "data" / "research" / "runtime_freshness_contract.json"
BELIEF = ROOT / "data" / "research" / "belief_to_paper_lineage.csv"
PARITY = ROOT / "data" / "research" / "engine_registry_parity.csv"
TIP_SNAP = ROOT / "data" / "research" / "runtime_tip_snapshot.json"
EDGE_LAGS = ROOT / "data" / "research" / "runtime_edge_lags.csv"
TRUTH_DOC = ROOT / "docs" / "CANONICAL_RUNTIME_TRUTH_PIPELINE.md"
PLAN_DOC = ROOT / "docs" / "WRITE_PLANE_CONSOLIDATION_PLAN.md"
RUNTIME_PIPELINE = ROOT / "src" / "btc_ml" / "runtime" / "pipeline.py"
DASH_META = ROOT / "dashboard" / "backend" / "app" / "pipeline_metadata.py"


@pytest.fixture(scope="module")
def ownership() -> dict:
    assert OWNERSHIP.exists()
    payload = json.loads(OWNERSHIP.read_text())
    assert payload.get("status") == "CANDIDATE_NOT_ACTIVATED"
    return payload


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_01_one_canonical_writer_per_dataset(ownership: dict) -> None:
    paths = [row["dataset_path"] for row in ownership["datasets"]]
    assert len(paths) == len(set(paths))
    for row in ownership["datasets"]:
        assert row.get("canonical_writer")
        assert row.get("writer_entrypoint")


def test_02_no_unknown_production_writer_in_registry(ownership: dict) -> None:
    allowed_writers = {
        "live_market_feed_writer",
        "canonical_pipeline_loop",
        "market_context_shadow_chain",
        "decision_logger",
        "paper_controller",
        "visual_json_builder",
    }
    for row in ownership["datasets"]:
        assert row["canonical_writer"] in allowed_writers


def test_03_canonical_path_exists_or_none_active() -> None:
    for row in _csv_rows(PATH_MAP):
        path = row["canonical_path"]
        if path == "NONE_ACTIVE":
            continue
        assert (ROOT / path).exists(), path


def test_04_no_production_consumer_reads_research_path_as_canonical(ownership: dict) -> None:
    for row in ownership["datasets"]:
        if row["dataset_path"].startswith("data/research/") and "paper_simulator/paper_" in row[
            "dataset_path"
        ]:
            # paper ledger lives under research by design; must stay paper-owned
            assert row["canonical_writer"] == "paper_controller"
        for consumer in row.get("allowed_consumers") or []:
            assert "candidate_continuation" not in consumer


def test_05_source_timestamp_field_defined_before_evaluated(ownership: dict) -> None:
    for row in ownership["datasets"]:
        assert row.get("source_timestamp_field")
        assert row.get("evaluated_timestamp_field")


def test_06_freshness_budget_defined(ownership: dict) -> None:
    contract = json.loads(FRESHNESS.read_text())
    assert contract["status"] == "CANDIDATE_NOT_ACTIVATED"
    assert contract["links"]
    for row in ownership["datasets"]:
        assert row.get("freshness_budget_seconds") is not None or row.get("semantics") == "event_log"


def test_07_event_sparse_inheritance_has_bounded_age() -> None:
    contract = json.loads(FRESHNESS.read_text())
    mtf = contract["mtf_contract"]
    assert mtf["kind"] == "event_log"
    assert int(mtf["max_inherited_age_seconds"]) == 86400
    assert "asof" in mtf["downstream_availability"]


def test_08_shadow_cannot_overwrite_production_policy_documented() -> None:
    contract = json.loads(FRESHNESS.read_text())
    assert contract["shadow_policy"]["disposition"] == "MERGE_SHARED_BUILDER"
    text = TRUTH_DOC.read_text()
    assert "Older candidate artifact must never replace a newer production tip" in text
    assert "candidates remain suffix-isolated" in text.lower() or "suffix-isolated" in text.lower() or ".candidate_*" in text


def test_09_older_candidate_cannot_replace_newer_tip_rule() -> None:
    plan = PLAN_DOC.read_text()
    assert "no tip rollback" in plan.lower()
    assert "MERGE_SHARED_BUILDER" in plan


def test_10_builder_version_present_in_candidate_schema(ownership: dict) -> None:
    for row in ownership["datasets"]:
        assert row.get("builder_version")


def test_11_dashboard_registry_matches_classification() -> None:
    rows = _csv_rows(PARITY)
    phantoms = [r for r in rows if r["classification"] == "PHANTOM_MISSING_FILE"]
    assert len(phantoms) >= 5
    runtime_text = RUNTIME_PIPELINE.read_text()
    dash_text = DASH_META.read_text()
    assert "EXPECTED_CANONICAL_PIPELINE_STEP_COUNT = 20" in runtime_text
    # Patch 4.2: dashboard mirrors runtime inventory (dynamic len); no hardcoded 24.
    assert "EXPECTED_CANONICAL_PIPELINE_STEP_COUNT" in dash_text
    assert "EXPECTED_CANONICAL_PIPELINE_STEP_COUNT = 24" not in dash_text
    active = [r for r in rows if r["classification"] == "REGISTERED_ACTIVE"]
    assert len(active) >= 15


def test_12_disconnected_fields_classified() -> None:
    rows = _csv_rows(BELIEF)
    classes = {r["classification"] for r in rows}
    assert "DISCONNECTED" in classes
    assert "ACTIVE_GATE" in classes
    disconnected = [r for r in rows if r["classification"] == "DISCONNECTED"]
    assert any(r["field"] == "conviction_probability" for r in disconnected)


def test_13_continuation_remains_off() -> None:
    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0") == "0"
    ownership = json.loads(OWNERSHIP.read_text())
    assert ownership["flags_frozen"]["BTC_ML_CONTINUATION_PROGRESSION"] == "0"
    tip = json.loads(TIP_SNAP.read_text())
    assert tip["flags"]["BTC_ML_CONTINUATION_PROGRESSION"] == "0"


def test_14_price_gate_remains_off() -> None:
    ownership = json.loads(OWNERSHIP.read_text())
    assert ownership["flags_frozen"]["PRICE_GATE"] == "OFF"
    tip = json.loads(TIP_SNAP.read_text())
    assert tip["flags"]["PRICE_GATE"] == "OFF"
    assert tip["flags"]["execution"] == "disabled"


def test_15_no_trading_field_changes_in_candidate_artifacts() -> None:
    """Candidate artifacts are metadata/docs only — no new trading enums/thresholds."""
    plan = PLAN_DOC.read_text()
    assert "No auction/trading semantic changes" in TRUTH_DOC.read_text() or "No auction/trading semantic changes" in plan or "no semantic" in plan.lower()
    assert "READY_FOR_METADATA_PATCH" in plan
    # ownership registry must not invent trading thresholds
    raw = OWNERSHIP.read_text()
    assert "stop_loss" not in raw
    assert "take_profit" not in raw
    assert CONFLICTS.exists() and EDGE_LAGS.exists() and OWNERSHIP_MIRROR.exists()


def test_ownership_mirror_matches_candidate(ownership: dict) -> None:
    mirror = json.loads(OWNERSHIP_MIRROR.read_text())
    assert mirror["status"] == ownership["status"]
    assert len(mirror["datasets"]) == len(ownership["datasets"])
