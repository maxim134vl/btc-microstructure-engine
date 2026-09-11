"""OPS snapshot must not stampede runtime-truth on concurrent polls."""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import ops_monitor  # noqa: E402


def test_runtime_truth_cache_single_flight(monkeypatch) -> None:
    calls = {"n": 0}
    started = threading.Event()

    def fake_snapshot() -> dict:
        calls["n"] += 1
        started.set()
        time.sleep(0.2)
        return {"overall_health": "OPERATIONAL", "processes": []}

    monkeypatch.setattr(
        "ops_dashboard_runtime_truth.build_runtime_truth_snapshot",
        fake_snapshot,
    )
    ops_monitor.clear_ops_snapshot_caches()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(ops_monitor._build_runtime_truth_cached_sync) for _ in range(4)]
        results = [fut.result(timeout=5) for fut in futs]

    assert calls["n"] == 1
    assert all(row["overall_health"] == "OPERATIONAL" for row in results)

    ops_monitor._build_runtime_truth_cached_sync()
    assert calls["n"] == 1


def test_runtime_truth_cache_force_rebuilds(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_snapshot() -> dict:
        calls["n"] += 1
        return {"overall_health": "OPERATIONAL"}

    monkeypatch.setattr(
        "ops_dashboard_runtime_truth.build_runtime_truth_snapshot",
        fake_snapshot,
    )
    ops_monitor.clear_ops_snapshot_caches()
    ops_monitor._build_runtime_truth_cached_sync()
    ops_monitor._build_runtime_truth_cached_sync()
    assert calls["n"] == 1
    ops_monitor._build_runtime_truth_cached_sync(force=True)
    assert calls["n"] == 2
