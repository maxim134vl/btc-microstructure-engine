#!/usr/bin/env python3
"""OPS1B — live operations truth candidate tests."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ops_dashboard_runtime_truth as truth  # noqa: E402

CANDIDATE = ROOT / "data/candidate/architecture_recovery/ops1b_live_operations_truth_candidate"


@pytest.fixture(scope="module")
def live_env():
    return {
        "BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE": "1",
        "BTC_ML_VOLUME_LOCALIZATION_LIVE": "1",
    }


def test_nested_if_else_assignments_found():
    path = ROOT / "src/btc_ml/runtime/pipeline.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    truth._collect_pipeline_assignments(
        list(tree.body),
        (),
        found,
        {truth.STAGE2_SYNTHESIS_INPUTS_LIVE_ENV: True},
    )
    assert len(found) >= 2
    builders = []
    for item in found:
        val = item["value"]
        if isinstance(val, ast.Call) and isinstance(val.func, ast.Name):
            builders.append(val.func.id)
    assert "canonical_pipeline_with_stage2_synthesis_inputs_candidate" in builders
    assert "canonical_pipeline_with_volume_localization_candidate" in builders


def test_builder_call_resolved_safely_no_eval_exec(live_env):
    import re

    src = (ROOT / "ops_dashboard_runtime_truth.py").read_text(encoding="utf-8")
    # Allow ast.literal_eval only; forbid bare eval/exec.
    assert not re.search(r"(?<!literal_)eval\(", src)
    assert not re.search(r"(?<![A-Za-z_])exec\(", src)
    meta = truth.resolve_active_canonical_pipeline(environ=live_env)
    assert meta["active_builder"] == "canonical_pipeline_with_stage2_synthesis_inputs_candidate"
    assert meta["total_engine_count"] == 26


def test_current_flags_resolve_active_branch(live_env):
    meta = truth.resolve_active_canonical_pipeline(environ=live_env)
    assert meta["active_flags"][truth.STAGE2_SYNTHESIS_INPUTS_LIVE_ENV] is True
    assert "live_volume_flow_engine_v1.py" in meta["ordered_engine_names"]
    assert "volume_localization_engine_v1.py" in meta["ordered_engine_names"]


def test_alternative_flag_branch_dynamic_count():
    meta = truth.resolve_active_canonical_pipeline(
        environ={"BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE": "0"}
    )
    assert meta["total_engine_count"] == 21
    assert meta["active_builder"] == "canonical_pipeline_with_volume_localization_candidate"
    assert "live_volume_flow_engine_v1.py" not in meta["ordered_engine_names"]


def test_engine_order_preserved(live_env):
    engines = truth.resolve_active_canonical_pipeline(environ=live_env)["ordered_engine_names"]
    assert engines.index("candle_structure_engine_v1.py") < engines.index(
        "volume_localization_engine_v1.py"
    )
    assert engines.index("volume_localization_engine_v1.py") < engines.index(
        "volume_response_engine_v1.py"
    )
    assert engines.index("htf_ltf_context_engine_v1.py") < engines.index(
        "auction_synthesis_engine_v1.py"
    )


def test_expected_count_dynamic_and_required_separated(live_env):
    meta = truth.resolve_active_canonical_pipeline(environ=live_env)
    assert meta["total_engine_count"] == len(meta["ordered_engine_names"])
    assert meta["required_engine_count"] == 3
    assert meta["required_engine_count"] < meta["total_engine_count"]
    assert "expected 20" not in json.dumps(meta)


def test_volume_localization_not_phantom_when_active(live_env):
    meta = truth.resolve_active_canonical_pipeline(environ=live_env)
    assert "volume_localization_engine_v1.py" in meta["ordered_engine_names"]
    assert "volume_localization_engine_v1.py" not in meta["phantom_engines"]
    assert "volume_localization_engine_v1.py" not in truth.PHANTOM_ENGINES


def test_failure_isolation_keeps_processes_traders_context(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("injected parser failure")

    monkeypatch.setattr(truth, "resolve_active_canonical_pipeline", boom)
    snap = truth.build_runtime_truth_snapshot()
    assert "pipeline_metadata" in snap["section_errors"]
    assert snap["processes"], "processes must remain"
    assert (snap.get("timeframe_traders") or {}).get("traders"), "traders must remain"
    assert snap.get("context_chain"), "context attempt must remain"
    assert snap["pipeline_engines"] == []


def test_processes_include_pipeline_manager_traders():
    rows = {p["process_id"]: p for p in truth.inspect_processes()}
    assert rows["canonical_pipeline"]["alive"] is True
    assert rows["timeframe_manager"]["alive"] is True
    for tf in ("M15", "M30", "H1", "H4"):
        assert rows[f"trader_{tf}"]["alive"] is True
        assert rows[f"trader_{tf}"]["pid"]


def test_runtime_uptime_uses_pipeline_pid_not_boot():
    snap = truth.build_runtime_truth_snapshot()
    up = snap["runtime_uptime"]
    assert up["source"] == "pipeline_pid_create_time"
    assert up["host_boot_time_substituted"] is False
    assert up["pipeline_pid"]
    assert up["runtime_uptime_seconds"] is not None
    assert up["runtime_uptime_seconds"] < 3600 * 24 * 30  # not multi-month host uptime


def test_missing_pipeline_pid_uptime_null(monkeypatch):
    monkeypatch.setattr(
        truth,
        "inspect_processes",
        lambda: [
            {
                "process_id": "canonical_pipeline",
                "pid": None,
                "alive": False,
                "health": "STOPPED",
            }
        ],
    )
    up = truth.pipeline_runtime_uptime()
    assert up["runtime_uptime_seconds"] is None
    assert up["reason"] == "PIPELINE_PID_UNAVAILABLE"
    assert up["host_boot_time_substituted"] is False


def test_schema_compatible_and_no_trading_writes(live_env, monkeypatch):
    monkeypatch.setenv("BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE", "1")
    books = [
        ROOT / f"data/trading/timeframe_traders/{tf}/positions.parquet"
        for tf in ("M15", "M30", "H1", "H4")
    ]
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in books if p.exists()}
    snap = truth.build_runtime_truth_snapshot()
    for key in (
        "processes",
        "pipeline_engines",
        "context_chain",
        "timeframe_traders",
        "overall_health",
        "schema_version",
    ):
        assert key in snap
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in before}
    assert after == before


def test_write_candidate_artifacts(live_env, monkeypatch):
    monkeypatch.setenv("BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE", "1")
    monkeypatch.setenv("BTC_ML_VOLUME_LOCALIZATION_LIVE", "1")
    CANDIDATE.mkdir(parents=True, exist_ok=True)
    baseline = {
        "exception_type": "RuntimeError",
        "exception_message": "CANONICAL_PIPELINE not found",
        "source_file": "ops_dashboard_runtime_truth.py",
        "function": "parse_canonical_pipeline",
        "payload_fields_lost_pre_fix": ["processes", "timeframe_traders", "context_chain"],
        "reproduced_pre_patch": True,
    }
    (CANDIDATE / "baseline_failure.json").write_text(json.dumps(baseline, indent=2) + "\n")
    meta = truth.resolve_active_canonical_pipeline(environ=live_env)
    (CANDIDATE / "resolved_pipeline_metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    snap = truth.build_runtime_truth_snapshot()
    (CANDIDATE / "candidate_runtime_truth.json").write_text(
        json.dumps(
            {
                "generated_at": snap["generated_at"],
                "overall_health": snap["overall_health"],
                "section_errors": snap["section_errors"],
                "pipeline_metadata": snap["pipeline_metadata"],
                "runtime_uptime": snap["runtime_uptime"],
                "process_count": len(snap["processes"]),
                "engine_count": len(snap["pipeline_engines"]),
                "trader_count": len((snap.get("timeframe_traders") or {}).get("traders") or []),
            },
            indent=2,
        )
        + "\n"
    )
    (CANDIDATE / "process_truth.json").write_text(json.dumps(snap["processes"], indent=2) + "\n")
    (CANDIDATE / "timeframe_traders.json").write_text(
        json.dumps(snap["timeframe_traders"], indent=2) + "\n"
    )
    (CANDIDATE / "context_chain.json").write_text(json.dumps(snap["context_chain"], indent=2) + "\n")
    assert meta["total_engine_count"] == 26
    assert snap["section_errors"] == {}
