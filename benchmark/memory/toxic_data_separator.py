"""Separate cognition into trust-tier datasets for future ML/LLM use."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmark.memory.cognition_history_store import load_layer_events
from benchmark.memory.paths import DATASETS_DIR, ensure_dirs
from benchmark.memory.trust_classifier import classify_cycle_trust, classify_event_trust

BUCKET_MAP = {
    "VERIFIED": "validated_cognition",
    "STABLE": "validated_cognition",
    "NOISY": "failed_cognition",
    "LOW_TRUST": "drift_epochs",
    "DEGRADED": "failed_cognition",
    "TOXIC": "toxic_periods",
    "ONTOLOGY_COLLAPSE": "ontology_health_history",
    "CALIBRATION_COLLAPSE": "calibration_history",
}


def _append_jsonl(bucket: str, record: dict[str, Any]) -> None:
    ensure_dirs()
    path = DATASETS_DIR / bucket / "records.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def separate_cycle_datasets(cycle: dict[str, Any], trust: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {bucket: 0 for bucket in BUCKET_MAP.values()}
    cid = cycle.get("cycle_id")
    generated_at = cycle.get("generated_at")

    cycle_record = {
        "cycle_id": cid,
        "generated_at": generated_at,
        "trust_level": trust.get("trust_level"),
        "layers_present": list((cycle.get("layers") or {}).keys()),
        "conformance_summary": (cycle.get("layers", {}).get("conformance") or {}).get("summary"),
    }
    bucket = BUCKET_MAP.get(trust.get("trust_level", "NOISY"), "drift_epochs")
    _append_jsonl(bucket, {"type": "cycle", **cycle_record})
    counts[bucket] += 1

    if trust.get("trust_level") in ("TOXIC", "DEGRADED", "LOW_TRUST"):
        _append_jsonl("drift_epochs", {"type": "epoch", **cycle_record})

    layers = cycle.get("layers") or {}
    for layer_name, layer_data in layers.items():
        export = layer_data.get("export_json")
        events = load_layer_events(export)
        for event in events:
            event_trust = classify_event_trust(event)
            event_bucket = BUCKET_MAP.get(event_trust, "failed_cognition")
            _append_jsonl(
                event_bucket,
                {
                    "type": "event",
                    "cycle_id": cid,
                    "layer": layer_name,
                    "trust_level": event_trust,
                    "event_index": event.get("event_index"),
                    "timestamp": event.get("timestamp"),
                    "verdict": event.get("integrated_verdict") or event.get("verdict"),
                    "interpretation": event.get("stage2_interpretation") or event.get("interpretation"),
                    "root_cause": event.get("root_cause"),
                    "contradiction_level": event.get("contradiction_level"),
                    "confidence_quality": event.get("confidence_quality") or event.get("confidence_realism"),
                    "event": event,
                },
            )
            counts[event_bucket] = counts.get(event_bucket, 0) + 1

            if event_trust in ("TOXIC", "CALIBRATION_COLLAPSE"):
                _append_jsonl("contradiction_events", {"type": "event", "cycle_id": cid, "event": event})
            if event.get("verdict") in ("FAILED", "FALSE NARRATIVE", "FALSE_NARRATIVE", "REASONING_FAILURE"):
                _append_jsonl("failed_cognition", {"type": "event", "cycle_id": cid, "event": event})

    cal = (layers.get("conformance") or {}).get("calibration")
    if cal:
        _append_jsonl(
            "calibration_history",
            {"type": "calibration_audit", "cycle_id": cid, "generated_at": generated_at, "calibration": cal},
        )
        counts["calibration_history"] = counts.get("calibration_history", 0) + 1

    onto = (layers.get("conformance") or {}).get("ontology")
    if onto:
        _append_jsonl(
            "ontology_health_history",
            {"type": "ontology", "cycle_id": cid, "generated_at": generated_at, "ontology": onto},
        )
        counts["ontology_health_history"] = counts.get("ontology_health_history", 0) + 1

    return counts
