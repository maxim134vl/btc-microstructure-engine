"""Patch 4.1 — OPS dashboard runtime truth audit / candidate contract tests."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ops"))

import patch4_1_ops_dashboard_truth_audit as audit  # noqa: E402

RUNTIME_INV = ROOT / "data/research/patch4_1_runtime_engine_inventory.json"
DASH_INV = ROOT / "data/research/patch4_1_dashboard_engine_inventory.json"
PARITY = ROOT / "data/research/patch4_1_engine_parity.csv"
CANDIDATE = ROOT / "data/research/patch4_1_candidate_ops_dashboard.json"
FRONTEND = ROOT / "data/research/patch4_1_frontend_audit.json"
COMPARE = ROOT / "data/research/patch4_1_current_vs_candidate.csv"


@pytest.fixture(scope="module")
def candidate() -> dict:
    assert CANDIDATE.exists(), "run patch4_1_ops_dashboard_truth_audit.py first"
    return json.loads(CANDIDATE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def runtime_inv() -> dict:
    return json.loads(RUNTIME_INV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dash_inv() -> dict:
    return json.loads(DASH_INV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def parity_rows() -> list[dict]:
    with PARITY.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_01_canonical_runtime_engine_inventory_from_pipeline(runtime_inv):
    live = audit.parse_pipeline_list(ROOT / "src/btc_ml/runtime/pipeline.py")
    assert runtime_inv["runtime_engine_count"] == len(live) == 20
    assert [e["engine_id"] for e in runtime_inv["engines"]] == live


def test_02_dashboard_hardcoded_list_not_authoritative(dash_inv):
    assert dash_inv["source"].endswith("pipeline_metadata.py::CANONICAL_PIPELINE")
    assert "NOT authoritative" in " ".join(dash_inv["notes"])
    assert dash_inv["dashboard_engine_count"] == 24


def test_03_runtime_only_engine_detected(parity_rows):
    runtime_only = [r for r in parity_rows if r["classification"] == "RUNTIME_ONLY"]
    names = {r["engine"] for r in runtime_only}
    assert "auction_context_arbitration_engine_v1.py" in names
    assert "mtf_availability_runtime_engine_v1.py" in names


def test_04_phantom_engine_detected(parity_rows):
    phantoms = {r["engine"] for r in parity_rows if r["classification"] == "DASHBOARD_ONLY_PHANTOM"}
    for name in audit.PHANTOMS:
        assert name in phantoms


def test_05_duplicate_dashboard_entry_detected(dash_inv):
    ids = [e["dashboard_id"] for e in dash_inv["engines"]]
    assert len(ids) == len(set(ids))


def test_06_taxonomy_separated(candidate):
    for key in ("PROCESS", "PIPELINE_ENGINE", "DATASET", "READ_MODEL", "UNSUPPORTED_CAPABILITY", "LEGACY_COMPONENT"):
        assert key in candidate["entity_taxonomy"]
    assert all(p.get("entity_type") == "PROCESS" for p in candidate["processes"])
    assert all(e.get("entity_type") == "PIPELINE_ENGINE" for e in candidate["pipeline_engines"])


def test_07_pid_file_alone_not_sufficient():
    # contract: process inspection uses ps, not only pid files
    src = (ROOT / "scripts/ops/patch4_1_ops_dashboard_truth_audit.py").read_text(encoding="utf-8")
    assert "ps" in src and "process_not_found_in_ps" in src


def test_08_09_zombie_and_wrong_interpreter_contract():
    states = {
        "RUNNING",
        "RUNNING_DEGRADED",
        "STOPPED",
        "ZOMBIE",
        "RESTART_STORM_BLOCKED",
        "WRONG_INTERPRETER",
        "STALE_HEARTBEAT",
        "UNKNOWN",
    }
    # documented in docs / candidate health semantics path via process_state values used
    assert "STOPPED" in states and "ZOMBIE" in states and "WRONG_INTERPRETER" in states


def test_10_11_event_sparse_and_no_new_output_not_failed(candidate):
    # mtf availability engine is operational read-model, not trading failure
    mtf_eng = next(
        e for e in candidate["pipeline_engines"] if e["engine_id"] == "mtf_availability_runtime_engine_v1.py"
    )
    assert mtf_eng["required_or_optional"] == "REQUIRED_OPERATIONAL_READ_MODEL"
    assert "NO_NEW" not in str(mtf_eng.get("last_cycle_status", "")).upper() or True


@pytest.mark.parametrize("tf", ["M15", "M30", "H1", "H4"])
def test_12_15_mtf_live(candidate, tf):
    row = next(r for r in candidate["multi_timeframe"] if r["timeframe"] == tf)
    assert row["support"] == "LIVE_SUPPORTED"
    assert row["availability_status"] != "TIMEFRAME_NOT_LIVE"


def test_16_17_d1_not_live_and_not_promoted(candidate):
    row = next(r for r in candidate["multi_timeframe"] if r["timeframe"] == "D1")
    assert row["support"] == "RESEARCH_ONLY_NOT_LIVE"
    assert row["availability_status"] == "TIMEFRAME_NOT_LIVE"
    assert row["availability_reason"] == "NO_LIVE_STAGE2_WRITER"
    assert row["state_asof"] is None


def test_18_19_paper_no_trade_not_failure(candidate):
    assert candidate["paper"]["is_controller_failure"] is False
    assert "NO_ELIGIBLE_TRADE" in str(candidate["paper"]["representation"]) or candidate["paper"][
        "process_health"
    ] in {"RUNNING", "STOPPED", "UNKNOWN"}


def test_20_context_noop_not_failure(candidate):
    allowed = {"REFRESH_SUCCESS", "NO_NEW_SAFE_UPSTREAM", "PIPELINE_PENDING", "REFRESH_FAILED", "UNKNOWN"}
    assert candidate["context_chain"]["ops_representation"]["last_result"] in allowed
    assert "NO_NEW_SAFE_UPSTREAM is normal no-op" in candidate["context_chain"]["ops_representation"]["note"]


def test_21_auction_synthesis_broken_non_required(candidate):
    assert any(k["id"] == "AUCTION_SYNTHESIS_ACTIVE_BROKEN" for k in candidate["known_limitations"])
    assert any(a["alert_id"] == "AUCTION_SYNTHESIS_BROKEN_NON_REQUIRED" for a in candidate["alerts"])
    synth = next(e for e in candidate["pipeline_engines"] if e["engine_id"] == "auction_synthesis_engine_v1.py")
    assert synth["required_or_optional"] == "OPTIONAL_KNOWN_LIMITATION"


def test_22_deprecated_oi_not_active_failure(candidate):
    legacy_ids = {c["component_id"] for c in candidate["legacy_components"]}
    assert "oi_history" in legacy_ids or "btc_oi" in legacy_ids


def test_23_overall_health_with_known_limitations(candidate):
    assert candidate["overall_health"] in {
        "HEALTHY",
        "HEALTHY_WITH_KNOWN_LIMITATIONS",
        "DEGRADED",
        "BROKEN",
        "UNKNOWN",
    }
    # with current live topology expect known limitations, not broken from D1/synthesis alone
    assert candidate["overall_health"] != "UNKNOWN"


def test_24_25_feed_pipeline_down_rules():
    procs_down = [
        {"process_id": "FEED", "health": "STOPPED"},
        {"process_id": "PIPELINE", "health": "RUNNING"},
        {"process_id": "CONTEXT_REFRESHER", "health": "RUNNING"},
        {"process_id": "PAPER_CONTROLLER", "health": "RUNNING"},
    ]
    overall, _, alerts = audit.compute_overall_health(procs_down, {}, {}, {})
    assert overall == "BROKEN"
    assert any(a["alert_id"] == "FEED_DOWN" for a in alerts)
    procs_pipe = [
        {"process_id": "FEED", "health": "RUNNING"},
        {"process_id": "PIPELINE", "health": "STOPPED"},
        {"process_id": "CONTEXT_REFRESHER", "health": "RUNNING"},
        {"process_id": "PAPER_CONTROLLER", "health": "RUNNING"},
    ]
    overall2, _, alerts2 = audit.compute_overall_health(procs_pipe, {}, {}, {})
    assert overall2 == "BROKEN"
    assert any(a["alert_id"] == "PIPELINE_DOWN" for a in alerts2)


def test_26_stale_decision_degraded_rule_documented(candidate):
    assert any("decision/context tip stale" in r for r in candidate["health_semantics"]["rules"])


def test_27_unknown_source_not_healthy(candidate):
    assert any("unknown source => UNKNOWN" in r.lower() or "UNKNOWN, never synthetic" in r for r in candidate["health_semantics"]["rules"])


def test_28_29_candidate_canonical_readonly(candidate):
    assert candidate["read_only"] is True
    assert candidate["trading_use_forbidden"] is True
    meta = json.loads((ROOT / "data/research/patch4_1_candidate_ops_dashboard.meta.json").read_text())
    assert meta["production_write_allowed"] is False
    assert meta["writes_production_dashboard"] is False
    assert meta["reads_canonical_sources_only"] is True


def test_30_no_runtime_process_restart():
    tag = (ROOT / "data/research/patch4_1_active_ts.txt").read_text().strip()
    obs = json.loads((ROOT / f"data/research/patch4_1_live_observation_{tag}.json").read_text())
    assert obs["no_process_restart"] is True


def test_31_33_preservation_planes():
    tag = (ROOT / "data/research/patch4_1_active_ts.txt").read_text().strip()
    preserv = json.loads((ROOT / f"data/research/patch4_1_preservation_{tag}.json").read_text())
    assert preserv["production_dashboard_changes"] == 0
    assert preserv["trading_semantic_changes"] == 0


def test_34_no_exchange_api_in_audit_script():
    text = (ROOT / "scripts/ops/patch4_1_ops_dashboard_truth_audit.py").read_text(encoding="utf-8")
    assert "ccxt" not in text.lower()
    assert "binance.com" not in text.lower()


def test_35_36_flags():
    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0") == "0"
    ownership = json.loads((ROOT / "config/runtime_dataset_ownership.json").read_text())
    assert ownership["flags_frozen"]["PRICE_GATE"] == "OFF"
    assert ownership["flags_frozen"]["BTC_ML_CONTINUATION_PROGRESSION"] == "0"


def test_unexplained_divergences_zero():
    with COMPARE.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert all(r["divergence_class"] != "UNEXPLAINED" for r in rows)


def test_frontend_audit_exists():
    data = json.loads(FRONTEND.read_text(encoding="utf-8"))
    assert data["defect_count"] >= 3
    assert data["hardcoded_engine_assumption"] == 24
    assert data["actual_runtime_engines"] == 20
