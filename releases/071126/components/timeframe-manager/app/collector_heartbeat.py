"""Collector heartbeat I/O — operational ingress monitoring only."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from storage.path_registry import repo_root

HEARTBEAT_DIR = repo_root() / "data" / "live" / "collector_heartbeats"
FUTURE_CLOCK_SKEW_TOLERANCE_SECONDS = 5.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def evaluate_heartbeat_timestamp(
    timestamp: Any,
    *,
    now_utc: datetime | None = None,
    future_tolerance_seconds: float = FUTURE_CLOCK_SKEW_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Normalize heartbeat time to UTC and classify future timestamps safely."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    try:
        raw = str(timestamp).strip()
        if not raw:
            raise ValueError("empty timestamp")
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        timezone_assumed = parsed.tzinfo is None
        if timezone_assumed:
            # Legacy heartbeat strings had no offset. Treat them as UTC so they
            # can never inherit the host's local timezone implicitly.
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        return {
            "valid": False,
            "freshness_status": "invalid_timestamp",
            "age_seconds": None,
            "timestamp_utc": None,
            "timezone_assumed_utc": False,
            "error": str(exc),
        }

    delta_seconds = (now - parsed).total_seconds()
    if delta_seconds < -float(future_tolerance_seconds):
        return {
            "valid": False,
            "freshness_status": "future_timestamp",
            "age_seconds": None,
            "future_offset_seconds": round(-delta_seconds, 6),
            "timestamp_utc": parsed.isoformat().replace("+00:00", "Z"),
            "timezone_assumed_utc": timezone_assumed,
        }

    return {
        "valid": True,
        "freshness_status": "clock_skew_tolerated" if delta_seconds < 0 else "valid",
        "age_seconds": max(0.0, delta_seconds),
        "future_offset_seconds": max(0.0, -delta_seconds),
        "timestamp_utc": parsed.isoformat().replace("+00:00", "Z"),
        "timezone_assumed_utc": timezone_assumed,
    }


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
        "timestamp": utc_now_iso(),
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
