"""Unified Model Assurance summary (MODEL-9) — observational, read-only aggregation."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_ml.model_assurance.toxic_box.common import atomic_write_json, load_json, parse_ts, utc_now_iso

SCHEMA_VERSION = "model_assurance_summary_v1"

NOT_APPLICABLE_STATUSES = frozenset(
    {
        "NO_ELIGIBLE_CONTEXTS_YET",
        "NO_ELIGIBLE_TRADES_YET",
        "NO_ELIGIBLE_EVENTS_YET",
        "NO_ELIGIBLE_INCIDENTS_YET",
        "NO_CANDIDATE_REGISTERED",
        "NOT_APPLICABLE_NO_CANDIDATE",
        "NONE_REGISTERED",
        "NOT_APPLICABLE",
        "COLLECTING_BASELINE",
    }
)

CRITICAL_TOKENS = frozenset({"CRITICAL", "CURRENT_CRITICAL"})
WARNING_TOKENS = frozenset({"WARNING", "CURRENT_WARNING", "DEGRADED", "CURRENT_DEGRADED"})
WATCH_TOKENS = frozenset(
    {
        "WATCH",
        "CURRENT_WATCH",
        "COLLECTING_BASELINE",
        "COLLECTING",
        "NO_ELIGIBLE_CONTEXTS_YET",
        "NO_ELIGIBLE_TRADES_YET",
        "NO_ELIGIBLE_EVENTS_YET",
        "NO_ELIGIBLE_INCIDENTS_YET",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def summary_paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance"
    return {
        "config": root / "config" / "model_assurance_summary.json",
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


def load_summary_config(repo_root: Path | None = None) -> dict[str, Any]:
    path = summary_paths(repo_root)["config"]
    return json.loads(path.read_text(encoding="utf-8"))


def _age_seconds(ts: str | None, *, now: datetime | None = None) -> float | None:
    stamp = parse_ts(ts)
    if stamp is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - stamp).total_seconds())


def _module_envelope(
    *,
    module_id: str,
    status: str | None,
    health_status: str,
    runtime_impact: str,
    summary: dict[str, Any],
    updated_at: str | None,
    source_path: str,
) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "status": status,
        "health_status": health_status,
        "runtime_impact": runtime_impact,
        "summary": summary,
        "updated_at": updated_at,
        "source_path": source_path,
    }


def classify_service_health(
    *,
    health: dict[str, Any] | None,
    health_path: Path,
    stale_after_seconds: float,
    now: datetime | None = None,
) -> str:
    if health is None:
        return "STOPPED" if not health_path.exists() else "STOPPED"
    if health.get("alive") is False:
        return "STOPPED"
    age = _age_seconds(health.get("updated_at"), now=now)
    if age is None:
        return "ALIVE_STALE"
    if age > float(stale_after_seconds):
        return "ALIVE_STALE"
    return "ALIVE_FRESH"


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _list_or_empty(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return []


def build_unified_summary(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    overrides: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Aggregate current snapshots into one canonical Model Assurance summary."""
    root = repo_root or _repo_root()
    paths = summary_paths(root)
    config = load_summary_config(root)
    current = now or datetime.now(timezone.utc)
    default_stale = float(config.get("source_stale_after_seconds", 30))
    registry_stale = float(config.get("registry_stale_after_seconds", 3600))
    module_fresh = dict(config.get("module_freshness_seconds") or {})

    def _load(key: str) -> dict[str, Any] | None:
        if overrides and key in overrides:
            return overrides[key]
        return load_json(paths[key])

    missing_sources: list[str] = []
    stale_sources: list[str] = []
    source_snapshot_timestamps: dict[str, str | None] = {}
    warnings: list[str] = []
    informational: list[str] = []
    promotion_blockers: list[str] = []
    environment_blockers: list[str] = []

    def _track_file(
        label: str,
        path: Path,
        payload: dict[str, Any] | None,
        *,
        stale_after: float,
        track_age_stale: bool = True,
    ) -> None:
        if payload is None:
            missing_sources.append(label)
            source_snapshot_timestamps[label] = None
            return
        ts = (
            payload.get("updated_at")
            or payload.get("last_evaluated_at")
            or payload.get("generated_at")
            or payload.get("captured_at")
        )
        source_snapshot_timestamps[label] = str(ts) if ts else None
        if not track_age_stale:
            _ = path
            return
        age = _age_seconds(str(ts) if ts else None, now=current)
        if age is not None and age > stale_after:
            stale_sources.append(label)
        _ = path

    active = _load("active")
    registry_status = _load("registry_status")
    # Registry pointers are not heartbeat files — existence only, never age-stale.
    _track_file("active_model", paths["active"], active, stale_after=registry_stale, track_age_stale=False)
    _track_file(
        "registry_status",
        paths["registry_status"],
        registry_status,
        stale_after=registry_stale,
        track_age_stale=False,
    )
    active_runtime = {
        "status": (registry_status or {}).get("status") or ("ACTIVE_REGISTERED" if active else "MISSING_SOURCE"),
        "registry_record_id": (active or {}).get("registry_record_id")
        or (registry_status or {}).get("active_registry_record_id"),
        "model_id": (active or {}).get("model_id") or (registry_status or {}).get("active_model_id"),
        "model_version": (active or {}).get("model_version") or (registry_status or {}).get("active_model_version"),
        "model_type": (active or {}).get("model_type"),
        "runtime_fingerprint": (active or {}).get("runtime_fingerprint")
        or (registry_status or {}).get("runtime_fingerprint"),
        "paper_epoch_id": (active or {}).get("paper_epoch_id") or (registry_status or {}).get("paper_epoch_id"),
        "paper_epoch_activated_at": (active or {}).get("paper_epoch_activated_at"),
        "paper_only": bool((active or {}).get("paper_only", True)),
        "real_execution": bool((active or {}).get("real_execution", False)),
    }

    # --- modules ---
    bv = _load("bv_summary")
    bv_h = _load("bv_health")
    _track_file("behavioral_validation", paths["bv_summary"], bv, stale_after=float(module_fresh.get("behavioral_validation", default_stale)))
    bv_health_status = classify_service_health(
        health=bv_h,
        health_path=paths["bv_health"],
        stale_after_seconds=float(module_fresh.get("behavioral_validation", default_stale)),
        now=current,
    )
    bv_status = (bv or {}).get("status") if bv is not None else "MISSING_SOURCE"
    if bv is None:
        bv_status = "MISSING_SOURCE"
    if bv_status in NOT_APPLICABLE_STATUSES:
        informational.append(f"behavioral_validation={bv_status}")
    behavioral_validation = _module_envelope(
        module_id="MODEL-1",
        status=bv_status,
        health_status=bv_health_status,
        runtime_impact="NON_BLOCKING",
        summary={
            "eligible_contexts": int((bv or {}).get("eligible_contexts") or 0),
            "open_predictions": int((bv or {}).get("open_predictions") or (bv_h or {}).get("open_predictions") or 0),
            "closed_predictions": int((bv or {}).get("closed_predictions") or 0),
            "evaluated_outcomes": int((bv or {}).get("evaluated_outcomes") or 0),
            "pending_outcomes": int((bv or {}).get("pending_outcomes") or (bv_h or {}).get("pending_outcomes") or 0),
        },
        updated_at=(bv_h or {}).get("updated_at") or (bv or {}).get("updated_at"),
        source_path=_rel(paths["bv_summary"], root),
    )

    ext = _load("ext_summary")
    ext_h = _load("ext_health")
    _track_file("external_data", paths["ext_summary"], ext, stale_after=float(module_fresh.get("external_data", default_stale)))
    ext_health_status = classify_service_health(
        health=ext_h,
        health_path=paths["ext_health"],
        stale_after_seconds=float(module_fresh.get("external_data", default_stale)),
        now=current,
    )
    ext_status = (ext or {}).get("status") if ext else ("MISSING_SOURCE" if "external_data" in missing_sources else None)
    external_data = _module_envelope(
        module_id="MODEL-2",
        status=ext_status,
        health_status=ext_health_status,
        runtime_impact="NON_BLOCKING",
        summary={
            "configured_sources": int((ext or {}).get("configured_sources") or 0),
            "healthy_sources": int((ext or {}).get("healthy_sources") or 0),
            "degraded_sources": int((ext or {}).get("degraded_sources") or 0),
            "unavailable_sources": int((ext or {}).get("unavailable_sources") or (ext_h or {}).get("unavailable_sources") or 0),
            "open_events": int((ext or {}).get("open_events") or 0),
        },
        updated_at=(ext_h or {}).get("updated_at") or (ext or {}).get("updated_at"),
        source_path=_rel(paths["ext_summary"], root),
    )

    ev = _load("ev_summary")
    ev_h = _load("ev_health")
    _track_file("economic_validation", paths["ev_summary"], ev, stale_after=float(module_fresh.get("economic_validation", default_stale)))
    ev_health_status = classify_service_health(
        health=ev_h,
        health_path=paths["ev_health"],
        stale_after_seconds=float(module_fresh.get("economic_validation", default_stale)),
        now=current,
    )
    ev_status = (ev or {}).get("status") if ev else ("MISSING_SOURCE" if "economic_validation" in missing_sources else None)
    if ev_status in NOT_APPLICABLE_STATUSES:
        informational.append(f"economic_validation={ev_status}")
    recon = (ev or {}).get("counts_by_reconciliation") or {}
    economic_validation = _module_envelope(
        module_id="MODEL-3",
        status=ev_status,
        health_status=ev_health_status,
        runtime_impact="NON_BLOCKING",
        summary={
            "closed_trades": int((ev or {}).get("closed_trades") or 0),
            "open_positions": int((ev or {}).get("open_positions") or (ev_h or {}).get("open_positions") or 0),
            "evaluated_trades": int((ev or {}).get("evaluated_trades") or 0),
            "gross_pnl_usd": float((ev or {}).get("gross_pnl_usd") or 0.0),
            "net_pnl_usd": float((ev or {}).get("net_pnl_usd") or 0.0),
            "matched_reconciliations": int(
                (ev or {}).get("matched_reconciliations") or recon.get("MATCH") or 0
            ),
            "mismatched_reconciliations": int(
                (ev or {}).get("mismatched_reconciliations")
                or (ev_h or {}).get("mismatched_reconciliations")
                or recon.get("MISMATCH")
                or 0
            ),
        },
        updated_at=(ev_h or {}).get("updated_at") or (ev or {}).get("last_evaluated_at"),
        source_path=_rel(paths["ev_summary"], root),
    )

    tox = _load("tox_summary")
    tox_h = _load("tox_health")
    _track_file("current_toxicity", paths["tox_summary"], tox, stale_after=float(module_fresh.get("current_toxicity", default_stale)))
    tox_health_status = classify_service_health(
        health=tox_h,
        health_path=paths["tox_health"],
        stale_after_seconds=float(module_fresh.get("current_toxicity", default_stale)),
        now=current,
    )
    tox_status = (tox or {}).get("status") if tox else ("MISSING_SOURCE" if "current_toxicity" in missing_sources else None)
    if tox_status in NOT_APPLICABLE_STATUSES:
        informational.append(f"current_toxicity={tox_status}")
    current_toxicity = _module_envelope(
        module_id="MODEL-4",
        status=tox_status,
        health_status=tox_health_status,
        runtime_impact="NON_BLOCKING",
        summary={
            "context_toxic_candidates": int((tox or {}).get("context_toxic_candidates") or 0),
            "context_confirmed_events": int((tox or {}).get("context_confirmed_events") or 0),
            "trade_toxic_candidates": int((tox or {}).get("trade_toxic_candidates") or 0),
            "trade_confirmed_events": int((tox or {}).get("trade_confirmed_events") or 0),
            "not_evaluable_checks": int((tox or {}).get("not_evaluable_checks") or 0),
        },
        updated_at=(tox_h or {}).get("updated_at"),
        source_path=_rel(paths["tox_summary"], root),
    )

    inc = _load("inc_summary")
    inc_h = _load("inc_health")
    _track_file("incident_correlation", paths["inc_summary"], inc, stale_after=float(module_fresh.get("incident_correlation", default_stale)))
    inc_health_status = classify_service_health(
        health=inc_h,
        health_path=paths["inc_health"],
        stale_after_seconds=float(module_fresh.get("incident_correlation", default_stale)),
        now=current,
    )
    inc_status = (inc or {}).get("status") if inc else ("MISSING_SOURCE" if "incident_correlation" in missing_sources else None)
    if inc_status in NOT_APPLICABLE_STATUSES:
        informational.append(f"incident_correlation={inc_status}")
    incident_correlation = _module_envelope(
        module_id="MODEL-5",
        status=inc_status,
        health_status=inc_health_status,
        runtime_impact="NON_BLOCKING",
        summary={
            "distinct_incidents": int((inc or {}).get("distinct_incidents") or 0),
            "cross_branch_incidents": int((inc or {}).get("cross_branch_incidents") or 0),
            "single_branch_incidents": int((inc or {}).get("single_branch_incidents") or 0),
            "open_incidents": int((inc or {}).get("open_incidents") or 0),
            "economic_harm_usd": float((inc or {}).get("economic_harm_usd") or 0.0),
        },
        updated_at=(inc_h or {}).get("updated_at"),
        source_path=_rel(paths["inc_summary"], root),
    )

    drift = _load("drift_summary")
    drift_h = _load("drift_health")
    _track_file("drift_monitoring", paths["drift_summary"], drift, stale_after=float(module_fresh.get("drift_monitoring", default_stale)))
    drift_health_status = classify_service_health(
        health=drift_h,
        health_path=paths["drift_health"],
        stale_after_seconds=float(module_fresh.get("drift_monitoring", default_stale)),
        now=current,
    )
    drift_status = (drift or {}).get("status") if drift else ("MISSING_SOURCE" if "drift_monitoring" in missing_sources else None)
    input_drift = str((drift or {}).get("input_drift_status") or "")
    feature_drift = str((drift or {}).get("feature_drift_status") or "")
    context_drift = str((drift or {}).get("context_drift_status") or "")
    performance_drift = str((drift or {}).get("performance_drift_status") or "")
    drift_monitoring = _module_envelope(
        module_id="MODEL-6",
        status=drift_status,
        health_status=drift_health_status,
        runtime_impact="NON_BLOCKING",
        summary={
            "input_drift_status": input_drift or None,
            "feature_drift_status": feature_drift or None,
            "context_drift_status": context_drift or None,
            "performance_drift_status": performance_drift or None,
            "frozen_baselines": int((drift or {}).get("frozen_baselines") or 0),
            "watch_metrics": _list_or_empty((drift or {}).get("watch_metrics")),
            "warning_metrics": _list_or_empty((drift or {}).get("warning_metrics")),
            "critical_metrics": _list_or_empty((drift or {}).get("critical_metrics")),
            "suppressed_metrics": _list_or_empty((drift or {}).get("suppressed_metrics")),
        },
        updated_at=(drift_h or {}).get("updated_at"),
        source_path=_rel(paths["drift_summary"], root),
    )

    shadow = _load("shadow_summary")
    shadow_h = _load("shadow_health")
    _track_file("candidate_shadow", paths["shadow_summary"], shadow, stale_after=float(module_fresh.get("candidate_shadow", default_stale)))
    shadow_health_status = classify_service_health(
        health=shadow_h,
        health_path=paths["shadow_health"],
        stale_after_seconds=float(module_fresh.get("candidate_shadow", default_stale)),
        now=current,
    )
    cand_status = (shadow or {}).get("candidate_status") or "NONE_REGISTERED"
    shadow_status = (shadow or {}).get("shadow_status") or (shadow or {}).get("status")
    if cand_status in NOT_APPLICABLE_STATUSES or str(shadow_status) in NOT_APPLICABLE_STATUSES:
        informational.append(f"candidate_shadow={cand_status}/{shadow_status}")
    candidate_shadow = _module_envelope(
        module_id="MODEL-7",
        status=str(shadow_status) if shadow else ("MISSING_SOURCE" if "candidate_shadow" in missing_sources else None),
        health_status=shadow_health_status,
        runtime_impact="NON_BLOCKING",
        summary={
            "candidate_status": cand_status,
            "candidate_model_id": (shadow or {}).get("candidate_model_id"),
            "candidate_model_version": (shadow or {}).get("candidate_model_version"),
            "shadow_status": shadow_status,
            "shadow_inputs": int((shadow or {}).get("shadow_inputs") or 0),
            "shadow_predictions": int((shadow or {}).get("shadow_predictions") or 0),
            "comparisons": int((shadow or {}).get("comparisons") or 0),
            "agreement_rate": (shadow or {}).get("agreement_rate"),
        },
        updated_at=(shadow_h or {}).get("updated_at"),
        source_path=_rel(paths["shadow_summary"], root),
    )

    gate = _load("gate_summary")
    gate_h = _load("gate_health")
    _track_file("governance_promotion", paths["gate_summary"], gate, stale_after=float(module_fresh.get("governance_promotion", default_stale)))
    gate_health_status = classify_service_health(
        health=gate_h,
        health_path=paths["gate_health"],
        stale_after_seconds=float(module_fresh.get("governance_promotion", default_stale)),
        now=current,
    )
    gate_blockers = _list_or_empty((gate or {}).get("blockers"))
    gate_env = _list_or_empty((gate or {}).get("environment_blockers"))
    promotion_blockers.extend(str(x) for x in gate_blockers)
    environment_blockers.extend(str(x) for x in gate_env)
    # Drift critical also surfaces as environment/promotion blocker when no candidate
    if input_drift.upper() == "CRITICAL" and "INPUT_DRIFT_CRITICAL" not in environment_blockers:
        if not gate_env and not gate_blockers:
            environment_blockers.append("INPUT_DRIFT_CRITICAL")
    governance_promotion = _module_envelope(
        module_id="MODEL-8",
        status=(gate or {}).get("status") if gate else ("MISSING_SOURCE" if "governance_promotion" in missing_sources else None),
        health_status=gate_health_status,
        runtime_impact="NON_BLOCKING",
        summary={
            "eligibility_status": (gate or {}).get("eligibility_status"),
            "governance_status": (gate or {}).get("governance_status"),
            "promotion_execution_status": (gate or {}).get("promotion_execution_status") or "DISABLED",
            "blockers": list(gate_blockers),
            "environment_blockers": list(gate_env) if gate_env else list(environment_blockers),
            "active_decision": (gate or {}).get("active_decision"),
            "approval_stale": bool((gate or {}).get("approval_stale")),
            "active_model_change_performed": bool((gate or {}).get("active_model_change_performed", False)),
        },
        updated_at=(gate_h or {}).get("updated_at") or (gate or {}).get("updated_at"),
        source_path=_rel(paths["gate_summary"], root),
    )

    service_health = {
        "MODEL-0": "NOT_APPLICABLE",
        "MODEL-1": behavioral_validation["health_status"],
        "MODEL-2": external_data["health_status"],
        "MODEL-3": economic_validation["health_status"],
        "MODEL-4": current_toxicity["health_status"],
        "MODEL-5": incident_correlation["health_status"],
        "MODEL-6": drift_monitoring["health_status"],
        "MODEL-7": candidate_shadow["health_status"],
        "MODEL-8": governance_promotion["health_status"],
    }

    # Overall status priority: STALE > CRITICAL > WARNING > WATCH > STABLE
    overall = "CURRENT_STABLE"
    cause: str | None = None

    def _bump(level: str, reason: str) -> None:
        nonlocal overall, cause
        order = {
            "CURRENT_STABLE": 0,
            "CURRENT_WATCH": 1,
            "CURRENT_WARNING": 2,
            "CURRENT_CRITICAL": 3,
            "CURRENT_STALE": 4,
        }
        if order[level] > order.get(overall, 0):
            overall = level
            cause = reason

    for label, token in (
        ("input_drift", input_drift),
        ("feature_drift", feature_drift),
        ("context_drift", context_drift),
        ("performance_drift", performance_drift),
        ("drift_status", str(drift_status or "")),
        ("external_data", str(ext_status or "")),
        ("toxicity", str(tox_status or "")),
        ("incidents", str(inc_status or "")),
    ):
        up = token.upper()
        if up in CRITICAL_TOKENS or up == "CRITICAL" or up.endswith("_CRITICAL"):
            reason = "INPUT_DRIFT_CRITICAL" if label == "input_drift" and up == "CRITICAL" else f"{label}:{up}"
            _bump("CURRENT_CRITICAL", reason)
        elif up in WARNING_TOKENS or up.endswith("_WARNING"):
            _bump("CURRENT_WARNING", f"{label}:{up}")
        elif up in WATCH_TOKENS:
            _bump("CURRENT_WATCH", f"{label}:{up}")

    if stale_sources:
        _bump("CURRENT_STALE", f"STALE_SOURCE:{stale_sources[0]}")
    elif missing_sources:
        _bump("CURRENT_STALE", f"MISSING_SOURCE:{missing_sources[0]}")

    if input_drift.upper() == "CRITICAL" and overall != "CURRENT_STALE":
        overall = "CURRENT_CRITICAL"
        cause = "INPUT_DRIFT_CRITICAL"
    if input_drift.upper() == "CRITICAL" and "INPUT_DRIFT_CRITICAL" not in environment_blockers:
        environment_blockers.append("INPUT_DRIFT_CRITICAL")

    paper_only = bool(active_runtime.get("paper_only", True))
    real_execution = bool(active_runtime.get("real_execution", False))
    if paper_only and not real_execution:
        runtime_safety = "SAFE_PAPER_ONLY"
    elif real_execution:
        runtime_safety = "LIVE_EXECUTION"
    else:
        runtime_safety = "UNKNOWN"

    # Strip forbidden translations: never surface NO_ELIGIBLE_* as MISSING/FAILED in module status
    for section in (
        behavioral_validation,
        economic_validation,
        current_toxicity,
        incident_correlation,
        candidate_shadow,
    ):
        st = str(section.get("status") or "")
        if st in {"MISSING", "FAILED", "BROKEN"} and st not in missing_sources:
            pass  # only MISSING_SOURCE when file absent — already handled

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "scope": "CURRENT_ACTIVE_MODEL_ONLY",
        "overall_assurance_status": overall,
        "overall_cause": cause,
        "runtime_safety_status": runtime_safety,
        "runtime_impact": "NON_BLOCKING",
        "promotion_control": "GOVERNANCE_GATE",
        "active_runtime": active_runtime,
        "behavioral_validation": behavioral_validation,
        "external_data": external_data,
        "economic_validation": economic_validation,
        "current_toxicity": current_toxicity,
        "incident_correlation": incident_correlation,
        "drift_monitoring": drift_monitoring,
        "candidate_shadow": candidate_shadow,
        "governance_promotion": governance_promotion,
        "service_health": service_health,
        "promotion_blockers": sorted(set(promotion_blockers)),
        "environment_blockers": sorted(set(environment_blockers)),
        "warnings": warnings,
        "informational_conditions": sorted(set(informational)),
        "source_snapshot_timestamps": source_snapshot_timestamps,
        "stale_sources": sorted(set(stale_sources)),
        "missing_sources": sorted(set(missing_sources)),
        # Explicit empty current arrays — replace any historical UI leftovers
        "current_blockers": sorted(set(promotion_blockers + environment_blockers)),
        "current_incidents": [],
        "current_toxic_events": [],
        "historical_counters_excluded": True,
    }
    return summary


