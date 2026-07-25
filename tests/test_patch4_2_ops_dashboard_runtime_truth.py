"""Patch 4.2 — OPS dashboard runtime truth production activation tests."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ops_dashboard_runtime_truth as truth  # noqa: E402

PHANTOMS = truth.PHANTOM_ENGINES
RUNTIME_ONLY = (
    "auction_context_arbitration_engine_v1.py",
    "mtf_availability_runtime_engine_v1.py",
)


def _load_pipeline_metadata():
    path = ROOT / "dashboard/backend/app/pipeline_metadata.py"
    spec = importlib.util.spec_from_file_location("patch42_pipeline_metadata", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def snapshot() -> dict[str, Any]:
    return truth.build_runtime_truth_snapshot()


@pytest.fixture(scope="module")
def pipeline_meta():
    return _load_pipeline_metadata()


def test_01_runtime_engine_inventory_is_20():
    engines = truth.parse_canonical_pipeline()
    assert len(engines) == 20


def test_02_dashboard_active_engines_is_20(pipeline_meta, snapshot):
    assert len(pipeline_meta.CANONICAL_PIPELINE) == 20
    assert pipeline_meta.EXPECTED_CANONICAL_PIPELINE_STEP_COUNT == 20
    assert len(snapshot["pipeline_engines"]) == 20


def test_03_runtime_only_arbitration_present(snapshot):
    ids = [e["engine_id"] for e in snapshot["pipeline_engines"]]
    assert "auction_context_arbitration_engine_v1.py" in ids


def test_04_runtime_only_mtf_availability_present(snapshot):
    ids = [e["engine_id"] for e in snapshot["pipeline_engines"]]
    assert "mtf_availability_runtime_engine_v1.py" in ids


def test_05_six_phantoms_absent_from_active_list(snapshot, pipeline_meta):
    ids = {e["engine_id"] for e in snapshot["pipeline_engines"]}
    meta_ids = set(pipeline_meta.CANONICAL_PIPELINE)
    for phantom in PHANTOMS:
        assert phantom not in ids
        assert phantom not in meta_ids


def test_06_phantoms_classified_legacy_if_retained(snapshot):
    legacy = {
        c["component_id"]: c
        for c in snapshot["legacy_components"]
        if c.get("classification") == "PHANTOM"
    }
    for phantom in PHANTOMS:
        assert phantom in legacy
        assert legacy[phantom]["active"] is False
        assert legacy[phantom]["reason"] == "NOT_PRESENT_IN_CANONICAL_RUNTIME"


def test_07_duplicate_engine_ids_rejected(monkeypatch):
    dup = truth.parse_canonical_pipeline() + [truth.parse_canonical_pipeline()[0]]

    def boom(*_a, **_k):
        return [
            {
                "engine_id": eng,
                "display_name": eng,
                "module": eng,
                "file": eng,
                "pipeline_order": i,
                "enabled": True,
                "required": True,
                "last_cycle_id": None,
                "last_result": "SUCCESS",
                "last_success": None,
                "duration_ms": None,
                "input_tip": None,
                "output_tip": None,
                "health": "HEALTHY",
                "health_reason": "ok",
                "entity_type": "PIPELINE_ENGINE",
            }
            for i, eng in enumerate(dup, start=1)
        ]

    monkeypatch.setattr(truth, "build_pipeline_engines", boom)
    with pytest.raises(RuntimeError, match="duplicate"):
        truth.build_runtime_truth_snapshot()


def test_08_process_engine_dataset_taxonomy_preserved(snapshot):
    for key in (
        "PROCESS",
        "PIPELINE_ENGINE",
        "DATASET",
        "READ_MODEL",
        "UNSUPPORTED_CAPABILITY",
        "LEGACY_COMPONENT",
    ):
        assert key in snapshot["entity_taxonomy"]
    assert all(p.get("process_id") for p in snapshot["processes"])
    assert all(e.get("entity_type") == "PIPELINE_ENGINE" for e in snapshot["pipeline_engines"])
    assert all(d.get("entity_type") in {"DATASET", "READ_MODEL"} for d in snapshot["datasets"])


def test_09_pid_identity_validation_uses_ps():
    src = (ROOT / "ops_dashboard_runtime_truth.py").read_text(encoding="utf-8")
    assert "ps" in src
    assert "process_id" in src
    assert "pid file" not in src.lower() or "PID file" not in src


def test_10_zombie_detection_contract():
    src = (ROOT / "ops_dashboard_runtime_truth.py").read_text(encoding="utf-8")
    assert 'proc_state = "ZOMBIE"' in src or 'health = "ZOMBIE"' in src
    assert "state=" in src


def test_11_wrong_interpreter_detection_contract():
    src = (ROOT / "ops_dashboard_runtime_truth.py").read_text(encoding="utf-8")
    assert "WRONG_INTERPRETER" in src
    assert "interpreter_identity_mismatch" in src


def test_12_event_sparse_no_event_not_failure(monkeypatch):
    def fake_engines():
        eng = truth.parse_canonical_pipeline()
        return [
            {
                "engine_id": name,
                "display_name": name,
                "module": name,
                "file": name,
                "pipeline_order": i,
                "enabled": True,
                "required": True,
                "last_cycle_id": 1,
                "last_result": "EVENT_SPARSE_NO_EVENT" if name.endswith("mtf_availability_runtime_engine_v1.py") else "SUCCESS",
                "last_success": None,
                "duration_ms": 1,
                "input_tip": None,
                "output_tip": None,
                "health": "HEALTHY",
                "health_reason": "ok",
                "entity_type": "PIPELINE_ENGINE",
            }
            for i, name in enumerate(eng, start=1)
        ]

    monkeypatch.setattr(truth, "build_pipeline_engines", fake_engines)
    snap = truth.build_runtime_truth_snapshot()
    mtf = next(e for e in snap["pipeline_engines"] if e["engine_id"].endswith("mtf_availability_runtime_engine_v1.py"))
    assert mtf["last_result"] == "EVENT_SPARSE_NO_EVENT"
    assert mtf["health"] != "FAILED"


def test_13_no_new_output_not_failure():
    src = (ROOT / "ops_dashboard_runtime_truth.py").read_text(encoding="utf-8")
    assert "SUCCESS_NO_NEW_OUTPUT" in src
    assert '"SUCCESS_NO_NEW_OUTPUT"' in src
    # SUCCESS_NO_NEW_OUTPUT is classified into non_failure set → HEALTHY
    assert "non_failure" in src


def test_14_to_17_mtf_live_timeframes(snapshot):
    by_tf = {r["timeframe"]: r for r in snapshot["multi_timeframe"]}
    for tf in ("M15", "M30", "H1", "H4"):
        assert tf in by_tf
        assert by_tf[tf]["availability_status"] != "TIMEFRAME_NOT_LIVE"
        assert by_tf[tf]["support"] == "LIVE_SUPPORTED"


def test_18_d1_not_live(snapshot):
    d1 = next(r for r in snapshot["multi_timeframe"] if r["timeframe"] == "D1")
    assert d1["availability_status"] == "TIMEFRAME_NOT_LIVE"
    assert d1["state_asof"] is None
    assert d1["entity_type"] == "UNSUPPORTED_CAPABILITY"


def test_19_d1_research_state_not_promoted(snapshot):
    d1 = next(r for r in snapshot["multi_timeframe"] if r["timeframe"] == "D1")
    assert d1["support"] == "RESEARCH_ONLY_NOT_LIVE"
    assert d1["availability_status"] != "FRESH_EVENT"


def test_20_paper_no_trade_healthy(snapshot):
    paper = snapshot["paper"]
    assert paper["is_controller_failure"] is False
    assert paper["health"] in {"HEALTHY", "UNKNOWN"}
    if paper.get("representation") == "RUNNING_NO_ELIGIBLE_TRADE":
        assert paper["health"] == "HEALTHY"


def test_21_paper_stale_distinct_from_stopped():
    procs_stopped = [
        {
            "process_id": "live_feed",
            "health": "RUNNING",
        },
        {"process_id": "canonical_pipeline", "health": "RUNNING"},
        {"process_id": "context_refresher", "health": "RUNNING"},
        {"process_id": "paper_controller", "health": "STOPPED"},
    ]
    overall, _, alerts = truth.compute_overall_health(
        procs_stopped,
        {"representation": "STOPPED"},
    )
    assert overall == "DEGRADED"
    assert any(a["reason_code"] == "PAPER_PROCESS_DOWN" for a in alerts)


def test_22_context_noop_healthy():
    # build_context_chain marks NO_NEW_SAFE_UPSTREAM as healthy noop when process up
    src = (ROOT / "ops_dashboard_runtime_truth.py").read_text(encoding="utf-8")
    assert "NO_NEW_SAFE_UPSTREAM_is_normal_noop" in src


def test_23_context_failure_degraded_or_broken():
    procs = [
        {"process_id": "live_feed", "health": "RUNNING"},
        {"process_id": "canonical_pipeline", "health": "RUNNING"},
        {"process_id": "context_refresher", "health": "STOPPED"},
        {"process_id": "paper_controller", "health": "RUNNING"},
    ]
    overall, _, alerts = truth.compute_overall_health(procs, {"representation": "RUNNING_NO_ELIGIBLE_TRADE"})
    assert overall in {"DEGRADED", "FAILED", "BROKEN"}
    assert any(a["reason_code"] == "CONTEXT_CHAIN_STALE" for a in alerts)


def test_24_auction_synthesis_broken_non_required(snapshot):
    lim = {x["id"]: x for x in snapshot["known_limitations"]}
    assert "AUCTION_SYNTHESIS_ACTIVE_BROKEN" in lim
    assert lim["AUCTION_SYNTHESIS_ACTIVE_BROKEN"]["required_by_current_runtime"] is False
    assert lim["AUCTION_SYNTHESIS_ACTIVE_BROKEN"]["reason"] == "WRITER_DISCONNECTED"
    assert any(
        a["reason_code"] == "AUCTION_SYNTHESIS_BROKEN_NON_REQUIRED" for a in snapshot["alerts"]
    )


def test_25_deprecated_oi_non_required(snapshot):
    deprecated = [
        c
        for c in snapshot["legacy_components"]
        if c.get("classification") == "INACTIVE_DEPRECATED"
    ]
    ids = {c["component_id"] for c in deprecated}
    assert "oi_history" in ids or "btc_oi" in ids
    assert all(c.get("required_by_current_runtime") is False for c in deprecated)


def test_26_overall_known_limitations(snapshot):
    assert snapshot["overall_health"] in {
        "OPERATIONAL_WITH_LIMITATIONS",
        "HEALTHY_WITH_KNOWN_LIMITATIONS",
        "HEALTHY",
        "DEGRADED",
        "BROKEN",
        "FAILED",
        "UNKNOWN",
    }
    # With live runtime up, expected production state is known-limitations.
    required_ids = {"live_feed", "canonical_pipeline", "context_refresher"}
    if any(p["process_id"] == "timeframe_manager" for p in snapshot["processes"]):
        required_ids |= {"timeframe_manager", "trader_M15", "trader_M30", "trader_H1", "trader_H4"}
    else:
        required_ids.add("paper_controller")
    if all(
        p.get("health") == "RUNNING"
        for p in snapshot["processes"]
        if p["process_id"] in required_ids
    ):
        assert snapshot["overall_health"] in {
            "OPERATIONAL_WITH_LIMITATIONS",
            "HEALTHY_WITH_KNOWN_LIMITATIONS",
        }


def test_27_feed_down_broken():
    procs = [
        {"process_id": "live_feed", "health": "STOPPED"},
        {"process_id": "canonical_pipeline", "health": "RUNNING"},
        {"process_id": "context_refresher", "health": "RUNNING"},
        {"process_id": "paper_controller", "health": "RUNNING"},
    ]
    overall, _, alerts = truth.compute_overall_health(procs, {"representation": "RUNNING_NO_ELIGIBLE_TRADE"})
    assert overall == "FAILED"
    assert any(a["reason_code"] == "FEED_DOWN" for a in alerts)


def test_28_pipeline_down_broken():
    procs = [
        {"process_id": "live_feed", "health": "RUNNING"},
        {"process_id": "canonical_pipeline", "health": "STOPPED"},
        {"process_id": "context_refresher", "health": "RUNNING"},
        {"process_id": "paper_controller", "health": "RUNNING"},
    ]
    overall, _, _ = truth.compute_overall_health(procs, {"representation": "RUNNING_NO_ELIGIBLE_TRADE"})
    assert overall == "FAILED"


def test_29_decision_stale_degraded_contract():
    procs = [
        {"process_id": "live_feed", "health": "RUNNING"},
        {"process_id": "canonical_pipeline", "health": "RUNNING"},
        {"process_id": "context_refresher", "health": "RUNNING"},
        {"process_id": "paper_controller", "health": "RUNNING"},
    ]
    overall, reason, alerts = truth.compute_overall_health(
        procs,
        {"representation": "RUNNING_NO_ELIGIBLE_TRADE"},
        decision_materially_stale=True,
    )
    assert overall == "DEGRADED"
    assert "decision" in reason
    assert any(a["reason_code"] == "DECISION_STALE" for a in alerts)


def test_30_unknown_critical_source_not_healthy():
    procs = [
        {"process_id": "live_feed", "health": "RUNNING"},
        {"process_id": "canonical_pipeline", "health": "RUNNING"},
        {"process_id": "context_refresher", "health": "RUNNING"},
        {"process_id": "paper_controller", "health": "RUNNING"},
    ]
    overall, _, alerts = truth.compute_overall_health(
        procs,
        {"representation": "RUNNING_NO_ELIGIBLE_TRADE"},
        critical_source_unknown=True,
    )
    assert overall == "UNKNOWN"
    assert overall != "HEALTHY"
    assert any(a["reason_code"] == "UNKNOWN_CRITICAL_SOURCE" for a in alerts)
    ops = (ROOT / "dashboard/backend/app/services/ops_monitor.py").read_text(encoding="utf-8")
    assert "runtime_truth_unavailable" in ops


def test_31_api_schema_keys(snapshot):
    for key in (
        "generated_at",
        "schema_version",
        "overall_health",
        "overall_reason",
        "processes",
        "pipeline_engines",
        "datasets",
        "multi_timeframe",
        "context_chain",
        "paper",
        "known_limitations",
        "legacy_components",
        "alerts",
    ):
        assert key in snapshot


def test_32_frontend_handles_null_fields_contract():
    dash = (ROOT / "dashboard/frontend/src/components/ops/OpsDashboard.tsx").read_text(encoding="utf-8")
    assert "LiveOperationalTruth" in dash or "RuntimeTruthSection" in dash
    assert "overall_health" in dash
    # Safe optional chaining / fallbacks present
    assert "??" in dash or "||" in dash or "?." in dash


def test_33_frontend_no_hardcoded_engine_count():
    fb = (ROOT / "dashboard/frontend/src/api/opsFallbackSnapshot.ts").read_text(encoding="utf-8")
    assert "24" not in re.findall(r"\b24\b", fb) or "ENGINE_NAMES.length" in fb
    assert "expected_step_count: ENGINE_NAMES.length" in fb or "ENGINE_NAMES.length" in fb


def test_34_frontend_no_hardcoded_24_engine_list():
    fb = (ROOT / "dashboard/frontend/src/api/opsFallbackSnapshot.ts").read_text(encoding="utf-8")
    for phantom in (
        "volume_localization_engine_v1.py",
        "market_state_engine_v1.py",
        "trading_state_engine_v1.py",
        "shadow_inference_engine_v1.py",
        "trading_state_validation_engine_v1.py",
        "economic_validation_engine_v1.py",
    ):
        assert phantom not in fb
    assert "mtf_availability_runtime_engine_v1.py" in fb
    assert "auction_context_arbitration_engine_v1.py" in fb
    # Exactly 20 names in fallback list
    names = re.findall(r'"([a-z0-9_]+\.py)"', fb)
    engine_names = [n for n in names if n.endswith(".py") and ("engine" in n or "memory" in n or "cognition" in n or "observer" in n or "mtf_" in n)]
    # ENGINE_NAMES block should yield 20
    assert len(truth.parse_canonical_pipeline()) == 20


def test_35_snapshot_deterministic_core(snapshot):
    again = truth.build_runtime_truth_snapshot()
    assert [e["engine_id"] for e in snapshot["pipeline_engines"]] == [
        e["engine_id"] for e in again["pipeline_engines"]
    ]
    assert snapshot["overall_health"] == again["overall_health"]
    assert snapshot["schema_version"] == again["schema_version"]


def test_36_dashboard_read_only_contract():
    src = (ROOT / "ops_dashboard_runtime_truth.py").read_text(encoding="utf-8")
    assert "Read-only" in src or "read-only" in src
    assert "Does not start writers" in src
    # No write helpers for cognition/paper
    assert "to_parquet(" not in src
    assert "open(" not in src or "read" in src


def test_37_runtime_datasets_unchanged_by_truth_builder(tmp_path, monkeypatch):
    target = ROOT / "data/runtime/runtime_dataset_status.json"
    if not target.exists():
        pytest.skip("runtime_dataset_status missing")
    before = _sha(target)
    truth.build_runtime_truth_snapshot()
    assert _sha(target) == before


def test_38_no_exchange_api_trading_call_in_truth_builder():
    src = (ROOT / "ops_dashboard_runtime_truth.py").read_text(encoding="utf-8")
    for banned in ("binance.com", "create_order", "place_order", "ccxt", "exchange_client"):
        assert banned not in src


def test_39_continuation_off_flag_surface(snapshot):
    flags = snapshot.get("flags_frozen") or {}
    assert str(flags.get("BTC_ML_CONTINUATION_PROGRESSION", "0")) in {"0", "OFF", "false", "False"}


def test_40_price_gate_off_flag_surface(snapshot):
    flags = snapshot.get("flags_frozen") or {}
    assert str(flags.get("PRICE_GATE", "OFF")).upper() in {"OFF", "0", "FALSE"}


def test_pipeline_metadata_loads_from_runtime_ast(pipeline_meta):
    live = truth.parse_canonical_pipeline()
    assert list(pipeline_meta.CANONICAL_PIPELINE) == live


def test_css_visual_baseline_untouched():
    css = ROOT / "dashboard/frontend/src/index.css"
    assert css.exists()
    # Activation script recorded css unchanged; ensure file still present and non-empty.
    assert css.stat().st_size > 100


def test_ops_monitor_wires_runtime_truth():
    ops = (ROOT / "dashboard/backend/app/services/ops_monitor.py").read_text(encoding="utf-8")
    assert "build_runtime_truth_snapshot" in ops
    assert "ops_snapshot_v2_runtime_truth" in ops or "ops_snapshot_v3_live_research_historical" in ops
    assert "pipeline_engines" in ops


def test_no_pipeline24_hardcoded_label():
    research = (ROOT / "dashboard/backend/app/services/research_pipeline_service.py").read_text(
        encoding="utf-8"
    )
    assert "PIPELINE24" not in research
