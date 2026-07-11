"""Pipeline cycle audit reader — no runtime module imports."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import REPO_ROOT

LOOP_AUDIT_RELATIVE = os.path.join("reports", "runtime_loop", "pipeline_cycle_audit.jsonl")
CYCLE_COUNT_RELATIVE = os.path.join("reports", "runtime_loop", "pipeline_cycle_count.json")
WORKER_AUDIT_RELATIVE = os.path.join("data", "runtime", "engine_worker_audit.jsonl")


def _read_latest_worker_cycle() -> int | None:
    """Latest cycle_id from engine worker audit (live persistent-worker runs)."""
    path = REPO_ROOT / WORKER_AUDIT_RELATIVE
    if not path.exists():
        return None
    try:
        # Read trailing chunk — file can be large.
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 256_000), os.SEEK_SET)
            chunk = handle.read().decode("utf-8", errors="ignore")
        latest_cycle: int | None = None
        for line in chunk.splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            cycle = payload.get("cycle_id")
            if cycle is None:
                continue
            try:
                latest_cycle = int(cycle)
            except (TypeError, ValueError):
                continue
        return latest_cycle
    except OSError:
        return None


def _read_counter_file() -> int | None:
    count_file = REPO_ROOT / CYCLE_COUNT_RELATIVE
    if not count_file.exists():
        return None
    try:
        with open(count_file, encoding="utf-8") as handle:
            payload = json.load(handle)
        return int(payload.get("cycle", 0))
    except Exception:
        return None


def read_pipeline_cycle_count() -> int:
    """Return best live pipeline cycle estimate.

    Prefer engine_worker_audit cycle_id (updates while runtime is running).
    Fall back to pipeline_cycle_count.json / jsonl line count only when the
    worker audit has no usable cycle — the counter file is often stale across
    process restarts and must not override a live worker cycle.
    """
    worker_cycle = _read_latest_worker_cycle()
    if worker_cycle is not None and worker_cycle > 0:
        return worker_cycle

    counter = _read_counter_file()
    if counter is not None and counter > 0:
        return counter

    loop_audit = REPO_ROOT / LOOP_AUDIT_RELATIVE
    if not loop_audit.exists():
        return 0
    with open(loop_audit, encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())
