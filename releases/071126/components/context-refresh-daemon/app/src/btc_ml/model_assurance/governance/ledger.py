"""Immutable governance decision ledger (MODEL-8)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from btc_ml.model_assurance.toxic_box.common import (
    append_jsonl,
    canonical_json,
    read_jsonl,
    sha256_text,
    utc_now_iso,
)

ALLOWED_DECISIONS = frozenset({"APPROVE", "REJECT", "REVOKE"})


def decision_id_for(
    *,
    evaluation_id: str,
    decision: str,
    actor_id: str,
    decided_at: str,
    previous_decision_id: str | None = None,
) -> str:
    return "GDEC_" + sha256_text(
        canonical_json(
            {
                "evaluation_id": evaluation_id,
                "decision": decision,
                "actor_id": actor_id,
                "decided_at": decided_at,
                "previous_decision_id": previous_decision_id,
            }
        )
    )[:32]


def load_decisions(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def active_approval(decisions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Latest non-revoked APPROVE, if still active."""
    latest_approve: dict[str, Any] | None = None
    revoked_of: set[str] = set()
    for row in decisions:
        dec = str(row.get("decision") or "").upper()
        if dec == "REVOKE" and row.get("previous_decision_id"):
            revoked_of.add(str(row.get("previous_decision_id")))
        elif dec == "APPROVE":
            latest_approve = row
        elif dec == "REJECT":
            # Reject clears any prior approval for that evaluation lineage
            latest_approve = None
    if latest_approve and str(latest_approve.get("decision_id")) not in revoked_of:
        return latest_approve
    return None


def is_approval_stale(
    *,
    approval: dict[str, Any],
    evidence: dict[str, Any],
    eligibility: dict[str, Any],
) -> bool:
    if str(approval.get("evidence_hash") or "") != str(evidence.get("evidence_hash") or ""):
        return True
    if str(approval.get("evaluation_id") or "") != str(eligibility.get("evaluation_id") or ""):
        return True
    if str(approval.get("candidate_registry_record_id") or "") != str(
        evidence.get("candidate_registry_record_id") or ""
    ):
        return True
    if str(approval.get("candidate_runtime_fingerprint") or "") != str(
        evidence.get("candidate_runtime_fingerprint") or ""
    ):
        return True
    if str(evidence.get("candidate_status") or "") != "CANDIDATE_REGISTERED":
        return True
    if eligibility.get("blockers"):
        return True
    if eligibility.get("eligibility_status") != "ELIGIBLE_FOR_REVIEW" and eligibility.get(
        "gate_status"
    ) not in {"APPROVED_FOR_PROMOTION", "ELIGIBLE_FOR_REVIEW"}:
        # After approval, eligibility may still be ELIGIBLE; if newly blocked → stale
        if eligibility.get("blockers"):
            return True
    # New critical environment conditions after approval
    env = set(eligibility.get("environment_blockers") or [])
    if any(x.endswith("_CRITICAL") for x in env) or "EXTERNAL_DATA_NOT_HEALTHY" in env:
        # Only stale if these weren't present at approval time
        approved_env = set(approval.get("environment_blockers_at_decision") or [])
        if env - approved_env:
            return True
    return False


