"""Track Stage 2.5 intermediate state quality across benchmark history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.calibration.paths import ensure_dirs
from benchmark.memory.paths import CYCLES_DIR
from benchmark.stage2_5.paths import EXPORTS_DIR as STAGE2_5_EXPORTS, latest_pointer_path as stage2_5_latest_path
from storage.path_registry import repo_root

PHASE1_STATES = (
    "IC_CONTINUATION_WEAKENING",
    "IC_INITIATIVE_DETERIORATION",
    "IC_ROTATIONAL_PRESSURE",
)

TRACKED_METRICS = (
    "precision",
    "confirmation_rate",
    "false_positive_rate",
    "early_warning_rate",
)

CALIBRATION_STATUSES = (
    "VERIFIED",
    "STABLE",
    "DEGRADING",
    "NEEDS_CALIBRATION",
)

THRESHOLDS = {
    "verified": {
        "precision": 0.70,
        "confirmation_rate": 0.55,
        "false_positive_rate": 0.15,
    },
    "stable": {
        "precision": 0.55,
        "confirmation_rate": 0.45,
        "false_positive_rate": 0.25,
    },
    "needs_calibration": {
        "precision": 0.55,
        "confirmation_rate": 0.40,
        "false_positive_rate": 0.30,
    },
}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_benchmark_runs(limit: int = 24) -> list[dict[str, Any]]:
    """Collect Stage 2.5 benchmark snapshots from evolution cycles and exports."""

    ensure_dirs()
    runs: dict[str, dict[str, Any]] = {}

    if CYCLES_DIR.exists():
        for path in sorted(CYCLES_DIR.glob("stage2_5_*.json")):
            if path.name.startswith("stage2_5_calibration_"):
                continue
            payload = _read_json(path) or {}
            entry = payload.get("entry") or {}
            run_id = entry.get("run_id") or path.stem.replace("stage2_5_", "")
            runs[run_id] = {
                "run_id": run_id,
                "generated_at": entry.get("generated_at"),
                "summary": entry.get("summary") or (payload.get("payload") or {}).get("summary"),
                "source": str(path),
            }

    if STAGE2_5_EXPORTS.exists():
        for path in sorted(STAGE2_5_EXPORTS.glob("stage2_5_benchmark_*.json")):
            payload = _read_json(path) or {}
            run_id = payload.get("run_id") or path.stem.replace("stage2_5_benchmark_", "")
            if run_id not in runs:
                runs[run_id] = {
                    "run_id": run_id,
                    "generated_at": payload.get("generated_at"),
                    "summary": payload.get("summary"),
                    "source": str(path),
                }

    latest = _read_json(stage2_5_latest_path())
    if latest:
        run_id = latest.get("run_id")
        if run_id:
            runs[run_id] = {
                "run_id": run_id,
                "generated_at": latest.get("generated_at"),
                "summary": latest.get("summary"),
                "source": "latest_stage2_5",
            }

    ordered = sorted(runs.values(), key=lambda item: item.get("generated_at") or "")
    return ordered[-limit:]


def load_evolution_context() -> dict[str, Any]:
    from benchmark.memory.paths import latest_evolution_path

    latest = _read_json(latest_evolution_path()) or {}
    trust = latest.get("trust") or {}
    regression = latest.get("regression") or {}
    calibration = latest.get("calibration_evolution") or {}
    return {
        "cycle_id": latest.get("cycle_id"),
        "trust_level": trust.get("current_trust_level"),
        "stability_score": trust.get("stability_score"),
        "regression_verdict": regression.get("verdict"),
        "calibration_status": calibration.get("calibration_status") or calibration.get("status"),
        "calibration_note": calibration.get("note"),
    }


def load_conformance_context() -> dict[str, Any]:
    from benchmark.conformance.paths import latest_pointer_path as conformance_latest_path

    latest = _read_json(conformance_latest_path()) or {}
    summary = latest.get("summary") or {}
    calibration = latest.get("calibration") or {}
    return {
        "run_id": latest.get("run_id"),
        "cognition_health": latest.get("cognition_health"),
        "calibration_status": calibration.get("status"),
        "calibration_health_score": summary.get("calibration_health_score"),
        "cognition_stability_score": summary.get("cognition_stability_score"),
        "recommendation_count": calibration.get("recommendation_count"),
    }


def _metric_value(summary: dict[str, Any], state: str | None, metric: str) -> float | None:
    if state:
        block = (summary.get("by_state") or {}).get(state) or {}
        value = block.get(metric)
    else:
        value = summary.get(metric)
    if value is None:
        return None
    return round(float(value), 4)


def _trend_direction(current: float | None, previous: float | None, *, invert: bool = False) -> str:
    if current is None or previous is None:
        return "unknown"
    delta = current - previous
    if invert:
        delta = -delta
    if delta >= 0.05:
        return "improving"
    if delta <= -0.05:
        return "degrading"
    return "stable"


def compute_metric_trends(runs: list[dict[str, Any]], state: str | None = None) -> dict[str, dict[str, Any]]:
    if len(runs) < 1:
        return {metric: {"current": None, "previous": None, "trend": "unknown"} for metric in TRACKED_METRICS}

    latest_summary = runs[-1].get("summary") or {}
    previous_summary = runs[-2].get("summary") or {} if len(runs) >= 2 else {}

    trends: dict[str, dict[str, Any]] = {}
    for metric in TRACKED_METRICS:
        current = _metric_value(latest_summary, state, metric)
        previous = _metric_value(previous_summary, state, metric)
        invert = metric == "false_positive_rate"
        trends[metric] = {
            "current": current,
            "previous": previous,
            "trend": _trend_direction(current, previous, invert=invert),
        }
    return trends


def _apply_external_pressure(status: str, external_pressure: bool) -> str:
    if not external_pressure:
        return status
    if status == "VERIFIED":
        return "STABLE"
    if status == "STABLE":
        return "DEGRADING"
    return status


def classify_state_quality(
    metrics: dict[str, float | None],
    trends: dict[str, dict[str, Any]],
    *,
    external_pressure: bool = False,
) -> str:
    precision = metrics.get("precision")
    confirmation = metrics.get("confirmation_rate")
    false_positive = metrics.get("false_positive_rate")

    if precision is not None and precision < THRESHOLDS["needs_calibration"]["precision"]:
        return _apply_external_pressure("NEEDS_CALIBRATION", external_pressure)
    if confirmation is not None and confirmation < THRESHOLDS["needs_calibration"]["confirmation_rate"]:
        return _apply_external_pressure("NEEDS_CALIBRATION", external_pressure)
    if false_positive is not None and false_positive > THRESHOLDS["needs_calibration"]["false_positive_rate"]:
        return _apply_external_pressure("NEEDS_CALIBRATION", external_pressure)

    degrading_count = sum(1 for item in trends.values() if item.get("trend") == "degrading")
    if degrading_count >= 2:
        return _apply_external_pressure("DEGRADING", external_pressure)

    if (
        precision is not None
        and precision >= THRESHOLDS["verified"]["precision"]
        and confirmation is not None
        and confirmation >= THRESHOLDS["verified"]["confirmation_rate"]
        and false_positive is not None
        and false_positive <= THRESHOLDS["verified"]["false_positive_rate"]
        and degrading_count == 0
    ):
        return _apply_external_pressure("VERIFIED", external_pressure)

    if (
        precision is not None
        and precision >= THRESHOLDS["stable"]["precision"]
        and false_positive is not None
        and false_positive <= THRESHOLDS["stable"]["false_positive_rate"]
    ):
        if degrading_count == 1:
            return _apply_external_pressure("DEGRADING", external_pressure)
        return _apply_external_pressure("STABLE", external_pressure)

    if degrading_count >= 1:
        return _apply_external_pressure("DEGRADING", external_pressure)

    return _apply_external_pressure("NEEDS_CALIBRATION", external_pressure)


def _external_calibration_pressure(evolution: dict[str, Any], conformance: dict[str, Any]) -> bool:
    regression = (evolution.get("regression_verdict") or "").upper()
    if regression in ("REGRESSION", "SEVERE_REGRESSION"):
        return True
    if (conformance.get("cognition_health") or "").upper() in ("SEVERE_DRIFT", "CRITICAL", "RED"):
        return True
    cal_health = conformance.get("calibration_health_score")
    if cal_health is not None and float(cal_health) < 0.35:
        return True
    return False


def track_state_quality(*, runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build per-state quality assessment with metric trends."""

    runs = runs if runs is not None else load_benchmark_runs()
    evolution = load_evolution_context()
    conformance = load_conformance_context()
    external_pressure = _external_calibration_pressure(evolution, conformance)

    latest_summary = runs[-1].get("summary") if runs else {}
    overall_trends = compute_metric_trends(runs, state=None)

    overall_metrics = {
        metric: overall_trends[metric]["current"] for metric in TRACKED_METRICS
    }
    overall_status = classify_state_quality(
        overall_metrics,
        overall_trends,
        external_pressure=external_pressure,
    )

    states: dict[str, Any] = {}
    for state in PHASE1_STATES:
        trends = compute_metric_trends(runs, state=state)
        metrics = {metric: trends[metric]["current"] for metric in TRACKED_METRICS}
        event_count = ((latest_summary or {}).get("by_state") or {}).get(state, {}).get("event_count", 0)
        states[state] = {
            "status": classify_state_quality(metrics, trends, external_pressure=external_pressure),
            "event_count": event_count,
            "metrics": metrics,
            "trends": trends,
        }

    return {
        "run_count": len(runs),
        "latest_run_id": runs[-1]["run_id"] if runs else None,
        "latest_generated_at": runs[-1].get("generated_at") if runs else None,
        "overall_status": overall_status,
        "overall_metrics": overall_metrics,
        "overall_trends": overall_trends,
        "states": states,
        "evolution_context": evolution,
        "conformance_context": conformance,
        "external_pressure": external_pressure,
        "sources": {
            "benchmark_runs": [run["run_id"] for run in runs],
            "evolution_cycle": evolution.get("cycle_id"),
            "conformance_run": conformance.get("run_id"),
        },
    }
