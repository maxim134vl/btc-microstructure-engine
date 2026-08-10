"""Minimal MODEL-9 unified Model Assurance summary tests (exactly five)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from btc_ml.model_assurance import summary as summ


def _fresh(now: datetime) -> str:
    return now.isoformat().replace("+00:00", "Z")


def _stale(now: datetime, seconds: int = 120) -> str:
    return (now - timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _base_overrides(now: datetime) -> dict:
    ts = _fresh(now)
    return {
        "active": {
            "registry_record_id": "REG_A",
            "model_id": "BTC_INTRABAR_RULE_BASED",
            "model_version": "INTRABAR_RULES_V1",
            "model_type": "RULE_BASED",
            "runtime_fingerprint": "fp_full_runtime_fingerprint_value",
            "paper_epoch_id": "INTRABAR_RULES_V1_20260728_110636",
            "paper_epoch_activated_at": ts,
            "paper_only": True,
            "real_execution": False,
        },
        "registry_status": {
            "status": "ACTIVE_REGISTERED",
            "active_model_id": "BTC_INTRABAR_RULE_BASED",
            "active_model_version": "INTRABAR_RULES_V1",
            "active_registry_record_id": "REG_A",
            "updated_at": ts,
        },
        "bv_summary": {
            "status": "NO_ELIGIBLE_CONTEXTS_YET",
            "eligible_contexts": 0,
            "open_predictions": 0,
            "closed_predictions": 0,
            "evaluated_outcomes": 0,
            "pending_outcomes": 0,
            "updated_at": ts,
        },
        "bv_health": {"alive": True, "status": "NO_ELIGIBLE_CONTEXTS_YET", "updated_at": ts},
        "ext_summary": {
            "status": "CURRENT_HEALTHY",
            "configured_sources": 3,
            "healthy_sources": 3,
            "degraded_sources": 0,
            "unavailable_sources": 0,
            "open_events": 0,
            "updated_at": ts,
        },
        "ext_health": {"alive": True, "status": "CURRENT_HEALTHY", "updated_at": ts},
        "ev_summary": {
            "status": "NO_ELIGIBLE_TRADES_YET",
            "closed_trades": 0,
            "open_positions": 0,
            "evaluated_trades": 0,
            "gross_pnl_usd": 0.0,
            "net_pnl_usd": 0.0,
            "updated_at": ts,
        },
        "ev_health": {"alive": True, "status": "NO_ELIGIBLE_TRADES_YET", "updated_at": ts},
        "tox_summary": {
            "status": "NO_ELIGIBLE_EVENTS_YET",
            "context_toxic_candidates": 0,
            "context_confirmed_events": 0,
            "trade_toxic_candidates": 0,
            "trade_confirmed_events": 0,
            "not_evaluable_checks": {"NO_OUTCOME": 2, "BBO_MISSING": 3},
            "updated_at": ts,
        },
        "tox_health": {"alive": True, "status": "NO_ELIGIBLE_EVENTS_YET", "updated_at": ts},
        "inc_summary": {
            "status": "NO_ELIGIBLE_INCIDENTS_YET",
            "distinct_incidents": 0,
            "cross_branch_incidents": 0,
            "single_branch_incidents": 0,
            "open_incidents": 0,
            "economic_harm_usd": 0.0,
            "updated_at": ts,
        },
        "inc_health": {"alive": True, "status": "NO_ELIGIBLE_INCIDENTS_YET", "updated_at": ts},
        "drift_summary": {
            "status": "CURRENT_CRITICAL",
            "input_drift_status": "CRITICAL",
            "feature_drift_status": "COLLECTING_BASELINE",
            "context_drift_status": "COLLECTING_BASELINE",
            "performance_drift_status": "COLLECTING_BASELINE",
            "frozen_baselines": 1,
            "watch_metrics": [],
            "warning_metrics": [],
            "critical_metrics": ["input:spread"],
            "suppressed_metrics": [],
            "updated_at": ts,
        },
        "drift_health": {"alive": True, "status": "CURRENT_CRITICAL", "updated_at": ts},
        "shadow_summary": {
            "status": "NO_CANDIDATE_REGISTERED",
            "candidate_status": "NONE_REGISTERED",
            "shadow_status": "NOT_APPLICABLE_NO_CANDIDATE",
            "shadow_inputs": 0,
            "shadow_predictions": 0,
            "comparisons": 0,
            "agreement_rate": None,
            "updated_at": ts,
        },
        "shadow_health": {"alive": True, "status": "NO_CANDIDATE_REGISTERED", "updated_at": ts},
        "gate_summary": {
            "status": "NOT_APPLICABLE_NO_CANDIDATE",
            "eligibility_status": "NOT_APPLICABLE",
            "governance_status": "NONE",
            "promotion_execution_status": "DISABLED",
            "blockers": [],
            "environment_blockers": ["INPUT_DRIFT_CRITICAL"],
            "active_decision": None,
            "approval_stale": False,
            "active_model_change_performed": False,
            "updated_at": ts,
            "last_evaluated_at": ts,
        },
        "gate_health": {"alive": True, "status": "NOT_APPLICABLE_NO_CANDIDATE", "updated_at": ts},
    }


def _wire_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {
        "poll_interval_seconds": 5,
        "source_stale_after_seconds": 30,
        "registry_stale_after_seconds": 3600,
        "display_fingerprint_characters": 12,
        "module_freshness_seconds": {
            "behavioral_validation": 30,
            "external_data": 30,
            "economic_validation": 120,
            "current_toxicity": 30,
            "incident_correlation": 30,
            "drift_monitoring": 30,
            "candidate_shadow": 30,
            "governance_promotion": 30,
        },
    }
    cfg_path = tmp_path / "config" / "model_assurance_summary.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    def paths(repo_root=None):
        base = tmp_path / "data" / "model_assurance"
        return {
            "config": cfg_path,
            "latest_summary": base / "summary" / "latest_summary.json",
            "health": base / "summary" / "runtime" / "health.json",
            "active": base / "registry" / "active" / "active_model.json",
            "registry_status": base / "registry" / "registry_status.json",
            "bv_summary": base / "behavioral_validation" / "snapshots" / "latest_summary.json",
            "bv_health": base / "behavioral_validation" / "runtime" / "health.json",
            "ext_summary": base / "toxic_box" / "external_data" / "snapshots" / "latest_summary.json",
            "ext_health": base / "toxic_box" / "external_data" / "runtime" / "health.json",
            "ev_summary": base / "economic_validation" / "snapshots" / "latest_summary.json",
            "ev_health": base / "economic_validation" / "runtime" / "health.json",
            "tox_summary": base / "toxic_box" / "current" / "snapshots" / "latest_summary.json",
            "tox_health": base / "toxic_box" / "current" / "runtime" / "health.json",
            "inc_summary": base / "toxic_box" / "incidents" / "snapshots" / "latest_summary.json",
            "inc_health": base / "toxic_box" / "incidents" / "runtime" / "health.json",
            "drift_summary": base / "drift" / "snapshots" / "latest_summary.json",
            "drift_health": base / "drift" / "runtime" / "health.json",
            "shadow_summary": base / "shadow" / "snapshots" / "latest_summary.json",
            "shadow_health": base / "shadow" / "runtime" / "health.json",
            "gate_summary": base / "governance" / "snapshots" / "latest_gate.json",
            "gate_health": base / "governance" / "runtime" / "health.json",
        }

    monkeypatch.setattr(summ, "summary_paths", paths)
    monkeypatch.setattr(summ, "load_summary_config", lambda repo_root=None: cfg)


def test_1_aggregates_current_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    _wire_tmp(tmp_path, monkeypatch)
    out = summ.build_unified_summary(repo_root=tmp_path, now=now, overrides=_base_overrides(now))
    assert out["scope"] == "CURRENT_ACTIVE_MODEL_ONLY"
    assert out["runtime_impact"] == "NON_BLOCKING"
    assert out["promotion_control"] == "GOVERNANCE_GATE"
    assert out["active_runtime"]["model_id"] == "BTC_INTRABAR_RULE_BASED"
    assert out["active_runtime"]["model_version"] == "INTRABAR_RULES_V1"
    assert out["behavioral_validation"]["module_id"] == "MODEL-1"
    assert out["governance_promotion"]["module_id"] == "MODEL-8"
    assert out["service_health"]["MODEL-0"] == "NOT_APPLICABLE"
    assert out["historical_counters_excluded"] is True


def test_2_input_drift_critical_keeps_runtime_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    _wire_tmp(tmp_path, monkeypatch)
    out = summ.build_unified_summary(repo_root=tmp_path, now=now, overrides=_base_overrides(now))
    assert out["overall_assurance_status"] == "CURRENT_CRITICAL"
    assert out["overall_cause"] == "INPUT_DRIFT_CRITICAL"
    assert out["runtime_safety_status"] == "SAFE_PAPER_ONLY"
    assert out["runtime_impact"] == "NON_BLOCKING"
    assert "INPUT_DRIFT_CRITICAL" in out["environment_blockers"]


def test_3_no_eligible_not_translated_to_missing_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = datetime.now(timezone.utc)
    _wire_tmp(tmp_path, monkeypatch)
    out = summ.build_unified_summary(repo_root=tmp_path, now=now, overrides=_base_overrides(now))
    assert out["behavioral_validation"]["status"] == "NO_ELIGIBLE_CONTEXTS_YET"
    assert out["economic_validation"]["status"] == "NO_ELIGIBLE_TRADES_YET"
    assert out["current_toxicity"]["status"] == "NO_ELIGIBLE_EVENTS_YET"
    assert out["incident_correlation"]["status"] == "NO_ELIGIBLE_INCIDENTS_YET"
    assert out["candidate_shadow"]["summary"]["candidate_status"] == "NONE_REGISTERED"
    assert out["candidate_shadow"]["summary"]["shadow_status"] == "NOT_APPLICABLE_NO_CANDIDATE"
    blob = json.dumps(out)
    assert "Behavioral Validation MISSING" not in blob
    assert '"status": "FAILED"' not in blob
    assert "toxic baseline" not in blob.lower()


def test_4_stale_and_missing_distinct_from_collecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = datetime.now(timezone.utc)
    _wire_tmp(tmp_path, monkeypatch)
    overrides = _base_overrides(now)
    # Collecting is not missing
    out_ok = summ.build_unified_summary(repo_root=tmp_path, now=now, overrides=overrides)
    assert "behavioral_validation" not in out_ok["missing_sources"]
    assert out_ok["behavioral_validation"]["status"] == "NO_ELIGIBLE_CONTEXTS_YET"

    # Truly missing file
    overrides2 = dict(overrides)
    overrides2["tox_summary"] = None
    # Also need path to not exist — summary_paths points under tmp; write others only
    paths = summ.summary_paths(tmp_path)
    for key, payload in overrides2.items():
        if payload is None or key.endswith("_health") and key.startswith("tox"):
            continue
        if key == "tox_summary":
            continue
        path = paths[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    out_missing = summ.build_unified_summary(repo_root=tmp_path, now=now, overrides=overrides2)
    assert "current_toxicity" in out_missing["missing_sources"]
    assert out_missing["current_toxicity"]["status"] == "MISSING_SOURCE"

    # Stale health/source
    overrides3 = _base_overrides(now)
    stale_ts = _stale(now, 120)
    overrides3["drift_summary"] = {**overrides3["drift_summary"], "updated_at": stale_ts}
    overrides3["drift_health"] = {**overrides3["drift_health"], "updated_at": stale_ts}
    out_stale = summ.build_unified_summary(repo_root=tmp_path, now=now, overrides=overrides3)
    assert "drift_monitoring" in out_stale["stale_sources"]
    assert out_stale["service_health"]["MODEL-6"] == "ALIVE_STALE"
    assert out_stale["overall_assurance_status"] == "CURRENT_STALE"


def test_5_idempotent_run_replaces_empty_arrays_excludes_historical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = datetime.now(timezone.utc)
    _wire_tmp(tmp_path, monkeypatch)
    overrides = _base_overrides(now)
    # Seed a previous summary with historical leftovers that must be replaced
    paths = summ.summary_paths(tmp_path)
    paths["latest_summary"].parent.mkdir(parents=True, exist_ok=True)
    paths["latest_summary"].write_text(
        json.dumps(
            {
                "current_blockers": ["OLD_BLOCKER"],
                "current_incidents": [{"id": "old"}],
                "current_toxic_events": [{"id": "legacy"}],
                "historical_toxic_baseline": 3879,
                "shadow_evaluations": 6771,
            }
        ),
        encoding="utf-8",
    )

    def _run():
        return summ.build_unified_summary(repo_root=tmp_path, now=now, overrides=overrides)

    first = _run()
    second = _run()
    # Idempotent content (ignore generated_at)
    for key in (
        "overall_assurance_status",
        "environment_blockers",
        "promotion_blockers",
        "current_blockers",
        "current_incidents",
        "current_toxic_events",
        "missing_sources",
        "stale_sources",
    ):
        assert first[key] == second[key]
    assert first["current_incidents"] == []
    assert first["current_toxic_events"] == []
    assert "OLD_BLOCKER" not in first["current_blockers"]
    assert "historical_toxic_baseline" not in first
    assert "shadow_evaluations" not in first
    assert "3879" not in json.dumps(first)
    assert "6771" not in json.dumps(first)

    # Persist via run_once without recursive monkeypatch
    first_fixed = dict(first)
    first_fixed["generated_at"] = "FIXED"
    monkeypatch.setattr(summ, "build_unified_summary", lambda **kwargs: dict(first_fixed))
    written = summ.run_once(repo_root=tmp_path)
    loaded = json.loads(paths["latest_summary"].read_text(encoding="utf-8"))
    assert loaded["current_incidents"] == []
    assert loaded["current_toxic_events"] == []
    assert loaded["overall_assurance_status"] == written["overall_assurance_status"]
    assert "historical_toxic_baseline" not in loaded
    assert "shadow_evaluations" not in loaded
