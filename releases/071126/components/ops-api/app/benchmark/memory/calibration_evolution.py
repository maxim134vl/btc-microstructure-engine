"""Track calibration changes and their longitudinal effects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.memory.paths import DATASETS_DIR, ensure_dirs


def record_calibration_evolution(
    cycle: dict[str, Any],
    comparison: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    ensure_dirs()
    layers = cycle.get("layers") or {}
    calibration = (layers.get("conformance") or {}).get("calibration") or {}

    confidence_delta = _find_delta(comparison, "confidence_realism_score")
    overconfident_delta = _find_delta(comparison, "overconfident_rate")
    cal_health_delta = _find_delta(comparison, "calibration_health_score")

    entry = {
        "cycle_id": cycle.get("cycle_id"),
        "generated_at": cycle.get("generated_at"),
        "calibration_status": calibration.get("status"),
        "recommendations": calibration.get("recommendations") or [],
        "confidence_realism_delta": confidence_delta,
        "overconfident_rate_delta": overconfident_delta,
        "calibration_health_delta": cal_health_delta,
        "regression_verdict": regression.get("verdict"),
        "calibration_improved": regression.get("verdict") == "IMPROVEMENT"
        and overconfident_delta is not None
        and overconfident_delta < 0,
    }

    path = DATASETS_DIR / "calibration_history" / "evolution.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")

    note = "Calibration change impact inconclusive."
    if entry["calibration_improved"]:
        note = "Calibration improvement confirmed — overconfidence decreased vs previous cycle."
    elif overconfident_delta is not None and overconfident_delta > 0.05:
        note = "Confidence inflation worsened vs previous cycle."

    return {"entry": entry, "note": note}


def _find_delta(comparison: dict[str, Any], metric: str) -> float | None:
    for row in comparison.get("comparisons") or []:
        if row.get("metric") == metric:
            return row.get("delta_vs_previous")
    return None
