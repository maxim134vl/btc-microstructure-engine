"""Build replayable cognition event timeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from benchmark.stage1.event_extractor import event_to_interpretation, extract_cognition_events
from benchmark.stage1.paths import REPORTS_DIR as STAGE1_REPORTS_DIR
from visual_cognition.behavioral_overlay_engine import detect_behaviors, overlay_for_bar
from visual_cognition.colors import BEHAVIOR_COLORS


def _load_stage1_export() -> list[dict[str, Any]]:
    latest_path = STAGE1_REPORTS_DIR / "latest.json"
    if not latest_path.exists():
        return []
    with open(latest_path, encoding="utf-8") as handle:
        latest = json.load(handle)
    export_path = Path(latest.get("export_json", ""))
    if not export_path.exists():
        return []
    with open(export_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("events") or []


def _load_memory_events(limit: int = 200) -> list[dict[str, Any]]:
    from benchmark.memory.paths import DATASETS_DIR

    records: list[dict[str, Any]] = []
    for bucket in ("validated_cognition", "failed_cognition", "contradiction_events", "drift_epochs"):
        path = DATASETS_DIR / bucket / "records.jsonl"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records[-limit:]


def _is_significant_cognition_row(row: pd.Series) -> bool:
    trigger = _safe_str(row.get("trigger_event"))
    climax = _safe_str(row.get("climax_state"))
    volume_event = _safe_str(row.get("volume_event"))
    volume_class = _safe_str(row.get("volume_class"))
    effort = _safe_str(row.get("effort_result_state"))
    transition = _safe_str(row.get("transition_state"))
    synthesis = _safe_str(row.get("synthesis_state"))

    if volume_class in ("climax", "stopping"):
        return True
    if volume_event in ("STOPPING_VOLUME", "ABSORPTION_VOLUME", "EXHAUSTION_VOLUME", "CONTINUATION_VOLUME"):
        return True
    if climax and climax != "NO_CLIMAX":
        return True
    if effort and effort not in ("BALANCED_RESPONSE",):
        return True
    if trigger and trigger not in ("NORMAL",):
        return True
    if synthesis:
        return True
    if transition and transition not in ("STABLE_STATE",):
        return True
    return False


def _safe_str(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text.lower() in ("nan", "none", ""):
        return None
    return text


def _event_type_from_row(row: pd.Series) -> str:
    behaviors = detect_behaviors(row)
    if behaviors:
        return behaviors[0]
    if pd.notna(row.get("transition_state")):
        return str(row["transition_state"])
    if pd.notna(row.get("trigger_event")):
        return str(row["trigger_event"])
    return "COGNITION_EVENT"


def _load_intermediate_events(limit: int = 120) -> list[dict[str, Any]]:
    from parquet_utils import safe_read_parquet

    frame = safe_read_parquet("intermediate_cognition_memory.parquet")
    if len(frame) == 0:
        return []
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp").tail(limit)
    events: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        state = str(row.get("intermediate_state") or "IC_EVENT")
        ts = row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"])
        anchor = row.get("anchor_stage2_state")
        events.append(
            {
                "timestamp": ts,
                "type": state,
                "label": f"{state} ({row.get('severity')}) — anchor {anchor}",
                "source": "stage2_5_intermediate",
                "confidence": row.get("confidence"),
                "severity": row.get("severity"),
                "anchor_stage2_state": anchor,
                "overlay_color": BEHAVIOR_COLORS.get(state),
            }
        )
    return events


def build_timeline_from_cognition(
    cognition: pd.DataFrame,
    benchmark_events: list[dict[str, Any]] | None = None,
    memory_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Unified cognition timeline for replay scrubber."""

    timeline: list[dict[str, Any]] = []

    if benchmark_events:
        for event in benchmark_events:
            ts = event.get("timestamp")
            overlay = overlay_for_bar(pd.Series(event.get("context") or {}))
            timeline.append(
                {
                    "event_index": event.get("event_index"),
                    "timestamp": ts,
                    "type": event.get("bias_label") or overlay.get("primary_behavior"),
                    "label": event.get("interpretation") or event.get("bias_label"),
                    "verdict": event.get("verdict"),
                    "source": "stage1_benchmark",
                    "behaviors": overlay.get("behaviors", []),
                    "overlay_color": overlay.get("overlay_color"),
                }
            )

    if memory_events:
        for event in memory_events:
            ts = event.get("timestamp")
            if any(item.get("timestamp") == ts and item.get("source") == event.get("source") for item in timeline):
                continue
            timeline.append({**event, "event_index": len(timeline) + 1})

    intermediate_events = _load_intermediate_events()
    if intermediate_events:
        for event in intermediate_events:
            ts = event.get("timestamp")
            if any(item.get("timestamp") == ts and item.get("source") == "stage2_5_intermediate" for item in timeline):
                continue
            timeline.append({**event, "event_index": len(timeline) + 1})

    if len(cognition) > 0:
        for _, row in cognition.iterrows():
            if not _is_significant_cognition_row(row):
                continue
            overlay = overlay_for_bar(row)
            ts = row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"])
            if any(item.get("timestamp") == ts for item in timeline):
                continue
            timeline.append(
                {
                    "event_index": len(timeline) + 1,
                    "timestamp": ts,
                    "type": _event_type_from_row(row),
                    "label": event_to_interpretation(row),
                    "source": "cognition_memory",
                    "behaviors": overlay.get("behaviors", []),
                    "overlay_color": overlay.get("overlay_color"),
                }
            )

    timeline.sort(key=lambda item: item.get("timestamp") or "")
    for index, item in enumerate(timeline, start=1):
        item["timeline_index"] = index
    return timeline


def build_cognition_timeline(cognition: pd.DataFrame, *, lookback_days: int = 7) -> list[dict[str, Any]]:
    benchmark = _load_stage1_export()
    native = extract_cognition_events(lookback_days=lookback_days)
    memory_events: list[dict[str, Any]] = []
    if len(native) > 0:
        for _, row in native.iterrows():
            overlay = overlay_for_bar(row)
            ts = row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"])
            memory_events.append(
                {
                    "timestamp": ts,
                    "type": _event_type_from_row(row),
                    "label": event_to_interpretation(row),
                    "source": "cognition_memory",
                    "behaviors": overlay.get("behaviors", []),
                    "overlay_color": overlay.get("overlay_color"),
                }
            )
    return build_timeline_from_cognition(cognition.iloc[0:0], benchmark_events=benchmark or None, memory_events=memory_events)
