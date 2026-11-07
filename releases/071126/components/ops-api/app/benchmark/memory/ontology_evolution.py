"""Track ontology integrity evolution over cognition history."""

from __future__ import annotations

import json
from typing import Any

from benchmark.memory.paths import DATASETS_DIR, ensure_dirs


def record_ontology_evolution(cycle: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    layers = cycle.get("layers") or {}
    ontology = (layers.get("conformance") or {}).get("ontology") or {}
    integrated = (layers.get("integrated") or {}).get("summary") or {}

    integrity_delta = _find_delta(comparison, "ontology_integrity_score")
    coherence = integrated.get("ontology_coherence")

    entry = {
        "cycle_id": cycle.get("cycle_id"),
        "generated_at": cycle.get("generated_at"),
        "ontology_status": ontology.get("status"),
        "ontology_score": ontology.get("score"),
        "ontology_coherence": coherence,
        "integrity_delta": integrity_delta,
        "issues": ontology.get("issues") or [],
    }

    path = DATASETS_DIR / "ontology_health_history" / "evolution.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")

    if integrity_delta is not None and integrity_delta < -0.08:
        signal = "ontology degradation detected"
    elif integrity_delta is not None and integrity_delta > 0.08:
        signal = "ontology integrity improving"
    else:
        signal = "ontology stable"

    return {"entry": entry, "signal": signal}


def _find_delta(comparison: dict[str, Any], metric: str) -> float | None:
    for row in comparison.get("comparisons") or []:
        if row.get("metric") == metric:
            return row.get("delta_vs_previous")
    return None
