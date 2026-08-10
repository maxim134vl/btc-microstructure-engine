"""Minimal MODEL-8 promotion gate tests (exactly five)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.model_assurance.governance import evidence as ev
from btc_ml.model_assurance.governance import ledger
from btc_ml.model_assurance.governance import monitor as mon
from btc_ml.model_assurance.governance import promotion_gate as gate
from btc_ml.model_assurance.toxic_box.common import read_jsonl


ACTIVE = {
    "registry_record_id": "REG_ACTIVE_TEST",
    "model_id": "ACTIVE_M",
    "model_version": "V1",
    "runtime_fingerprint": "fp_active",
    "paper_only": True,
    "real_execution": False,
}

CANDIDATE = {
    "registry_record_id": "REG_CAND_TEST",
    "model_id": "CAND_M",
    "model_version": "C1",
    "runtime_fingerprint": "fp_cand",
    "record_status": "CANDIDATE_REGISTERED",
    "execution_capability": "NONE",
    "execution_enabled": False,
    "adapter_module": "tests.fake_adapter",
    "adapter_class": "FakeAdapter",
}

GOV_CFG = {
    "promotion_execution_enabled": False,
    "required_manual_approvals": 1,
    "minimum_closed_trades": 400,
    "shadow": {
        "minimum_predictions": 1000,
        "minimum_comparisons": 1000,
        "minimum_elapsed_hours": 168,
        "maximum_not_evaluable_ratio": 0.05,
        "require_zero_execution_entities": True,
    },
    "environment": {
        "require_external_data_healthy": True,
        "block_on_drift_warning": True,
        "block_on_drift_critical": True,
        "block_on_confirmed_critical_toxicity": True,
        "block_on_open_critical_incident": True,
        "block_on_pnl_reconciliation_mismatch": True,
    },
    "poll_interval_seconds": 5,
}


def _healthy_snaps(**overrides) -> dict:
    base = {
        "shadow": {
            "status": "SHADOW_RUNNING",
            "shadow_status": "SHADOW_RUNNING",
            "shadow_inputs": 2000,
            "shadow_predictions": 2000,
            "comparisons": 2000,
            "shadow_not_evaluable": 0,
            "shadow_elapsed_hours": 200.0,
            "shadow_created_orders": 0,
            "shadow_created_fills": 0,
            "shadow_created_positions": 0,
            "last_evaluated_at": "2026-07-28T10:00:00Z",
        },
        "drift": {
            "input_drift_status": "STABLE",
            "feature_drift_status": "STABLE",
            "context_drift_status": "STABLE",
            "performance_drift_status": "STABLE",
            "last_evaluated_at": "2026-07-28T10:00:00Z",
        },
        "external": {"status": "CURRENT_HEALTHY", "last_evaluated_at": "2026-07-28T10:00:00Z"},
        "toxicity_current": {"status": "CURRENT_HEALTHY", "context_confirmed_events": 0, "trade_confirmed_events": 0},
        "incidents": {"status": "NO_OPEN_INCIDENTS", "open_incidents": 0, "critical_incidents": 0},
        "behavioral": {"status": "NO_ELIGIBLE_CONTEXTS_YET"},
        "economic": {
            "status": "CURRENT",
            "closed_trades": 400,
            "pnl_reconciliation_mismatches": 0,
        },
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def _wire_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    p = {
        "evidence": tmp_path / "evidence" / "evidence_snapshots.jsonl",
        "evaluations": tmp_path / "evaluations" / "promotion_evaluations.jsonl",
        "decisions": tmp_path / "decisions" / "governance_decisions.jsonl",
        "latest_gate": tmp_path / "snapshots" / "latest_gate.json",
        "latest_governance": tmp_path / "snapshots" / "latest_governance.json",
        "checkpoint": tmp_path / "runtime" / "checkpoint.json",
        "health": tmp_path / "runtime" / "health.json",
        "active_model": tmp_path / "active_model.json",
    }
    p["active_model"].write_text(
        json.dumps(
            {
                "registry_record_id": ACTIVE["registry_record_id"],
                "model_id": ACTIVE["model_id"],
                "model_version": ACTIVE["model_version"],
                "runtime_fingerprint": ACTIVE["runtime_fingerprint"],
                "paper_only": True,
                "real_execution": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mon, "paths", lambda repo_root=None: p)
    monkeypatch.setattr(mon, "load_governance_config", lambda repo_root=None: GOV_CFG)
    monkeypatch.setattr(ev, "load_governance_config", lambda repo_root=None: GOV_CFG)
    return p


def test_1_no_candidate_preserves_environment_drift_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    p = _wire_paths(tmp_path, monkeypatch)
    snaps = _healthy_snaps(drift={"input_drift_status": "CRITICAL"})
    monkeypatch.setattr(mon, "read_active_runtime", lambda repo_root=None: ACTIVE)
    monkeypatch.setattr(ev, "read_candidate", lambda repo_root=None: None)
    monkeypatch.setattr(mon, "read_active_runtime", lambda repo_root=None: ACTIVE)

    def _build(*, repo_root=None, active=None, candidate=None, snapshots=None):
        return ev.build_promotion_evidence_snapshot(
            repo_root=tmp_path,
            active=active or ACTIVE,
            candidate=None,
            snapshots=snaps,
        )

    monkeypatch.setattr(mon, "build_promotion_evidence_snapshot", _build)
    result = mon.run_once(repo_root=tmp_path)
    assert result["status"] == "NOT_APPLICABLE_NO_CANDIDATE"
    assert result["candidate_status"] == "NONE_REGISTERED"
    assert result["blockers"] == []
    assert "INPUT_DRIFT_CRITICAL" in result["environment_blockers"]
    assert result["promotion_execution_status"] == "DISABLED"
    assert result["active_model_change_performed"] is False


def test_2_candidate_with_critical_drift_blocked_approve_forbidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    p = _wire_paths(tmp_path, monkeypatch)
    snaps = _healthy_snaps(drift={"input_drift_status": "CRITICAL"})
    evidence = ev.build_promotion_evidence_snapshot(
        repo_root=tmp_path, active=ACTIVE, candidate=CANDIDATE, snapshots=snaps
    )
    eligibility = gate.evaluate_promotion_eligibility(evidence=evidence, config=GOV_CFG)
    assert eligibility["gate_status"] == "BLOCKED"
    assert "INPUT_DRIFT_CRITICAL" in eligibility["blockers"]
    evaluation = gate.build_evaluation_record(evidence=evidence, eligibility=eligibility)
    with pytest.raises(ValueError, match="APPROVE_FORBIDDEN"):
        ledger.approve(
            decisions_path=p["decisions"],
            evaluation=evaluation,
            evidence=evidence,
            actor_id="tester",
            reason="should fail",
            expected_evaluation_id=evaluation["evaluation_id"],
        )
    assert not p["decisions"].exists() or read_jsonl(p["decisions"]) == []


def test_3_candidate_healthy_sufficient_shadow_eligible(tmp_path: Path):
    snaps = _healthy_snaps()
    evidence = ev.build_promotion_evidence_snapshot(
        repo_root=tmp_path, active=ACTIVE, candidate=CANDIDATE, snapshots=snaps
    )
    eligibility = gate.evaluate_promotion_eligibility(evidence=evidence, config=GOV_CFG)
    assert eligibility["gate_status"] == "ELIGIBLE_FOR_REVIEW"
    assert eligibility["eligibility_status"] == "ELIGIBLE_FOR_REVIEW"
    assert eligibility["blockers"] == []
    assert any("NO_ELIGIBLE" in x for x in eligibility["informational_conditions"])


def test_4_approve_bound_to_evaluation_active_model_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    p = _wire_paths(tmp_path, monkeypatch)
    snaps = _healthy_snaps()
    before = p["active_model"].read_bytes()
    evidence = ev.build_promotion_evidence_snapshot(
        repo_root=tmp_path, active=ACTIVE, candidate=CANDIDATE, snapshots=snaps
    )
    eligibility = gate.evaluate_promotion_eligibility(evidence=evidence, config=GOV_CFG)
    evaluation = gate.build_evaluation_record(evidence=evidence, eligibility=eligibility)
    assert eligibility["eligibility_status"] == "ELIGIBLE_FOR_REVIEW"

    # Wrong evaluation id rejected
    with pytest.raises(ValueError, match="EVALUATION_ID_MISMATCH"):
        ledger.approve(
            decisions_path=p["decisions"],
            evaluation=evaluation,
            evidence=evidence,
            actor_id="tester",
            reason="bad id",
            expected_evaluation_id="EVAL_WRONG",
        )

    decision = ledger.approve(
        decisions_path=p["decisions"],
        evaluation=evaluation,
        evidence=evidence,
        actor_id="tester",
        reason="eligible review approve",
        expected_evaluation_id=evaluation["evaluation_id"],
    )
    assert decision["decision"] == "APPROVE"
    assert decision["evaluation_id"] == evaluation["evaluation_id"]
    assert decision["evidence_hash"] == evidence["evidence_hash"]
    assert p["active_model"].read_bytes() == before

    monkeypatch.setattr(mon, "read_active_runtime", lambda repo_root=None: ACTIVE)

    def _build(*, repo_root=None, active=None, candidate=None, snapshots=None):
        return ev.build_promotion_evidence_snapshot(
            repo_root=tmp_path,
            active=active or ACTIVE,
            candidate=CANDIDATE,
            snapshots=snaps,
        )

    monkeypatch.setattr(mon, "build_promotion_evidence_snapshot", _build)
    # Persist evaluation then run_once with approval
    mon.run_once(repo_root=tmp_path)
    # Manually ensure decision file used; run_once will see approval
    # Re-append same evaluation path already done inside run_once
    gate_snap = json.loads(p["latest_gate"].read_text(encoding="utf-8"))
    # Need decisions present for active_approval — already written
    # Re-run so monitor loads decisions
    gate_snap2 = mon.run_once(repo_root=tmp_path)
    assert gate_snap2["status"] == "APPROVED_FOR_PROMOTION"
    assert gate_snap2["promotion_execution_status"] == "DISABLED"
    assert gate_snap2["active_model_change_performed"] is False
    assert p["active_model"].read_bytes() == before
    assert gate_snap["active_model_change_performed"] is False


def test_5_evidence_change_makes_approval_stale_no_duplicate_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    p = _wire_paths(tmp_path, monkeypatch)
    snaps = _healthy_snaps()
    evidence = ev.build_promotion_evidence_snapshot(
        repo_root=tmp_path, active=ACTIVE, candidate=CANDIDATE, snapshots=snaps
    )
    eligibility = gate.evaluate_promotion_eligibility(evidence=evidence, config=GOV_CFG)
    evaluation = gate.build_evaluation_record(evidence=evidence, eligibility=eligibility)
    ledger.approve(
        decisions_path=p["decisions"],
        evaluation=evaluation,
        evidence=evidence,
        actor_id="tester",
        reason="approve then stale",
        expected_evaluation_id=evaluation["evaluation_id"],
    )
    monkeypatch.setattr(mon, "read_active_runtime", lambda repo_root=None: ACTIVE)

    def _build_ok(*, repo_root=None, active=None, candidate=None, snapshots=None):
        return ev.build_promotion_evidence_snapshot(
            repo_root=tmp_path,
            active=active or ACTIVE,
            candidate=CANDIDATE,
            snapshots=snaps,
        )

    monkeypatch.setattr(mon, "build_promotion_evidence_snapshot", _build_ok)
    mon.run_once(repo_root=tmp_path)
    assert json.loads(p["latest_gate"].read_text(encoding="utf-8"))["status"] == "APPROVED_FOR_PROMOTION"
    eval_count_1 = len(read_jsonl(p["evaluations"]))
    mon.run_once(repo_root=tmp_path)
    eval_count_2 = len(read_jsonl(p["evaluations"]))
    assert eval_count_2 == eval_count_1
    decisions_count_1 = len(read_jsonl(p["decisions"]))

    # Introduce critical drift → stale
    snaps_bad = _healthy_snaps(drift={"input_drift_status": "CRITICAL"})

    def _build_bad(*, repo_root=None, active=None, candidate=None, snapshots=None):
        return ev.build_promotion_evidence_snapshot(
            repo_root=tmp_path,
            active=active or ACTIVE,
            candidate=CANDIDATE,
            snapshots=snaps_bad,
        )

    monkeypatch.setattr(mon, "build_promotion_evidence_snapshot", _build_bad)
    stale_gate = mon.run_once(repo_root=tmp_path)
    assert stale_gate["status"] == "APPROVAL_STALE"
    assert stale_gate["approval_stale"] is True
    assert "INPUT_DRIFT_CRITICAL" in stale_gate["blockers"]
    assert len(read_jsonl(p["decisions"])) == decisions_count_1
    # New evidence → new evaluation once; second run no duplicate
    eval_count_3 = len(read_jsonl(p["evaluations"]))
    assert eval_count_3 == eval_count_1 + 1
    mon.run_once(repo_root=tmp_path)
    assert len(read_jsonl(p["evaluations"])) == eval_count_3


@pytest.mark.parametrize("closed_trades", [0, 19, 399])
def test_pre_400_closed_trades_block_promotion_only(tmp_path: Path, closed_trades: int):
    snaps = _healthy_snaps(
        behavioral={"status": "COLLECTING_OUTCOMES"},
        economic={"status": "COLLECTING_TRADES", "closed_trades": closed_trades},
        drift={
            "input_drift_status": "COLLECTING_BASELINE",
            "feature_drift_status": "COLLECTING_BASELINE",
            "context_drift_status": "COLLECTING_BASELINE",
            "performance_drift_status": "COLLECTING_BASELINE",
        },
    )
    evidence = ev.build_promotion_evidence_snapshot(
        repo_root=tmp_path, active=ACTIVE, candidate=CANDIDATE, snapshots=snaps
    )
    eligibility = gate.evaluate_promotion_eligibility(evidence=evidence, config=GOV_CFG)

    assert evidence["behavioral_validation_status"] == "COLLECTING_OUTCOMES"
    assert evidence["economic_validation_status"] == "COLLECTING_TRADES"
    assert evidence["closed_trades"] == closed_trades
    assert eligibility["gate_status"] == "BLOCKED"
    assert "CLOSED_TRADES_INSUFFICIENT" in eligibility["blockers"]
    assert eligibility["promotion_execution_enabled"] is False
