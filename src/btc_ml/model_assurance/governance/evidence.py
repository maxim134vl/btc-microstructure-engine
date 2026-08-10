"""Canonical promotion evidence snapshot (MODEL-8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from btc_ml.model_assurance.registry import read_active_runtime, read_candidate
from btc_ml.model_assurance.toxic_box.common import (
    canonical_json,
    load_json,
    sha256_text,
    utc_now_iso,
)

# Fields excluded from evidence_hash (volatile / non-gate-relevant).
_EXCLUDED_FROM_HASH = frozenset(
    {
        "captured_at",
        "evidence_snapshot_id",
        "pid",
        "updated_at",
        "health_updated_at",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def snapshot_paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance"
    return {
        "active": base / "registry" / "active" / "active_model.json",
        "shadow": base / "shadow" / "snapshots" / "latest_summary.json",
        "drift": base / "drift" / "snapshots" / "latest_summary.json",
        "external": base / "toxic_box" / "external_data" / "snapshots" / "latest_summary.json",
        "toxicity_current": base / "toxic_box" / "current" / "snapshots" / "latest_summary.json",
        "incidents": base / "toxic_box" / "incidents" / "snapshots" / "latest_summary.json",
        "behavioral": base / "behavioral_validation" / "snapshots" / "latest_summary.json",
        "economic": base / "economic_validation" / "snapshots" / "latest_summary.json",
        "config": root / "config" / "model_assurance_governance.json",
    }


def load_governance_config(repo_root: Path | None = None) -> dict[str, Any]:
    return json.loads(snapshot_paths(repo_root)["config"].read_text(encoding="utf-8"))


def _stable_snapshot_ts(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    # Prefer non-heartbeat timestamps when available
    for key in ("last_evaluated_at", "last_shadow_prediction_at", "last_incident_at", "last_resolved_at"):
        if payload.get(key):
            return str(payload.get(key))
    return None


def evidence_hash_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in snapshot.items() if k not in _EXCLUDED_FROM_HASH}


def compute_evidence_hash(snapshot: dict[str, Any]) -> str:
    return sha256_text(canonical_json(evidence_hash_payload(snapshot)))


def evidence_snapshot_id(evidence_hash: str) -> str:
    return "EVID_" + evidence_hash[:32]


def build_promotion_evidence_snapshot(
    *,
    repo_root: Path | None = None,
    active: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    snapshots: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    root = repo_root or _repo_root()
    paths = snapshot_paths(root)
    active = active if active is not None else read_active_runtime(repo_root=root)
    candidate = candidate if candidate is not None else read_candidate(repo_root=root)
    if candidate and str(candidate.get("record_status") or "") != "CANDIDATE_REGISTERED":
        candidate = None

    if snapshots is None:
        snapshots = {
            "shadow": load_json(paths["shadow"]),
            "drift": load_json(paths["drift"]),
            "external": load_json(paths["external"]),
            "toxicity_current": load_json(paths["toxicity_current"]),
            "incidents": load_json(paths["incidents"]),
            "behavioral": load_json(paths["behavioral"]),
            "economic": load_json(paths["economic"]),
        }

    shadow = snapshots.get("shadow") or {}
    drift = snapshots.get("drift") or {}
    external = snapshots.get("external") or {}
    toxicity = snapshots.get("toxicity_current") or {}
    incidents = snapshots.get("incidents") or {}
    behavioral = snapshots.get("behavioral") or {}
    economic = snapshots.get("economic") or {}

    comparisons = int(shadow.get("comparisons") or shadow.get("shadow_comparisons") or 0)
    not_eval = int(shadow.get("shadow_not_evaluable") or shadow.get("not_evaluable") or 0)
    preds = int(shadow.get("shadow_predictions") or 0)

    body = {
        "active_registry_record_id": (active or {}).get("registry_record_id"),
        "active_model_id": (active or {}).get("model_id"),
        "active_model_version": (active or {}).get("model_version"),
        "active_runtime_fingerprint": (active or {}).get("runtime_fingerprint"),
        "candidate_registry_record_id": (candidate or {}).get("registry_record_id"),
        "candidate_model_id": (candidate or {}).get("model_id"),
        "candidate_model_version": (candidate or {}).get("model_version"),
        "candidate_runtime_fingerprint": (candidate or {}).get("runtime_fingerprint"),
        "candidate_status": (
            (candidate or {}).get("record_status") if candidate else "NONE_REGISTERED"
        ),
        "candidate_execution_capability": (candidate or {}).get("execution_capability"),
        "candidate_execution_enabled": (candidate or {}).get("execution_enabled"),
        "candidate_adapter_module": (candidate or {}).get("adapter_module"),
        "candidate_adapter_class": (candidate or {}).get("adapter_class"),
        "shadow_status": shadow.get("shadow_status") or shadow.get("status"),
        "shadow_inputs": int(shadow.get("shadow_inputs") or 0),
        "shadow_predictions": preds,
        "shadow_comparisons": comparisons,
        "shadow_not_evaluable": not_eval,
        "shadow_elapsed_hours": float(shadow.get("shadow_elapsed_hours") or 0.0),
        "shadow_orders_created": int(shadow.get("shadow_created_orders") or 0),
        "shadow_fills_created": int(shadow.get("shadow_created_fills") or 0),
        "shadow_positions_created": int(shadow.get("shadow_created_positions") or 0),
        "external_data_status": external.get("status"),
        "input_drift_status": drift.get("input_drift_status"),
        "feature_drift_status": drift.get("feature_drift_status"),
        "context_drift_status": drift.get("context_drift_status"),
        "performance_drift_status": drift.get("performance_drift_status"),
        "current_toxicity_status": toxicity.get("status"),
        "confirmed_critical_toxicity_count": (
            max(
                1,
                int(toxicity.get("context_confirmed_events") or 0)
                + int(toxicity.get("trade_confirmed_events") or 0),
            )
            if str(toxicity.get("status") or "") == "CURRENT_CRITICAL"
            else 0
        ),
        "incident_status": incidents.get("status"),
        "open_critical_incident_count": (
            int(incidents.get("critical_incidents") or 0)
            if int(incidents.get("open_incidents") or 0) > 0
            else 0
        ),
        "behavioral_validation_status": behavioral.get("status"),
        "economic_validation_status": economic.get("status"),
        "closed_trades": int(economic.get("closed_trades") or 0),
        "pnl_reconciliation_mismatches": int(
            economic.get("pnl_reconciliation_mismatches")
            or (economic.get("counts_by_reconciliation") or {}).get("MISMATCH")
            or 0
        ),
        "source_snapshot_timestamps": {
            "shadow": _stable_snapshot_ts(shadow),
            "drift": _stable_snapshot_ts(drift),
            "external": _stable_snapshot_ts(external),
            "toxicity_current": _stable_snapshot_ts(toxicity),
            "incidents": _stable_snapshot_ts(incidents),
            "behavioral": _stable_snapshot_ts(behavioral),
            "economic": _stable_snapshot_ts(economic),
        },
    }

    ehash = compute_evidence_hash(body)
    snapshot = {
        **body,
        "evidence_hash": ehash,
        "evidence_snapshot_id": evidence_snapshot_id(ehash),
        "captured_at": utc_now_iso(),
    }
    return snapshot
