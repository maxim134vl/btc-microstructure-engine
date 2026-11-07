"""Build observed runtime cognition profile from benchmark outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.integrated.paths import latest_pointer_path as integrated_latest_path
from benchmark.stage1.paths import REPORTS_DIR as STAGE1_REPORTS_DIR
from benchmark.stage2.paths import latest_pointer_path as stage2_latest_path


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _load_export_events(export_path: str | None) -> list[dict[str, Any]]:
    if not export_path:
        return []
    path = Path(export_path)
    if not path.exists():
        return []
    payload = _read_json(path) or {}
    return payload.get("events") or payload.get("chains") or []


def _climax_event_rate(events: list[dict[str, Any]], lookback_days: int) -> float:
    if not events:
        return 0.0
    climax = 0
    for event in events:
        text = " ".join(
            [
                str(event.get("interpretation", "")),
                str(event.get("stage1_perception_text", "")),
                str(event.get("context", {}).get("volume_class", "")),
                str(event.get("context", {}).get("trigger_event", "")),
            ]
        ).lower()
        if "climax" in text:
            climax += 1
    rate = climax / len(events)
    days = max(lookback_days, 1)
    return round(rate / days, 4)


def build_runtime_profile(*, lookback_days: int = 7) -> dict[str, Any]:
    stage1_latest = _read_json(STAGE1_REPORTS_DIR / "latest.json")
    stage2_latest = _read_json(stage2_latest_path())
    integrated_latest = _read_json(integrated_latest_path())

    stage1_summary = (stage1_latest or {}).get("summary") or {}
    stage2_summary = (stage2_latest or {}).get("summary") or {}
    integrated_summary = (integrated_latest or {}).get("summary") or {}
    integrated_drift = (integrated_latest or {}).get("drift") or {}

    stage1_events = _load_export_events((stage1_latest or {}).get("export_json"))
    integrated_events = _load_export_events((integrated_latest or {}).get("export_json"))

    stage1_profile = {
        **stage1_summary,
        "climax_event_rate": _climax_event_rate(stage1_events, lookback_days),
        "event_count": stage1_summary.get("event_count", 0),
        "run_id": (stage1_latest or {}).get("run_id"),
        "generated_at": (stage1_latest or {}).get("generated_at"),
    }
    stage2_profile = {
        **stage2_summary,
        "event_count": stage2_summary.get("event_count", 0),
        "run_id": (stage2_latest or {}).get("run_id"),
        "generated_at": (stage2_latest or {}).get("generated_at"),
    }
    integrated_profile = {
        **integrated_summary,
        "event_count": integrated_summary.get("event_count", 0),
        "drift_health": integrated_drift.get("health"),
        "drift_signals": integrated_drift.get("signals") or [],
        "climax_event_rate": _climax_event_rate(integrated_events, lookback_days),
        "run_id": (integrated_latest or {}).get("run_id"),
        "generated_at": (integrated_latest or {}).get("generated_at"),
    }

    return {
        "lookback_days": lookback_days,
        "stage1": stage1_profile,
        "stage2": stage2_profile,
        "integrated": integrated_profile,
        "has_stage1": stage1_latest is not None,
        "has_stage2": stage2_latest is not None,
        "has_integrated": integrated_latest is not None,
    }
