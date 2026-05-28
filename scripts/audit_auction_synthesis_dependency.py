#!/usr/bin/env python3
"""Operational audit — auction_synthesis_memory.parquet dependency chain."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd

from runtime_dependency_guard import should_run_engine
from runtime_dependency_map import DEPENDENCIES
from storage.path_registry import resolve_read


def _file_info(name: str) -> dict:
    path = resolve_read(name)
    info = {"file": name, "path": path, "exists": os.path.exists(path)}
    if info["exists"]:
        info["mtime"] = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
        info["age_seconds"] = round(time.time() - os.path.getmtime(path), 1)
        try:
            df = pd.read_parquet(path)
            info["row_count"] = len(df)
            if len(df) and "timestamp" in df.columns:
                info["latest_timestamp"] = str(df["timestamp"].iloc[-1])
            if len(df) and "auction_state" in df.columns:
                info["latest_auction_state"] = str(df["auction_state"].iloc[-1])
        except Exception as error:
            info["read_error"] = str(error)
    return info


def main() -> int:
    engine = "auction_synthesis_engine_v1.py"
    memory = "auction_synthesis_memory.parquet"
    deps = DEPENDENCIES.get(engine, [])

    engine_state_path = resolve_read("runtime_engine_state.parquet")
    synthesis_runs = 0
    if os.path.exists(engine_state_path):
        df = pd.read_parquet(engine_state_path)
        synthesis_runs = int((df["engine"] == engine).sum())

    audit = {
        "generated_at": datetime.now().isoformat(),
        "classification": "DORMANT_APPEND_ONLY",
        "summary": (
            "auction_synthesis_memory.parquet is append-only (state-change gated). "
            "Engine skipped when dependency mtimes unchanged. "
            "Not on live feed→cognition→probabilistic path. "
            "state_transition defers cleanly with <2 rows."
        ),
        "writer": {
            "engine": engine,
            "write_condition": "should_persist_state — only when auction_state changes",
            "skip_condition": "runtime_dependency_guard — skipped when dependency mtimes unchanged",
            "should_run_now": should_run_engine(engine, deps),
            "dependency_inputs": [_file_info(d) for d in deps],
            "total_logged_runs": synthesis_runs,
        },
        "readers": [
            {
                "consumer": "state_transition_engine_v1.py",
                "blocks_pipeline": False,
                "behavior_if_stale": "DEFERRED — WAITING FOR SECOND STATE if <2 rows",
            },
            {
                "consumer": "auction_reinforcement_engine_v1.py",
                "blocks_pipeline": False,
                "behavior_if_stale": "reads STATE cache loaded at process start",
            },
            {
                "consumer": "probabilistic_auction_engine_v1.py",
                "blocks_pipeline": False,
                "behavior_if_stale": "uses runtime_cognition synthesis_state, not parquet directly",
            },
            {
                "consumer": "dashboard health manifest",
                "blocks_pipeline": False,
                "behavior_if_stale": "was false DEGRADED — removed from REQUIRED",
            },
        ],
        "memory_file": _file_info(memory),
        "recommendation": {
            "manifest": "Remove from REQUIRED_PARQUET and REQUIRED_ENGINES",
            "display_class": "DORMANT",
            "health_impact": "none — mtime staleness is expected for append-only state memory",
        },
    }

    out_dir = os.path.join(ROOT, "reports", "runtime_dependency")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "auction_synthesis_audit.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2)

    print(json.dumps({"path": out_path, "classification": audit["classification"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
