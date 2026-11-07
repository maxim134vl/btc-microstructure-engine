"""Detect cognition drift across rolling conformance audits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.conformance.paths import HISTORY_DIR


def _load_history(limit: int = 12) -> list[dict[str, Any]]:
    if not HISTORY_DIR.exists():
        return []
    files = sorted(HISTORY_DIR.glob("conformance_*.json"), reverse=True)
    history: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            with open(path, encoding="utf-8") as handle:
                history.append(json.load(handle))
        except Exception:
            continue
    return history


def analyze_drift(
    current_results: list[dict[str, Any]],
    *,
    current_health: dict[str, Any],
) -> dict[str, Any]:
    history = _load_history()
    signals: list[str] = list(current_health.get("signals") or [])

    failed = sum(1 for r in current_results if r["verdict"] in ("FAILED", "SEVERE_DRIFT", "CALIBRATION_COLLAPSE"))
    drifting = sum(1 for r in current_results if r["verdict"] == "DRIFTING")
    total = len(current_results) or 1

    if history:
        prior = history[0]
        prior_failed = prior.get("summary", {}).get("failed_count", 0)
        if failed > prior_failed + 1:
            signals.append("conformance regression")

    drift_map = {
        "confidence inflation": any("confidence" in r["metric"] for r in current_results if r["verdict"] != "CONFIRMED"),
        "narrative degradation": any("narrative" in r["metric"] for r in current_results if r["verdict"] != "CONFIRMED"),
        "contradiction growth": any("contradiction" in r["metric"] for r in current_results if r["verdict"] != "CONFIRMED"),
        "transition instability": any("transition" in r["metric"] for r in current_results if r["verdict"] != "CONFIRMED"),
        "ontology fragmentation": any(r["verdict"] == "ONTOLOGY_DEGRADATION" for r in current_results),
        "threshold oversensitivity": any("climax" in r["metric"] and r["verdict"] != "CONFIRMED" for r in current_results),
        "perception drift": any(r["layer"] == "stage1" and r["verdict"] in ("DRIFTING", "SEVERE_DRIFT") for r in current_results),
        "synthesis drift": any(r["layer"] == "stage2" and r["verdict"] in ("DRIFTING", "SEVERE_DRIFT") for r in current_results),
    }
    for label, active in drift_map.items():
        if active and label not in signals:
            signals.append(label)

    severe_rate = sum(1 for r in current_results if r["verdict"] == "SEVERE_DRIFT") / total
    if severe_rate >= 0.25:
        severity = "SEVERE"
    elif failed / total >= 0.35 or drifting / total >= 0.40:
        severity = "MODERATE"
    elif failed / total >= 0.15 or drifting / total >= 0.20:
        severity = "MILD"
    else:
        severity = "NONE"

    return {
        "severity": severity,
        "signals": signals,
        "failed_count": failed,
        "drifting_count": drifting,
        "history_runs": len(history),
        "drift_map": {key: bool(val) for key, val in drift_map.items()},
    }
