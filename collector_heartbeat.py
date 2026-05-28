"""Collector heartbeat I/O — operational ingress monitoring only."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from storage.path_registry import repo_root

HEARTBEAT_DIR = repo_root() / "data" / "live" / "collector_heartbeats"


def heartbeat_path(collector_name: str) -> str:
    safe = collector_name.replace("/", "_")
    return str(HEARTBEAT_DIR / f"{safe}.json")


def write_heartbeat(
    collector_name: str,
    *,
    status: str = "ALIVE",
    event: str = "tick",
    message_count: int | None = None,
    last_error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    os.makedirs(HEARTBEAT_DIR, exist_ok=True)
    payload: dict[str, Any] = {
        "collector": collector_name,
        "status": status,
        "event": event,
        "timestamp": datetime.now().isoformat(),
    }
    if message_count is not None:
        payload["message_count"] = message_count
    if last_error is not None:
        payload["last_error"] = last_error
    if extra:
        payload.update(extra)

    path = heartbeat_path(collector_name)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp, path)


def read_heartbeat(collector_name: str) -> dict[str, Any] | None:
    path = heartbeat_path(collector_name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None
