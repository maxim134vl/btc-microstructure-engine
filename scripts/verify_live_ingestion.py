#!/usr/bin/env python3
"""Verify live market ingestion — parquet freshness, heartbeats, collector processes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)

from collector_health_audit import build_collector_audit, export_collector_health_audit
from collector_heartbeat import read_heartbeat
from collector_registry import COLLECTOR_CRITICAL_SECONDS, COLLECTOR_STALE_SECONDS, REQUIRED_COLLECTORS
from live_feed_paths import read_live_feed
from storage.path_registry import resolve_read, CANONICAL_LIVE_FEED_PATH


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _load_pids() -> dict[str, int]:
    path = os.path.join("data", "live", "collector_pids.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return {k: int(v) for k, v in json.load(handle).items()}


def check_live_feed_freshness() -> dict:
    feed_path = resolve_read(CANONICAL_LIVE_FEED_PATH)
    result = {
        "path": feed_path,
        "exists": os.path.exists(feed_path),
        "fresh": False,
        "age_seconds": None,
        "row_count": 0,
        "latest_timestamp": None,
    }
    if not result["exists"]:
        return result

    age = time.time() - os.path.getmtime(feed_path)
    result["age_seconds"] = round(age, 1)
    result["fresh"] = age <= COLLECTOR_STALE_SECONDS

    try:
        df = read_live_feed()
        result["row_count"] = len(df)
        if len(df) > 0:
            result["latest_timestamp"] = str(df.iloc[-1]["timestamp"])
    except Exception as error:
        result["error"] = str(error)

    return result


def check_websocket_heartbeat() -> dict:
    hb = read_heartbeat("binance_live_feed")
    if hb is None:
        return {"present": False, "fresh": False}

    age = None
    if hb.get("timestamp"):
        age = time.time() - datetime.fromisoformat(hb["timestamp"]).timestamp()

    return {
        "present": True,
        "fresh": age is not None and age <= COLLECTOR_STALE_SECONDS,
        "age_seconds": round(age, 1) if age is not None else None,
        "status": hb.get("status"),
        "event": hb.get("event"),
        "message_count": hb.get("message_count"),
    }


def run_checks() -> dict:
    pids = _load_pids()
    audit = build_collector_audit(pids)
    feed = check_live_feed_freshness()
    ws = check_websocket_heartbeat()

    required_alive = all(
        pids.get(name) and _pid_alive(pids[name]) for name in REQUIRED_COLLECTORS
    )

    checks = {
        "timestamp": datetime.now().isoformat(),
        "feed_fresh": feed.get("fresh", False),
        "feed": feed,
        "websocket_heartbeat_fresh": ws.get("fresh", False),
        "websocket": ws,
        "required_collectors_alive": required_alive,
        "overall": audit["overall"],
        "collectors": audit["collectors"],
        "stale_parquet_count": audit["stale_parquet_count"],
    }

    checks["pass"] = (
        checks["feed_fresh"]
        or checks["websocket_heartbeat_fresh"]
    ) and required_alive and audit["overall"] != "CRITICAL"

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live market ingestion")
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Wait N seconds and re-check parquet mtime advancement",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON only",
    )
    args = parser.parse_args()

    first = run_checks()
    mtime_before = None
    feed_path = first["feed"].get("path")
    if feed_path and os.path.exists(feed_path):
        mtime_before = os.path.getmtime(feed_path)

    advanced = None
    if args.wait > 0:
        time.sleep(args.wait)
        second = run_checks()
        mtime_after = os.path.getmtime(feed_path) if feed_path and os.path.exists(feed_path) else None
        advanced = mtime_after is not None and mtime_before is not None and mtime_after > mtime_before
        second["parquet_mtime_advanced"] = advanced
        first = second

    export_collector_health_audit(_load_pids())

    if args.json:
        print(json.dumps(first, indent=2))
    else:
        print()
        print("LIVE INGESTION VERIFICATION")
        print("=" * 60)
        print(f"Overall audit: {first['overall']}")
        print(f"Feed fresh (≤{COLLECTOR_STALE_SECONDS}s): {first['feed_fresh']}")
        print(f"Feed path: {first['feed'].get('path')}")
        print(f"Feed age: {first['feed'].get('age_seconds')}s")
        print(f"Latest candle: {first['feed'].get('latest_timestamp')}")
        print(f"WS heartbeat fresh: {first['websocket_heartbeat_fresh']}")
        print(f"Required collectors alive: {first['required_collectors_alive']}")
        print(f"Stale parquet count: {first['stale_parquet_count']}")
        if advanced is not None:
            print(f"Parquet mtime advanced after {args.wait}s wait: {advanced}")
        print()
        print(f"Result: {'PASS' if first['pass'] else 'FAIL'}")
        print()

    return 0 if first["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
