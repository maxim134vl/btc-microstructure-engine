"""Promotion gate orchestrator (MODEL-8) — evaluation only, never promotes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from btc_ml.model_assurance.governance.evidence import (
    build_promotion_evidence_snapshot,
    load_governance_config,
)
from btc_ml.model_assurance.governance.ledger import (
    active_approval,
    is_approval_stale,
    load_decisions,
)
from btc_ml.model_assurance.governance.promotion_gate import (
    build_evaluation_record,
    evaluate_promotion_eligibility,
)
from btc_ml.model_assurance.registry import read_active_runtime
from btc_ml.model_assurance.toxic_box.common import (
    append_jsonl,
    atomic_write_json,
    read_jsonl,
    utc_now_iso,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "governance"
    return {
        "evidence": base / "evidence" / "evidence_snapshots.jsonl",
        "evaluations": base / "evaluations" / "promotion_evaluations.jsonl",
        "decisions": base / "decisions" / "governance_decisions.jsonl",
        "latest_gate": base / "snapshots" / "latest_gate.json",
        "latest_governance": base / "snapshots" / "latest_governance.json",
        "checkpoint": base / "runtime" / "checkpoint.json",
        "health": base / "runtime" / "health.json",
        "active_model": root / "data" / "model_assurance" / "registry" / "active" / "active_model.json",
    }


def _persist_unique(path: Path, row: dict[str, Any], *, id_field: str, existing: set[str]) -> bool:
    rid = str(row.get(id_field) or "")
    if not rid or rid in existing:
        return False
    append_jsonl(path, row)
    existing.add(rid)
    return True


def resolve_gate_status(
    *,
    eligibility: dict[str, Any],
    approval: dict[str, Any] | None,
    approval_stale: bool,
) -> tuple[str, str]:
    """Return (gate_status, governance_status)."""
    base = str(eligibility.get("gate_status") or "NOT_APPLICABLE_NO_CANDIDATE")
    if approval is None:
        return base, "NONE"
    if approval_stale:
        return "APPROVAL_STALE", "APPROVAL_STALE"
    if str(approval.get("decision") or "").upper() == "APPROVE":
        if base == "ELIGIBLE_FOR_REVIEW":
            return "APPROVED_FOR_PROMOTION", "APPROVED"
        # If somehow blocked after approve, treat as stale (caller should set stale)
        return "APPROVAL_STALE", "APPROVAL_STALE"
    return base, "NONE"


def build_latest_gate(
    *,
    active: dict[str, Any] | None,
    evidence: dict[str, Any],
    eligibility: dict[str, Any],
    approval: dict[str, Any] | None,
    approval_stale: bool,
) -> dict[str, Any]:
    gate_status, gov_status = resolve_gate_status(
        eligibility=eligibility, approval=approval, approval_stale=approval_stale
    )
    # Latest reject?
    if approval is None and gov_status == "NONE":
        pass
    return {
        "status": gate_status,
        "runtime_impact": "NONE",
        "promotion_control": "BLOCKING",
        "active_model_id": (active or {}).get("model_id") or evidence.get("active_model_id"),
        "active_model_version": (active or {}).get("model_version") or evidence.get("active_model_version"),
        "active_registry_record_id": evidence.get("active_registry_record_id"),
        "candidate_status": evidence.get("candidate_status"),
        "candidate_model_id": evidence.get("candidate_model_id"),
        "candidate_model_version": evidence.get("candidate_model_version"),
        "candidate_registry_record_id": evidence.get("candidate_registry_record_id"),
        "eligibility_status": eligibility.get("eligibility_status"),
        "governance_status": gov_status if approval else (
            "REJECTED"
            if False
            else "NONE"
        ),
        "promotion_execution_status": "DISABLED",
        "blockers": list(eligibility.get("blockers") or []),
        "environment_blockers": list(eligibility.get("environment_blockers") or []),
        "warnings": list(eligibility.get("warnings") or []),
        "informational_conditions": list(eligibility.get("informational_conditions") or []),
        "evidence_snapshot_id": evidence.get("evidence_snapshot_id"),
        "evidence_hash": evidence.get("evidence_hash"),
        "evaluation_id": eligibility.get("evaluation_id"),
        "active_decision_id": (approval or {}).get("decision_id") if approval and not approval_stale else None,
        "active_decision": (approval or {}).get("decision") if approval and not approval_stale else None,
        "decision_actor": (approval or {}).get("actor_id") if approval and not approval_stale else None,
        "decision_reason": (approval or {}).get("reason") if approval and not approval_stale else None,
        "decision_at": (approval or {}).get("decided_at") if approval and not approval_stale else None,
        "approval_stale": bool(approval_stale) if approval else False,
        "active_model_change_performed": False,
        "last_evaluated_at": eligibility.get("evaluated_at"),
        "updated_at": utc_now_iso(),
    }


def run_once(*, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    p = paths(root)
    config = load_governance_config(root)
    active = read_active_runtime(repo_root=root)
    # Capture active model bytes for change detection
    active_before = None
    if p["active_model"].exists():
        active_before = p["active_model"].read_bytes()

    evidence = build_promotion_evidence_snapshot(repo_root=root, active=active)
    eligibility = evaluate_promotion_eligibility(evidence=evidence, config=config)
    evaluation = build_evaluation_record(evidence=evidence, eligibility=eligibility)

    existing_ev = {str(r.get("evidence_snapshot_id")) for r in read_jsonl(p["evidence"])}
    existing_eval = {str(r.get("evaluation_id")) for r in read_jsonl(p["evaluations"])}
    _persist_unique(p["evidence"], evidence, id_field="evidence_snapshot_id", existing=existing_ev)
    _persist_unique(p["evaluations"], evaluation, id_field="evaluation_id", existing=existing_eval)

    decisions = load_decisions(p["decisions"])
    # Track latest REJECT for governance_status
    latest_reject = None
    for row in decisions:
        if str(row.get("decision") or "").upper() == "REJECT":
            latest_reject = row
    approval = active_approval(decisions)
    approval_stale = False
    if approval is not None:
        approval_stale = is_approval_stale(
            approval=approval, evidence=evidence, eligibility=eligibility
        )
        # Also stale if blockers appeared
        if eligibility.get("blockers"):
            approval_stale = True

    gate = build_latest_gate(
        active=active,
        evidence=evidence,
        eligibility=eligibility,
        approval=approval,
        approval_stale=approval_stale,
    )
    if approval is None and latest_reject is not None:
        # Show rejected only if reject targets current evaluation lineage
        if str(latest_reject.get("evaluation_id")) == str(evaluation.get("evaluation_id")):
            gate["governance_status"] = "REJECTED"
            gate["active_decision_id"] = latest_reject.get("decision_id")
            gate["active_decision"] = "REJECT"
            gate["decision_actor"] = latest_reject.get("actor_id")
            gate["decision_reason"] = latest_reject.get("reason")
            gate["decision_at"] = latest_reject.get("decided_at")
            if gate["status"] not in {"NOT_APPLICABLE_NO_CANDIDATE"}:
                gate["status"] = "REJECTED"

    atomic_write_json(p["latest_gate"], gate)
    atomic_write_json(
        p["latest_governance"],
        {
            "decisions_count": len(decisions),
            "active_decision_id": gate.get("active_decision_id"),
            "active_decision": gate.get("active_decision"),
            "approval_stale": gate.get("approval_stale"),
            "promotion_execution_status": "DISABLED",
            "promotion_execution_enabled": False,
            "updated_at": utc_now_iso(),
        },
    )

    active_after = p["active_model"].read_bytes() if p["active_model"].exists() else None
    changed = active_before != active_after
    atomic_write_json(
        p["checkpoint"],
        {
            "evaluation_id": evaluation.get("evaluation_id"),
            "evidence_hash": evidence.get("evidence_hash"),
            "gate_status": gate.get("status"),
            "active_model_changed": changed,
            "updated_at": utc_now_iso(),
        },
    )
    atomic_write_json(
        p["health"],
        {
            "status": gate.get("status"),
            "alive": True,
            "runtime_impact": "NONE",
            "promotion_control": "BLOCKING",
            "promotion_execution_status": "DISABLED",
            "pid": os.getpid(),
            "candidate_status": gate.get("candidate_status"),
            "environment_blockers": gate.get("environment_blockers"),
            "paper_only": (active or {}).get("paper_only", True),
            "real_execution": (active or {}).get("real_execution", False),
            "active_model_change_performed": False,
            "updated_at": utc_now_iso(),
        },
    )
    gate["active_model_file_changed"] = changed
    return gate