def record_decision(
    *,
    decisions_path: Path,
    evaluation: dict[str, Any],
    evidence: dict[str, Any],
    decision: str,
    actor_id: str,
    reason: str,
    previous_decision_id: str | None = None,
    existing_ids: set[str] | None = None,
) -> dict[str, Any]:
    decision_u = str(decision or "").upper()
    if decision_u not in ALLOWED_DECISIONS:
        raise ValueError(f"INVALID_DECISION:{decision}")
    if not str(actor_id or "").strip():
        raise ValueError("ACTOR_REQUIRED")
    if not str(reason or "").strip():
        raise ValueError("REASON_REQUIRED")

    decided_at = utc_now_iso()
    did = decision_id_for(
        evaluation_id=str(evaluation.get("evaluation_id")),
        decision=decision_u,
        actor_id=str(actor_id),
        decided_at=decided_at,
        previous_decision_id=previous_decision_id,
    )
    row = {
        "decision_id": did,
        "evaluation_id": evaluation.get("evaluation_id"),
        "evidence_hash": evidence.get("evidence_hash") or evaluation.get("evidence_hash"),
        "candidate_registry_record_id": evidence.get("candidate_registry_record_id")
        or evaluation.get("candidate_registry_record_id"),
        "candidate_model_id": evidence.get("candidate_model_id") or evaluation.get("candidate_model_id"),
        "candidate_model_version": evidence.get("candidate_model_version")
        or evaluation.get("candidate_model_version"),
        "candidate_runtime_fingerprint": evidence.get("candidate_runtime_fingerprint")
        or evaluation.get("candidate_runtime_fingerprint"),
        "decision": decision_u,
        "actor_id": str(actor_id),
        "reason": str(reason),
        "decision_source": "CLI_LOCAL",
        "decided_at": decided_at,
        "previous_decision_id": previous_decision_id,
        "environment_blockers_at_decision": list(
            evaluation.get("environment_blockers") or evidence.get("environment_blockers") or []
        ),
        "blockers_at_decision": list(evaluation.get("blockers") or []),
    }
    ids = existing_ids if existing_ids is not None else {str(r.get("decision_id")) for r in read_jsonl(decisions_path)}
    if did not in ids:
        append_jsonl(decisions_path, row)
        ids.add(did)
    return row


def approve(
    *,
    decisions_path: Path,
    evaluation: dict[str, Any],
    evidence: dict[str, Any],
    actor_id: str,
    reason: str,
    expected_evaluation_id: str,
) -> dict[str, Any]:
    if str(evaluation.get("evaluation_id")) != str(expected_evaluation_id):
        raise ValueError("EVALUATION_ID_MISMATCH")
    if str(evaluation.get("eligibility_status")) != "ELIGIBLE_FOR_REVIEW":
        raise ValueError("APPROVE_FORBIDDEN_NOT_ELIGIBLE")
    if str(evaluation.get("evidence_hash")) != str(evidence.get("evidence_hash")):
        raise ValueError("EVIDENCE_HASH_MISMATCH")
    if str(evaluation.get("candidate_runtime_fingerprint") or "") != str(
        evidence.get("candidate_runtime_fingerprint") or ""
    ):
        raise ValueError("CANDIDATE_FINGERPRINT_MISMATCH")
    return record_decision(
        decisions_path=decisions_path,
        evaluation=evaluation,
        evidence=evidence,
        decision="APPROVE",
        actor_id=actor_id,
        reason=reason,
    )


def reject(
    *,
    decisions_path: Path,
    evaluation: dict[str, Any],
    evidence: dict[str, Any],
    actor_id: str,
    reason: str,
    expected_evaluation_id: str,
) -> dict[str, Any]:
    if str(evaluation.get("evaluation_id")) != str(expected_evaluation_id):
        raise ValueError("EVALUATION_ID_MISMATCH")
    status = str(evaluation.get("eligibility_status") or evaluation.get("gate_status") or "")
    if status not in {"BLOCKED", "ELIGIBLE_FOR_REVIEW", "APPROVED_FOR_PROMOTION"}:
        raise ValueError("REJECT_FORBIDDEN_STATUS")
    return record_decision(
        decisions_path=decisions_path,
        evaluation=evaluation,
        evidence=evidence,
        decision="REJECT",
        actor_id=actor_id,
        reason=reason,
    )


def revoke(
    *,
    decisions_path: Path,
    evaluation: dict[str, Any],
    evidence: dict[str, Any],
    actor_id: str,
    reason: str,
    decision_id: str,
) -> dict[str, Any]:
    decisions = load_decisions(decisions_path)
    target = next((d for d in decisions if str(d.get("decision_id")) == str(decision_id)), None)
    if target is None or str(target.get("decision") or "").upper() != "APPROVE":
        raise ValueError("REVOKE_TARGET_NOT_ACTIVE_APPROVE")
    approval = active_approval(decisions)
    if approval is None or str(approval.get("decision_id")) != str(decision_id):
        raise ValueError("REVOKE_TARGET_NOT_ACTIVE_APPROVE")
    return record_decision(
        decisions_path=decisions_path,
        evaluation=evaluation,
        evidence=evidence,
        decision="REVOKE",
        actor_id=actor_id,
        reason=reason,
        previous_decision_id=str(decision_id),
    )