def run_once(*, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    paths = summary_paths(root)
    summary = build_unified_summary(repo_root=root)
    atomic_write_json(paths["latest_summary"], summary)
    atomic_write_json(
        paths["health"],
        {
            "status": summary.get("overall_assurance_status"),
            "alive": True,
            "runtime_impact": "NON_BLOCKING",
            "promotion_control": "GOVERNANCE_GATE",
            "runtime_safety_status": summary.get("runtime_safety_status"),
            "pid": os.getpid(),
            "paper_only": (summary.get("active_runtime") or {}).get("paper_only"),
            "real_execution": (summary.get("active_runtime") or {}).get("real_execution"),
            "stale_sources": summary.get("stale_sources"),
            "missing_sources": summary.get("missing_sources"),
            "updated_at": utc_now_iso(),
        },
    )
    return summary


def load_latest_summary(repo_root: Path | None = None) -> dict[str, Any]:
    """Dashboard producer helper — read only the canonical summary file."""
    path = summary_paths(repo_root)["latest_summary"]
    payload = load_json(path)
    if payload is None:
        return {
            "status": "MISSING_SOURCE",
            "overall_assurance_status": "MISSING_SOURCE",
            "runtime_safety_status": "UNKNOWN",
            "runtime_impact": "NON_BLOCKING",
            "promotion_control": "GOVERNANCE_GATE",
            "scope": "CURRENT_ACTIVE_MODEL_ONLY",
            "missing_sources": ["latest_summary"],
            "stale_sources": [],
            "promotion_blockers": [],
            "environment_blockers": [],
            "current_blockers": [],
            "current_incidents": [],
            "current_toxic_events": [],
        }
    return payload
