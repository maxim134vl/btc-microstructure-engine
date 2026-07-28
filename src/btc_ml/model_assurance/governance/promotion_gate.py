"""Promotion gate eligibility evaluation (MODEL-8) — never executes promotion."""

from __future__ import annotations

from typing import Any

from btc_ml.model_assurance.toxic_box.common import canonical_json, sha256_text, utc_now_iso

DRIFT_BRANCHES = (
    ("input_drift_status", "INPUT_DRIFT"),
    ("feature_drift_status", "FEATURE_DRIFT"),
    ("context_drift_status", "CONTEXT_DRIFT"),
    ("performance_drift_status", "PERFORMANCE_DRIFT"),
)


def evaluation_id(
    *,
    active_registry_record_id: str | None,
    candidate_registry_record_id: str | None,
    evidence_hash: str,
) -> str:
    return "EVAL_" + sha256_text(
        canonical_json(
            {
                "active_registry_record_id": active_registry_record_id,
                "candidate_registry_record_id": candidate_registry_record_id,
                "evidence_hash": evidence_hash,
            }
        )
    )[:32]


def _drift_blockers(evidence: dict[str, Any], env_cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (candidate_blockers, environment_blockers) for drift statuses."""
    blockers: list[str] = []
    env_blockers: list[str] = []
    block_warn = bool(env_cfg.get("block_on_drift_warning", True))
    block_crit = bool(env_cfg.get("block_on_drift_critical", True))
    for field, prefix in DRIFT_BRANCHES:
        status = str(evidence.get(field) or "").upper()
        code = None
        if status == "CRITICAL" and block_crit:
            code = f"{prefix}_CRITICAL"
        elif status == "WARNING" and block_warn:
            code = f"{prefix}_WARNING"
        if not code:
            continue
        # Without a candidate these are environment blockers only
        if evidence.get("candidate_status") == "NONE_REGISTERED" or not evidence.get(
            "candidate_registry_record_id"
        ):
            env_blockers.append(code)
        else:
            blockers.append(code)
    return blockers, env_blockers


def evaluate_promotion_eligibility(
    *,
    evidence: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic eligibility from evidence + governance config."""
    env_cfg = config.get("environment") or {}
    shadow_cfg = config.get("shadow") or {}
    blockers: list[str] = []
    warnings: list[str] = []
    informational: list[str] = []
    environment_blockers: list[str] = []

    candidate_status = str(evidence.get("candidate_status") or "NONE_REGISTERED")
    has_candidate = bool(evidence.get("candidate_registry_record_id")) and candidate_status == (
        "CANDIDATE_REGISTERED"
    )

    if not evidence.get("active_registry_record_id"):
        blockers.append("ACTIVE_REGISTRY_INVALID")

    # Drift / environment always recorded
    drift_b, drift_env = _drift_blockers(evidence, env_cfg)
    blockers.extend(drift_b)
    environment_blockers.extend(drift_env)

    # External data
    ext = str(evidence.get("external_data_status") or "")
    if env_cfg.get("require_external_data_healthy", True) and ext and ext != "CURRENT_HEALTHY":
        if has_candidate:
            blockers.append("EXTERNAL_DATA_NOT_HEALTHY")
        else:
            environment_blockers.append("EXTERNAL_DATA_NOT_HEALTHY")

    # Toxicity / incidents / reconciliation
    if env_cfg.get("block_on_confirmed_critical_toxicity", True):
        if int(evidence.get("confirmed_critical_toxicity_count") or 0) > 0:
            (blockers if has_candidate else environment_blockers).append("CONFIRMED_CRITICAL_TOXICITY")
    if env_cfg.get("block_on_open_critical_incident", True):
        if int(evidence.get("open_critical_incident_count") or 0) > 0:
            (blockers if has_candidate else environment_blockers).append("OPEN_CRITICAL_INCIDENT")
    if env_cfg.get("block_on_pnl_reconciliation_mismatch", True):
        if int(evidence.get("pnl_reconciliation_mismatches") or 0) > 0:
            (blockers if has_candidate else environment_blockers).append("PNL_RECONCILIATION_MISMATCH")

    # Soft informational from BV/EV collecting states
    for label, status in (
        ("behavioral_validation_status", evidence.get("behavioral_validation_status")),
        ("economic_validation_status", evidence.get("economic_validation_status")),
    ):
        st = str(status or "")
        if st in {
            "NO_ELIGIBLE_CONTEXTS_YET",
            "NO_ELIGIBLE_TRADES_YET",
            "COLLECTING_BASELINE",
            "NO_ELIGIBLE_EVENTS_YET",
            "NO_ELIGIBLE_INCIDENTS_YET",
        }:
            informational.append(f"{label.upper()}={st}")

    if not has_candidate:
        return {
            "eligibility_status": "NOT_APPLICABLE",
            "gate_status": "NOT_APPLICABLE_NO_CANDIDATE",
            "blockers": [],
            "environment_blockers": sorted(set(environment_blockers)),
            "warnings": warnings,
            "informational_conditions": informational,
            "evaluation_id": evaluation_id(
                active_registry_record_id=evidence.get("active_registry_record_id"),
                candidate_registry_record_id=None,
                evidence_hash=str(evidence.get("evidence_hash") or ""),
            ),
            "promotion_execution_enabled": False,
            "active_model_change_performed": False,
            "evaluated_at": utc_now_iso(),
        }

    # Candidate-specific blockers
    if candidate_status != "CANDIDATE_REGISTERED":
        blockers.append("CANDIDATE_NOT_ACTIVE_IN_REGISTRY")
    if str(evidence.get("candidate_execution_capability") or "NONE") != "NONE":
        blockers.append("CANDIDATE_EXECUTION_CAPABILITY_PRESENT")
    if evidence.get("candidate_execution_enabled") is True:
        blockers.append("CANDIDATE_EXECUTION_CAPABILITY_PRESENT")
    if not evidence.get("candidate_adapter_module") or not evidence.get("candidate_adapter_class"):
        blockers.append("CANDIDATE_ADAPTER_UNAVAILABLE")

    shadow_status = str(evidence.get("shadow_status") or "")
    if shadow_status in {"NOT_APPLICABLE_NO_CANDIDATE", "NO_CANDIDATE_REGISTERED", ""}:
        blockers.append("SHADOW_NOT_RUNNING")
    elif shadow_status == "CANDIDATE_ADAPTER_UNAVAILABLE":
        blockers.append("CANDIDATE_ADAPTER_UNAVAILABLE")

    preds = int(evidence.get("shadow_predictions") or 0)
    cmps = int(evidence.get("shadow_comparisons") or 0)
    elapsed = float(evidence.get("shadow_elapsed_hours") or 0.0)
    not_eval = int(evidence.get("shadow_not_evaluable") or 0)
    min_preds = int(shadow_cfg.get("minimum_predictions", 1000))
    min_cmps = int(shadow_cfg.get("minimum_comparisons", 1000))
    min_hours = float(shadow_cfg.get("minimum_elapsed_hours", 168))
    max_ne_ratio = float(shadow_cfg.get("maximum_not_evaluable_ratio", 0.05))

    if preds < min_preds or cmps < min_cmps or elapsed < min_hours:
        blockers.append("SHADOW_EVIDENCE_INSUFFICIENT")
    denom = max(cmps, 1)
    if cmps > 0 and (not_eval / denom) > max_ne_ratio:
        blockers.append("SHADOW_NOT_EVALUABLE_RATIO_HIGH")
    if shadow_cfg.get("require_zero_execution_entities", True):
        if (
            int(evidence.get("shadow_orders_created") or 0) > 0
            or int(evidence.get("shadow_fills_created") or 0) > 0
            or int(evidence.get("shadow_positions_created") or 0) > 0
        ):
            blockers.append("SHADOW_EXECUTION_BREACH")

    blockers = sorted(set(blockers))
    environment_blockers = sorted(set(environment_blockers))
    if blockers:
        eligibility = "BLOCKED"
        gate_status = "BLOCKED"
    else:
        eligibility = "ELIGIBLE_FOR_REVIEW"
        gate_status = "ELIGIBLE_FOR_REVIEW"

    return {
        "eligibility_status": eligibility,
        "gate_status": gate_status,
        "blockers": blockers,
        "environment_blockers": environment_blockers,
        "warnings": warnings,
        "informational_conditions": informational,
        "evaluation_id": evaluation_id(
            active_registry_record_id=evidence.get("active_registry_record_id"),
            candidate_registry_record_id=evidence.get("candidate_registry_record_id"),
            evidence_hash=str(evidence.get("evidence_hash") or ""),
        ),
        "promotion_execution_enabled": False,
        "active_model_change_performed": False,
        "evaluated_at": utc_now_iso(),
    }


def build_evaluation_record(
    *,
    evidence: dict[str, Any],
    eligibility: dict[str, Any],
) -> dict[str, Any]:
    return {
        "evaluation_id": eligibility["evaluation_id"],
        "evidence_snapshot_id": evidence.get("evidence_snapshot_id"),
        "evidence_hash": evidence.get("evidence_hash"),
        "active_registry_record_id": evidence.get("active_registry_record_id"),
        "candidate_registry_record_id": evidence.get("candidate_registry_record_id"),
        "candidate_model_id": evidence.get("candidate_model_id"),
        "candidate_model_version": evidence.get("candidate_model_version"),
        "candidate_runtime_fingerprint": evidence.get("candidate_runtime_fingerprint"),
        "eligibility_status": eligibility.get("eligibility_status"),
        "blockers": list(eligibility.get("blockers") or []),
        "environment_blockers": list(eligibility.get("environment_blockers") or []),
        "warnings": list(eligibility.get("warnings") or []),
        "informational_conditions": list(eligibility.get("informational_conditions") or []),
        "evaluated_at": eligibility.get("evaluated_at") or utc_now_iso(),
        "promotion_execution_enabled": False,
        "active_model_change_performed": False,
    }
