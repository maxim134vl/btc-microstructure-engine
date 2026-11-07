"""Operational audit exports for canonical runtime loop continuity."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import pandas as pd

from storage.path_registry import resolve_read

AUDIT_FILES = (
    "probabilistic_auction_memory.parquet",
    "auction_synthesis_memory.parquet",
    "state_transition_memory.parquet",
    "runtime_cognition_memory.parquet",
    "auction_reinforcement_memory.parquet",
)

DEFAULT_REPORT_DIR = os.path.join("reports", "runtime_loop")


def _file_snapshot(label: str) -> dict[str, Any]:
    path = resolve_read(label)
    snapshot: dict[str, Any] = {
        "file": label,
        "path": path,
        "exists": os.path.exists(path),
        "mtime": None,
        "row_count": 0,
        "latest_timestamp": None,
    }
    if not snapshot["exists"]:
        return snapshot

    snapshot["mtime"] = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()

    try:
        df = pd.read_parquet(path)
        snapshot["row_count"] = int(len(df))
        if len(df) > 0 and "timestamp" in df.columns:
            snapshot["latest_timestamp"] = str(pd.to_datetime(df["timestamp"].iloc[-1]))
    except Exception as error:
        snapshot["read_error"] = str(error)

    return snapshot


def export_runtime_tick_audit(report_dir: str = DEFAULT_REPORT_DIR) -> str:
    os.makedirs(report_dir, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "files": [_file_snapshot(name) for name in AUDIT_FILES],
    }
    out = os.path.join(report_dir, "runtime_tick_audit.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return out


def export_state_snapshot_sequence(report_dir: str = DEFAULT_REPORT_DIR) -> str:
    os.makedirs(report_dir, exist_ok=True)
    sequence: dict[str, Any] = {"generated_at": datetime.now().isoformat(), "series": {}}

    for label in (
        "auction_synthesis_memory.parquet",
        "probabilistic_auction_memory.parquet",
        "state_transition_memory.parquet",
    ):
        path = resolve_read(label)
        if not os.path.exists(path):
            sequence["series"][label] = []
            continue

        df = pd.read_parquet(path)
        if len(df) == 0 or "timestamp" not in df.columns:
            sequence["series"][label] = []
            continue

        tail = df.tail(10)
        sequence["series"][label] = [
            {
                "timestamp": str(pd.to_datetime(row["timestamp"])),
                "auction_state": row.get("auction_state"),
                "auction_regime": row.get("auction_regime"),
                "transition_state": row.get("transition_state"),
            }
            for _, row in tail.iterrows()
        ]

    out = os.path.join(report_dir, "state_snapshot_sequence.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(sequence, handle, indent=2)
    return out


def append_pipeline_cycle_audit(
    cycle: int,
    duration_s: float,
    engine_results: list[dict[str, Any]],
    report_dir: str = DEFAULT_REPORT_DIR,
) -> str:
    os.makedirs(report_dir, exist_ok=True)
    out = os.path.join(report_dir, "pipeline_cycle_audit.jsonl")
    row = {
        "cycle": cycle,
        "completed_at": datetime.now().isoformat(),
        "duration_s": round(duration_s, 2),
        "engines": engine_results,
    }
    with open(out, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    return out


def export_all_audits(report_dir: str = DEFAULT_REPORT_DIR) -> dict[str, str]:
    return {
        "runtime_tick_audit": export_runtime_tick_audit(report_dir),
        "state_snapshot_sequence": export_state_snapshot_sequence(report_dir),
    }
