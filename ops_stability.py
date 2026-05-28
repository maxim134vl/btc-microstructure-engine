"""Operational stability / uptime tracking for remote deployment supervision."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

from storage.path_registry import repo_root

STABILITY_PATH = repo_root() / "data" / "live" / "ops_stability.json"
MAX_EVENTS = 50


def _load() -> dict[str, Any]:
    if not STABILITY_PATH.exists():
        return {
            "started_at": datetime.now().isoformat(),
            "runtime": {"connected_since": None, "last_stall_at": None, "stall_count": 0},
            "collector": {
                "binance_live_feed": {
                    "connected_since": None,
                    "last_disconnect_at": None,
                    "disconnect_count": 0,
                    "restart_count": 0,
                }
            },
            "feed": {
                "ws_last_connected_at": None,
                "ws_last_disconnect_at": None,
                "write_last_at": None,
                "consume_last_at": None,
            },
            "pipeline": {
                "last_cycle": 0,
                "last_cycle_at": None,
                "last_timeout_at": None,
                "timeout_count": 0,
                "last_stall_at": None,
            },
            "events": [],
        }
    try:
        with open(STABILITY_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {
            "started_at": datetime.now().isoformat(),
            "runtime": {"connected_since": None},
            "collector": {"binance_live_feed": {}},
            "feed": {},
            "pipeline": {"last_cycle": 0},
            "events": [],
        }


def _save(state: dict[str, Any]) -> None:
    STABILITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = str(STABILITY_PATH) + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
    os.replace(temp, STABILITY_PATH)


def _append_event(state: dict[str, Any], event_type: str, detail: str) -> None:
    state.setdefault("events", []).insert(
        0,
        {"timestamp": datetime.now().isoformat(), "type": event_type, "detail": detail},
    )
    state["events"] = state["events"][:MAX_EVENTS]


def _uptime_seconds(since_iso: str | None) -> float | None:
    if not since_iso:
        return None
    try:
        return max(0.0, time.time() - datetime.fromisoformat(since_iso).timestamp())
    except Exception:
        return None


def update_stability(
    *,
    pipeline_cycle: int,
    pipeline_cycling: bool,
    collector_connected: bool,
    ws_connected: bool,
    parquet_writing: bool,
    pipeline_timeout_count: int,
    pipeline_stalled: bool,
) -> dict[str, Any]:
    now_iso = datetime.now().isoformat()
    state = _load()

    # Pipeline cycle tracking
    pipe = state.setdefault("pipeline", {})
    prev_cycle = int(pipe.get("last_cycle", 0))
    if pipeline_cycle > prev_cycle:
        pipe["last_cycle"] = pipeline_cycle
        pipe["last_cycle_at"] = now_iso
        state.setdefault("runtime", {})["connected_since"] = state["runtime"].get("connected_since") or now_iso

    if pipeline_stalled and not pipe.get("last_stall_at"):
        pipe["last_stall_at"] = now_iso
        pipe["stall_count"] = int(pipe.get("stall_count", 0)) + 1
        _append_event(state, "pipeline_stall", f"cycle stuck at {pipeline_cycle}")
    elif pipeline_cycling and pipe.get("last_stall_at"):
        _append_event(state, "pipeline_recovered", f"cycle advanced to {pipeline_cycle}")
        pipe["last_stall_at"] = None

    if pipeline_timeout_count > int(pipe.get("timeout_count", 0)):
        pipe["last_timeout_at"] = now_iso
        pipe["timeout_count"] = pipeline_timeout_count
        _append_event(state, "engine_timeout", f"timeout count {pipeline_timeout_count}")

    # Collector / WS
    coll = state.setdefault("collector", {}).setdefault(
        "binance_live_feed",
        {"connected_since": None, "last_disconnect_at": None, "disconnect_count": 0, "restart_count": 0},
    )
    feed = state.setdefault("feed", {})

    if ws_connected:
        feed["ws_last_connected_at"] = now_iso
        if not coll.get("connected_since"):
            coll["connected_since"] = now_iso
    else:
        if coll.get("connected_since"):
            coll["last_disconnect_at"] = now_iso
            coll["disconnect_count"] = int(coll.get("disconnect_count", 0)) + 1
            coll["connected_since"] = None
            feed["ws_last_disconnect_at"] = now_iso
            _append_event(state, "collector_disconnect", "binance_live_feed websocket lost")

    if collector_connected and not coll.get("connected_since"):
        coll["connected_since"] = now_iso
        coll["restart_count"] = int(coll.get("restart_count", 0)) + 1

    if parquet_writing:
        feed["write_last_at"] = now_iso
    if pipeline_cycling:
        feed["consume_last_at"] = now_iso

    _save(state)

    runtime_since = state.get("runtime", {}).get("connected_since")
    coll_since = coll.get("connected_since")

    return {
        "runtime_uptime_s": _uptime_seconds(runtime_since),
        "collector_uptime_s": _uptime_seconds(coll_since),
        "websocket_uptime_s": _uptime_seconds(feed.get("ws_last_connected_at") if ws_connected else None),
        "last_disconnect": coll.get("last_disconnect_at") or feed.get("ws_last_disconnect_at"),
        "last_timeout": pipe.get("last_timeout_at"),
        "last_pipeline_stall": pipe.get("last_stall_at"),
        "restart_count": coll.get("restart_count", 0),
        "disconnect_count": coll.get("disconnect_count", 0),
        "last_write_at": feed.get("write_last_at"),
        "last_consume_at": feed.get("consume_last_at"),
        "recent_events": state.get("events", [])[:8],
    }
