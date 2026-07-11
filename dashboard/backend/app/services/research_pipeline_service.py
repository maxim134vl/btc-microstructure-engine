"""Research pipeline aggregators — decision layer, ML governance, validation memories."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from app.config import (
    CANONICAL_PIPELINE,
    EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,
    MODEL_DRIFT_MAX_AGE_HOURS,
    MODEL_ECONOMIC_MAX_AGE_HOURS,
    MODEL_GOVERNANCE_MAX_AGE_HOURS,
    MODEL_TOXIC_MAX_AGE_HOURS,
    MODEL_VALIDATION_MAX_AGE_HOURS,
    REPO_ROOT,
)
from app.services.dashboard_paths import resolve_dashboard_read
from app.services.model_summary_freshness import (
    STATUS_STALE_DRIFT,
    STATUS_STALE_GOVERNANCE,
    STATUS_STALE_VALIDATION,
    apply_stale_block,
    apply_stale_governance,
    build_freshness,
    build_model_summary_with_freshness,
    resolve_existing_path,
)
from app.services.monitoring_kpis import (
    decision_level_and_label,
    drift_composite_level,
    governance_age_days,
    toxic_routing_is_bulk_backfill,
    toxic_severity_level,
)
from app.services.parquet_service import df_records, latest_row, read_parquet

ECONOMIC_ROLLING_WINDOW = 5000
SHADOW_MACRO_F1_PASS_THRESHOLD = 0.50

WIN_OUTCOMES = frozenset({"ECONOMIC_WIN", "ECONOMIC_WEAK_WIN"})
NEUTRAL_OUTCOMES = frozenset({"ECONOMIC_NEUTRAL"})
LOSS_OUTCOMES = frozenset({"ECONOMIC_LOSS", "ECONOMIC_SEVERE_LOSS"})

WATCH_TRADING_STATES = frozenset({"REVERSAL_WATCH", "OBSERVE"})


def _level_from_flags(*, missing: bool = False, stale: bool = False, warning: bool = False) -> str:
    if missing:
        return "RED"
    if stale or warning:
        return "YELLOW"
    return "GREEN"


def _psi_level(psi: float | None) -> str:
    if psi is None:
        return "GREY"
    if psi < 0.10:
        return "GREEN"
    if psi <= 0.25:
        return "YELLOW"
    return "RED"


def _to_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return bool(value)


def _format_pct(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(100.0 * count / total, 1)


def _outcome_bucket(outcome: str) -> str | None:
    if outcome in WIN_OUTCOMES:
        return "WIN"
    if outcome in NEUTRAL_OUTCOMES:
        return "NEUTRAL"
    if outcome in LOSS_OUTCOMES:
        return "LOSS"
    return None


def _decision_level(
    *,
    entry_eligible: bool | None,
    trading_state: str | None,
    execution_posture: str | None = None,
    missing: bool = False,
) -> str:
    level, _ = decision_level_and_label(
        entry_eligible=entry_eligible,
        trading_state=trading_state,
        execution_posture=execution_posture,
        missing=missing,
    )
    return level


def _decision_status_label(
    *,
    entry_eligible: bool | None,
    trading_state: str | None,
    execution_posture: str | None = None,
    missing: bool = False,
) -> str:
    _, label = decision_level_and_label(
        entry_eligible=entry_eligible,
        trading_state=trading_state,
        execution_posture=execution_posture,
        missing=missing,
    )
    return label


def _derive_governance_status(
    *,
    active_model: str | None,
    candidate_model: str | None,
    promotion_eligible: bool,
    rollback_warning: bool,
    psi: float | None,
    rollback_reasons: Any,
    macro_f1: float | None = None,
    loss_recall: float | None = None,
) -> tuple[str, str]:
    reasons_text = ""
    if isinstance(rollback_reasons, list):
        reasons_text = " ".join(str(r) for r in rollback_reasons).upper()
    elif rollback_reasons:
        reasons_text = str(rollback_reasons).upper()

    drift_level, _ = drift_composite_level(
        psi=psi,
        macro_f1=macro_f1,
        loss_recall=loss_recall,
    )
    psi_drift = (psi or 0.0) > 0.25 or "PSI" in reasons_text

    if promotion_eligible:
        return "PROMOTION_ELIGIBLE", "GREEN"
    if drift_level == "RED" or (rollback_warning and psi_drift and drift_level != "YELLOW"):
        return "DRIFT_WARNING", drift_level if drift_level in ("RED", "YELLOW") else "RED"
    if drift_level == "YELLOW" or rollback_warning:
        return "DRIFT_WARNING", "YELLOW"
    if rollback_warning:
        return "REVIEW_REQUIRED", "YELLOW"
    if candidate_model and candidate_model != active_model:
        return "CANDIDATE", "YELLOW"
    return "ACTIVE", "GREEN"


def _repo_path(relative: str) -> str:
    return os.path.join(str(REPO_ROOT), relative)


def _cycle_durations(records: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    step_count = len(CANONICAL_PIPELINE)
    if not records:
        return None, None

    last_records = records[-step_count:]
    last_durations = [_to_float(row.get("duration")) for row in last_records]
    last_durations = [value for value in last_durations if value is not None]
    last_cycle_duration = round(sum(last_durations), 2) if last_durations else None

    recent_records = records[-step_count * 3 :]
    all_durations = [_to_float(row.get("duration")) for row in recent_records]
    all_durations = [value for value in all_durations if value is not None]
    avg_cycle_duration = round(sum(all_durations) / len(all_durations), 2) if all_durations else None
    return last_cycle_duration, avg_cycle_duration


async def build_pipeline_sync_status() -> dict[str, Any]:
    engine_state = await read_parquet("runtime_engine_state.parquet", tail=500)
    records = df_records(engine_state)
    last_cycle_duration, avg_cycle_duration = _cycle_durations(records)

    return {
        "step_count": len(CANONICAL_PIPELINE),
        "expected_step_count": EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,
        "in_sync": len(CANONICAL_PIPELINE) == EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,
        "engines": CANONICAL_PIPELINE,
        "last_cycle_duration_s": last_cycle_duration,
        "average_cycle_duration_s": avg_cycle_duration,
    }


async def build_decision_layer_snapshot() -> dict[str, Any]:
    market = await read_parquet("market_state_memory.parquet", tail=1)
    trading = await read_parquet("trading_state_memory.parquet", tail=1)
    snapshots = await read_parquet("trading_state_feature_snapshots.parquet", tail=1)
    probabilistic = await read_parquet("probabilistic_auction_memory.parquet", tail=1)

    market_latest = latest_row(market) or {}
    trading_latest = latest_row(trading) or {}
    snapshot_latest = latest_row(snapshots) or {}
    probabilistic_latest = latest_row(probabilistic) or {}

    trading_state = trading_latest.get("trading_state") or snapshot_latest.get("trading_state")
    market_state = market_latest.get("market_state") or trading_latest.get("market_state") or snapshot_latest.get("market_state")
    rule_id = market_latest.get("rule_id") or snapshot_latest.get("rule_id")
    market_state_confidence = _to_float(
        market_latest.get("market_state_confidence")
        or trading_latest.get("market_state_confidence")
        or snapshot_latest.get("market_state_confidence")
    )
    trend_confidence = _to_float(probabilistic_latest.get("trend_confidence"))
    entry_eligible = _to_bool(trading_latest.get("entry_eligible") if "entry_eligible" in trading_latest else snapshot_latest.get("entry_eligible"))
    execution_posture = trading_latest.get("execution_posture") or snapshot_latest.get("execution_posture")

    missing = len(market) == 0 and len(trading) == 0
    level = _decision_level(
        entry_eligible=entry_eligible,
        trading_state=trading_state,
        execution_posture=str(execution_posture) if execution_posture is not None else None,
        missing=missing,
    )

    return {
        "level": level,
        "status_label": _decision_status_label(
            entry_eligible=entry_eligible,
            trading_state=trading_state,
            execution_posture=str(execution_posture) if execution_posture is not None else None,
            missing=missing,
        ),
        "market_state": market_state,
        "market_bias": market_latest.get("market_bias") or snapshot_latest.get("market_bias"),
        "rule_id": rule_id,
        "market_state_confidence": market_state_confidence,
        "trend_confidence": trend_confidence,
        "trading_state": trading_state,
        "confidence_band": trading_latest.get("confidence_band") or snapshot_latest.get("confidence_band"),
        "entry_eligible": entry_eligible,
        "execution_posture": trading_latest.get("execution_posture") or snapshot_latest.get("execution_posture"),
        "snapshot_id": snapshot_latest.get("snapshot_id"),
        "timestamp": trading_latest.get("timestamp") or market_latest.get("timestamp") or snapshot_latest.get("timestamp"),
        "rows": {
            "market_state_memory": len(market),
            "trading_state_memory": len(trading),
            "feature_snapshots": len(snapshots),
        },
    }


async def build_drift_monitoring_snapshot() -> dict[str, Any]:
    monitoring_path = resolve_existing_path(resolve_dashboard_read("model_monitoring_memory.parquet"))
    monitoring = await read_parquet("model_monitoring_memory.parquet", tail=20)
    if len(monitoring) == 0:
        freshness = build_freshness(
            source_path=monitoring_path,
            source_timestamp=None,
            max_age_hours=MODEL_DRIFT_MAX_AGE_HOURS,
            stale_status=STATUS_STALE_DRIFT,
        )
        return apply_stale_block(
            {
                "level": "GREY",
                "psi": None,
                "macro_f1": None,
                "loss_recall": None,
                "macro_f1_trend": None,
                "loss_recall_trend": None,
                "monitoring_rows": 0,
                "severity_label": "Unknown",
            },
            freshness,
            stale_status_field="severity_label",
            stale_status_value=STATUS_STALE_DRIFT if freshness.get("is_stale") else "Unknown",
        )

    latest = monitoring.iloc[-1]
    psi = _to_float(latest.get("psi_label"))
    macro_f1 = _to_float(latest.get("macro_f1"))
    loss_recall = _to_float(latest.get("loss_recall"))

    first = monitoring.iloc[0]
    macro_f1_trend = None
    loss_recall_trend = None
    if len(monitoring) >= 2:
        first_macro = _to_float(first.get("macro_f1"))
        first_loss = _to_float(first.get("loss_recall"))
        if macro_f1 is not None and first_macro is not None:
            macro_f1_trend = round(macro_f1 - first_macro, 4)
        if loss_recall is not None and first_loss is not None:
            loss_recall_trend = round(loss_recall - first_loss, 4)

    level, severity_label = drift_composite_level(
        psi=psi,
        macro_f1=macro_f1,
        loss_recall=loss_recall,
        macro_f1_trend=macro_f1_trend,
        loss_recall_trend=loss_recall_trend,
    )

    freshness = build_freshness(
        source_path=monitoring_path,
        source_timestamp=latest.get("timestamp"),
        max_age_hours=MODEL_DRIFT_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_DRIFT,
    )
    payload = {
        "level": level,
        "severity_label": severity_label,
        "psi": psi,
        "psi_feature_max": _to_float(latest.get("psi_feature_max")),
        "macro_f1": macro_f1,
        "loss_recall": loss_recall,
        "macro_f1_trend": macro_f1_trend,
        "loss_recall_trend": loss_recall_trend,
        "last_monitoring_at": latest.get("timestamp"),
        "monitoring_rows": int(len(monitoring)),
    }
    if freshness.get("is_stale"):
        payload["severity_label"] = f"{severity_label}+STALE" if severity_label else STATUS_STALE_DRIFT
    return apply_stale_block(payload, freshness)


async def build_model_governance_snapshot() -> dict[str, Any]:
    dashboard_path = resolve_existing_path(_repo_path("exports/model_governance_dashboard.json"))
    governance: dict[str, Any] = {}
    if dashboard_path:
        with open(dashboard_path, encoding="utf-8") as handle:
            governance = json.load(handle)

    monitoring_path = resolve_existing_path(resolve_dashboard_read("model_monitoring_memory.parquet"))
    monitoring = await read_parquet("model_monitoring_memory.parquet", tail=20)
    latest_monitoring = latest_row(monitoring) or {}
    drift = await build_drift_monitoring_snapshot()

    rollback_warning = bool(latest_monitoring.get("rollback_warning")) if latest_monitoring else False
    promotion_eligible = bool(latest_monitoring.get("promotion_eligible")) if latest_monitoring else False
    shadow_metrics = governance.get("shadow_metrics_last_5000") or {}
    shadow_macro_f1 = _to_float(shadow_metrics.get("macro_f1"))
    shadow_loss_recall = _to_float(shadow_metrics.get("loss_recall"))

    active_model = governance.get("active_model")
    candidate_model = governance.get("candidate_model")
    psi = drift.get("psi")
    eval_macro_f1 = drift.get("macro_f1") or shadow_macro_f1
    eval_loss_recall = drift.get("loss_recall") or shadow_loss_recall

    governance_status, governance_level = _derive_governance_status(
        active_model=active_model,
        candidate_model=candidate_model,
        promotion_eligible=promotion_eligible,
        rollback_warning=rollback_warning,
        psi=psi,
        rollback_reasons=latest_monitoring.get("rollback_reasons"),
        macro_f1=eval_macro_f1,
        loss_recall=eval_loss_recall,
    )

    registry_path = resolve_existing_path(_repo_path("model_registry.json"))
    active_registered_at = None
    if registry_path:
        with open(registry_path, encoding="utf-8") as handle:
            registry = json.load(handle)
            for model in registry.get("models", []):
                if model.get("id") == active_model:
                    active_registered_at = model.get("registered_at")
                    break

    active_since = governance.get("last_retrain_at") or active_registered_at
    active_model_age_days = governance_age_days(active_since)
    last_validation_at = governance.get("last_validation_at") or latest_monitoring.get("timestamp")

    freshness = build_freshness(
        source_path=dashboard_path or monitoring_path,
        source_timestamp=last_validation_at,
        max_age_hours=MODEL_GOVERNANCE_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_GOVERNANCE,
    )

    payload = {
        "level": governance_level,
        "governance_status": governance_status,
        "active_model": active_model,
        "candidate_model": candidate_model,
        "shadow_model": governance.get("shadow_model"),
        "last_retrain_at": governance.get("last_retrain_at"),
        "last_validation_at": last_validation_at,
        "last_promotion_at": governance.get("last_promotion_at"),
        "active_model_registered_at": active_registered_at,
        "active_model_age_days": active_model_age_days,
        "promotion_eligible_label": "YES" if promotion_eligible else "NO",
        "next_retrain_note": "Manual — scripts/retrain_models.py (weekly)",
        "active_metrics": governance.get("active_metrics"),
        "candidate_metrics": governance.get("candidate_metrics"),
        "candidate_comparison": governance.get("candidate_comparison"),
        "shadow_macro_f1": _to_float(shadow_metrics.get("macro_f1")),
        "shadow_balanced_accuracy": _to_float(shadow_metrics.get("balanced_accuracy")),
        "shadow_loss_recall": _to_float(shadow_metrics.get("loss_recall")),
        "shadow_rows": shadow_metrics.get("rows"),
        "rollback_warning": rollback_warning,
        "rollback_reasons": latest_monitoring.get("rollback_reasons"),
        "promotion_eligible": promotion_eligible,
        "promotion_reasons": latest_monitoring.get("promotion_reasons"),
        "monitoring_rows": len(monitoring),
    }
    return apply_stale_governance(payload, freshness)


async def build_economic_validation_snapshot() -> dict[str, Any]:
    economic = await read_parquet(
        "economic_validation_memory.parquet",
        tail=ECONOMIC_ROLLING_WINDOW + 5000,
    )
    validation = await read_parquet("trading_state_validation_memory.parquet", tail=5000)

    if len(economic) == 0:
        economic_path = resolve_existing_path(resolve_dashboard_read("economic_validation_memory.parquet"))
        freshness = build_freshness(
            source_path=economic_path,
            source_timestamp=None,
            max_age_hours=MODEL_ECONOMIC_MAX_AGE_HOURS,
            stale_status=STATUS_STALE_VALIDATION,
        )
        return apply_stale_block(
            {
                "level": "GREY",
                "status": "NOT_EVALUATED",
                "rows": 0,
                "complete_h4h": 0,
                "pending_h4h": 0,
                "rolling_window": ECONOMIC_ROLLING_WINDOW,
                "win_pct": None,
                "neutral_pct": None,
                "loss_pct": None,
                "outcome_distribution": {},
            },
            freshness,
            stale_status_field="status",
            stale_status_value=STATUS_STALE_VALIDATION if freshness.get("is_stale") else "NOT_EVALUATED",
        )

    frame = economic.copy()
    if "validation_horizon" in frame.columns:
        h4h = frame[frame["validation_horizon"] == "H4H"]
    else:
        h4h = frame

    if "validation_status" in h4h.columns:
        complete = h4h[h4h["validation_status"] == "COMPLETE"]
    else:
        complete = h4h

    rolling = complete.tail(ECONOMIC_ROLLING_WINDOW) if len(complete) else complete
    win_count = neutral_count = loss_count = 0
    if "economic_outcome" in rolling.columns and len(rolling):
        for outcome in rolling["economic_outcome"].astype(str):
            bucket = _outcome_bucket(outcome)
            if bucket == "WIN":
                win_count += 1
            elif bucket == "NEUTRAL":
                neutral_count += 1
            elif bucket == "LOSS":
                loss_count += 1

    rolling_total = win_count + neutral_count + loss_count
    pending = int(len(h4h) - len(complete)) if len(h4h) else 0
    if len(complete) == 0 and pending == 0:
        level = "GREY"
        status = "NOT_EVALUATED"
    else:
        level = _level_from_flags(missing=False, warning=pending > max(len(complete), 1) * 0.5)
        status = "EVALUATED"

    outcome_dist: dict[str, int] = {}
    if "economic_outcome" in complete.columns:
        outcome_dist = complete["economic_outcome"].value_counts().head(8).astype(int).to_dict()

    latest_completed_at = complete.iloc[-1].get("completed_at") if len(complete) else None
    if latest_completed_at is None or (isinstance(latest_completed_at, float) and pd.isna(latest_completed_at)):
        latest_completed_at = complete.iloc[-1].get("timestamp") if len(complete) else None
    if latest_completed_at is None or (isinstance(latest_completed_at, float) and pd.isna(latest_completed_at)):
        latest_completed_at = (
            economic.iloc[-1].get("lineage_propagation_timestamp")
            if len(economic) and "lineage_propagation_timestamp" in economic.columns
            else None
        )

    economic_path = resolve_existing_path(resolve_dashboard_read("economic_validation_memory.parquet"))
    freshness = build_freshness(
        source_path=economic_path,
        source_timestamp=latest_completed_at,
        max_age_hours=MODEL_ECONOMIC_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
    )
    payload = {
        "level": level,
        "status": status,
        "rows": int(len(economic)),
        "validation_rows": int(len(validation)),
        "complete_h4h": int(len(complete)),
        "pending_h4h": pending,
        "rolling_window": ECONOMIC_ROLLING_WINDOW,
        "rolling_complete_count": int(len(rolling)),
        "win_pct": _format_pct(win_count, rolling_total),
        "neutral_pct": _format_pct(neutral_count, rolling_total),
        "loss_pct": _format_pct(loss_count, rolling_total),
        "win_count": win_count,
        "neutral_count": neutral_count,
        "loss_count": loss_count,
        "outcome_distribution": outcome_dist,
        "latest_completed_at": latest_completed_at,
    }
    if freshness.get("is_stale"):
        payload["status"] = STATUS_STALE_VALIDATION
    return apply_stale_block(payload, freshness)


async def build_shadow_inference_snapshot() -> dict[str, Any]:
    shadow = await read_parquet("shadow_inference_memory.parquet", tail=10000)
    governance_path = resolve_existing_path(_repo_path("exports/model_governance_dashboard.json"))
    shadow_metrics: dict[str, Any] = {}
    last_validation_time = None
    if governance_path:
        with open(governance_path, encoding="utf-8") as handle:
            governance = json.load(handle)
            shadow_metrics = governance.get("shadow_metrics_last_5000") or {}
            last_validation_time = governance.get("last_validation_at")

    monitoring_path = resolve_existing_path(resolve_dashboard_read("model_monitoring_memory.parquet"))
    monitoring = await read_parquet("model_monitoring_memory.parquet", tail=1)
    latest_monitoring = latest_row(monitoring) or {}
    if last_validation_time is None:
        last_validation_time = latest_monitoring.get("timestamp")
    if not shadow_metrics and latest_monitoring:
        shadow_metrics = {
            "macro_f1": latest_monitoring.get("macro_f1"),
            "balanced_accuracy": latest_monitoring.get("balanced_accuracy"),
            "loss_recall": latest_monitoring.get("loss_recall"),
            "rows": latest_monitoring.get("shadow_rows"),
        }
    if len(shadow) == 0 and not shadow_metrics:
        freshness = build_freshness(
            source_path=governance_path or monitoring_path,
            source_timestamp=last_validation_time,
            max_age_hours=MODEL_VALIDATION_MAX_AGE_HOURS,
            stale_status=STATUS_STALE_VALIDATION,
        )
        return apply_stale_block(
            {
                "level": "GREY",
                "rows": 0,
                "evaluated_rows": 0,
                "validation_status": "NOT_EVALUATED",
                "last_validation_time": last_validation_time,
            },
            freshness,
            stale_status_field="validation_status",
            stale_status_value=STATUS_STALE_VALIDATION if freshness.get("is_stale") else "NOT_EVALUATED",
        )

    evaluated = shadow[shadow["evaluation_status"] == "COMPLETE"] if "evaluation_status" in shadow.columns else shadow.iloc[0:0]
    pred_dist: dict[str, int] = {}
    if "predicted_class" in evaluated.columns and len(evaluated):
        pred_dist = evaluated["predicted_class"].value_counts().astype(int).to_dict()

    macro_f1 = _to_float(shadow_metrics.get("macro_f1"))
    balanced_accuracy = _to_float(shadow_metrics.get("balanced_accuracy"))
    loss_recall = _to_float(shadow_metrics.get("loss_recall"))
    evaluated_rows = int(shadow_metrics.get("rows") or len(evaluated))

    validation_status = "PASS" if macro_f1 is not None and macro_f1 >= SHADOW_MACRO_F1_PASS_THRESHOLD else "WARNING"
    level = "GREEN" if validation_status == "PASS" else "YELLOW"
    if macro_f1 is None and len(evaluated) == 0:
        level = "GREY"
        validation_status = "NOT_EVALUATED"

    registry_id = shadow.iloc[-1].get("registry_id") if len(shadow) else None
    model_version = shadow.iloc[-1].get("model_version") if len(shadow) else None

    freshness = build_freshness(
        source_path=governance_path or monitoring_path,
        source_timestamp=last_validation_time,
        max_age_hours=MODEL_VALIDATION_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
    )
    payload = {
        "level": level,
        "validation_status": validation_status,
        "rows": int(len(shadow)),
        "evaluated_rows": evaluated_rows,
        "pending_rows": int(len(shadow) - len(evaluated)) if len(shadow) else 0,
        "macro_f1": macro_f1,
        "balanced_accuracy": balanced_accuracy,
        "loss_recall": loss_recall,
        "last_validation_time": last_validation_time,
        "registry_id": registry_id,
        "model_version": model_version,
        "prediction_distribution": pred_dist,
        "latest_prediction_at": shadow.iloc[-1].get("prediction_timestamp") if len(shadow) else None,
    }
    if freshness.get("is_stale"):
        payload["validation_status"] = STATUS_STALE_VALIDATION
        payload["level"] = "YELLOW"
    return apply_stale_block(payload, freshness)


async def build_toxic_box_snapshot() -> dict[str, Any]:
    toxic = await read_parquet("toxic_box_memory.parquet", tail=10000)
    if len(toxic) == 0:
        toxic_path = resolve_existing_path(resolve_dashboard_read("toxic_box_memory.parquet"))
        freshness = build_freshness(
            source_path=toxic_path,
            source_timestamp=None,
            max_age_hours=MODEL_TOXIC_MAX_AGE_HOURS,
            stale_status=STATUS_STALE_VALIDATION,
        )
        return apply_stale_block(
            {
                "level": "YELLOW",
                "severity_label": "Unknown",
                "rows": 0,
                "events": 0,
                "events_last_7d": 0,
                "toxic_rate_7d": 0.0,
                "trend": "STABLE",
                "type_distribution": {},
            },
            freshness,
        )

    frame = toxic.copy()
    now = pd.Timestamp.now(tz=timezone.utc)

    prop_col = None
    for candidate in ("lineage_propagation_timestamp", "created_at", "timestamp"):
        if candidate in frame.columns:
            prop_col = candidate
            break
    if prop_col is None:
        prop_col = "timestamp" if "timestamp" in frame.columns else "created_at"

    frame["_routed_at"] = pd.to_datetime(frame[prop_col], utc=True, errors="coerce")
    t0_col = "timestamp" if "timestamp" in frame.columns else prop_col
    frame["_t0_at"] = pd.to_datetime(frame[t0_col], utc=True, errors="coerce")

    cutoff_7d = now - timedelta(days=7)
    cutoff_14d = now - timedelta(days=14)
    cutoff_30d = now - timedelta(days=30)

    bulk_backfill = toxic_routing_is_bulk_backfill(frame["_routed_at"].dropna().tolist())
    latest_routed = frame["_routed_at"].max()
    hours_since_last_routed = None
    if pd.notna(latest_routed):
        hours_since_last_routed = (now - latest_routed).total_seconds() / 3600.0

    if bulk_backfill and pd.notna(latest_routed):
        backfill_peak = latest_routed
        live_frame = frame[frame["_routed_at"] > backfill_peak + pd.Timedelta(seconds=1)]
    else:
        live_frame = frame

    recent_7d = live_frame[live_frame["_routed_at"] >= cutoff_7d]
    prior_7d = live_frame[(live_frame["_routed_at"] >= cutoff_14d) & (live_frame["_routed_at"] < cutoff_7d)]
    recent_30d = live_frame[live_frame["_routed_at"] >= cutoff_30d]

    events_last_7d = int(len(recent_7d))
    events_prior_7d = int(len(prior_7d))
    events_last_30d = int(len(recent_30d))
    toxic_rate_7d = round(events_last_7d / 7.0, 2)
    toxic_rate_30d = round(events_last_30d / 30.0, 2)

    t0_recent_7d = int((frame["_t0_at"] >= cutoff_7d).sum())
    t0_recent_30d = int((frame["_t0_at"] >= cutoff_30d).sum())

    if events_last_7d > events_prior_7d:
        trend = "UP"
    elif events_last_7d < events_prior_7d:
        trend = "DOWN"
    else:
        trend = "STABLE"

    type_dist: dict[str, int] = {}
    if "toxic_type" in frame.columns:
        type_dist = frame["toxic_type"].value_counts().head(8).astype(int).to_dict()

    level, severity_label = toxic_severity_level(
        events_last_7d=events_last_7d,
        events_last_30d=events_last_30d,
        trend=trend,
        hours_since_last_routed=hours_since_last_routed,
        is_bulk_backfill=bulk_backfill,
    )

    toxic_path = resolve_existing_path(resolve_dashboard_read("toxic_box_memory.parquet"))
    freshness_ts = latest_routed if pd.notna(latest_routed) else frame.iloc[-1].get(t0_col)
    freshness = build_freshness(
        source_path=toxic_path,
        source_timestamp=freshness_ts,
        max_age_hours=MODEL_TOXIC_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
    )
    payload = {
        "level": level,
        "severity_label": severity_label,
        "rows": int(len(frame)),
        "events": int(len(frame)),
        "events_last_7d": events_last_7d,
        "events_prior_7d": events_prior_7d,
        "events_last_30d": events_last_30d,
        "events_t0_last_7d": t0_recent_7d,
        "events_t0_last_30d": t0_recent_30d,
        "toxic_rate_7d": toxic_rate_7d,
        "toxic_rate_30d": toxic_rate_30d,
        "monitoring_mode": "bulk_backfill" if bulk_backfill else "live",
        "hours_since_last_routed": round(hours_since_last_routed, 1) if hours_since_last_routed is not None else None,
        "trend": trend,
        "type_distribution": type_dist,
        "latest_timestamp": frame.iloc[-1].get(t0_col) if len(frame) else None,
        "latest_routed_at": latest_routed.isoformat() if pd.notna(latest_routed) else None,
    }
    if freshness.get("is_stale"):
        if severity_label == "Baseline loaded":
            payload["severity_label"] = "Baseline loaded (STALE)"
        else:
            payload["severity_label"] = f"{severity_label}+STALE" if severity_label else "STALE"
    return apply_stale_block(payload, freshness)


async def build_model_summary_snapshot(
    governance: dict[str, Any],
    drift: dict[str, Any],
    shadow: dict[str, Any],
) -> dict[str, Any]:
    macro_f1 = shadow.get("macro_f1") or governance.get("shadow_macro_f1")
    loss_recall = shadow.get("loss_recall") or governance.get("shadow_loss_recall")
    psi = drift.get("psi")
    shadow_status = str(shadow.get("validation_status") or "NOT_EVALUATED").upper()
    drift_level = drift.get("level", "GREY")
    drift_severity = drift.get("severity_label")

    if shadow_status in {"MISSING", "NOT_EVALUATED", "MISSING_DATA"} and not governance.get("active_model"):
        status = "NOT_EVALUATED"
        level = "GREY"
    elif shadow_status in {"MISSING", "NOT_EVALUATED", "MISSING_DATA"}:
        status = "NOT_EVALUATED"
        level = "GREY"
    elif shadow_status in {"WARNING", "STALE_VALIDATION"} or drift_level == "RED":
        status = "ATTENTION"
        level = "YELLOW"
    elif drift_level == "YELLOW":
        status = "MONITOR"
        level = "YELLOW"
    else:
        status = "HEALTHY"
        level = "GREEN"

    if drift_level == "RED" and drift_severity == "Critical" and shadow_status == "PASS":
        status = "MONITOR"
        level = "YELLOW"

    base = {
        "level": level,
        "status": status,
        "model": governance.get("active_model"),
        "shadow_macro_f1": macro_f1,
        "loss_recall": loss_recall,
        "psi": psi,
        "governance_status": governance.get("governance_status"),
    }
    return build_model_summary_with_freshness(
        governance=governance,
        drift=drift,
        shadow=shadow,
        base_summary=base,
    )


async def build_research_pipeline_snapshot() -> dict[str, Any]:
    pipeline = await build_pipeline_sync_status()
    decision = await build_decision_layer_snapshot()
    drift = await build_drift_monitoring_snapshot()
    governance = await build_model_governance_snapshot()
    economic = await build_economic_validation_snapshot()
    shadow = await build_shadow_inference_snapshot()
    toxic = await build_toxic_box_snapshot()
    model_summary = await build_model_summary_snapshot(governance, drift, shadow)

    ribbon_extensions = [
        {
            "key": "decision_layer",
            "label": "DECISION",
            "level": decision["level"],
            "value": str(decision.get("status_label") or decision.get("trading_state") or "—"),
        },
        {
            "key": "model_governance",
            "label": "ML GOVERNANCE",
            "level": governance["level"],
            "value": str(governance.get("governance_status") or governance.get("active_model") or "—"),
        },
        {
            "key": "economic_validation",
            "label": "ECONOMIC",
            "level": economic["level"],
            "value": (
                f"W{economic.get('win_pct')}% N{economic.get('neutral_pct')}% L{economic.get('loss_pct')}%"
                if economic.get("win_pct") is not None
                else str(economic.get("status") or f"complete {economic.get('complete_h4h', 0)}")
            ),
        },
        {
            "key": "shadow_inference",
            "label": "SHADOW",
            "level": shadow["level"],
            "value": str(shadow.get("validation_status") or "—"),
        },
        {
            "key": "toxic_box",
            "label": "TOXIC",
            "level": toxic["level"],
            "value": f"{toxic.get('events_last_7d', 0)}/7d",
        },
        {
            "key": "pipeline_sync",
            "label": "PIPELINE24",
            "level": "GREEN" if pipeline["in_sync"] else "RED",
            "value": f"{pipeline['step_count']}/{pipeline['expected_step_count']}",
        },
    ]

    return {
        "generated_at": datetime.now().isoformat(),
        "pipeline": pipeline,
        "decision_layer": decision,
        "model_governance": governance,
        "economic_validation": economic,
        "shadow_inference": shadow,
        "toxic_box": toxic,
        "drift_monitoring": drift,
        "model_summary": model_summary,
        "ribbon_extensions": ribbon_extensions,
    }
