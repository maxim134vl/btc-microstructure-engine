#!/usr/bin/env python3
"""Collector process watchdog — start, monitor, restart ingress layer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from collector_health_audit import build_collector_audit, export_collector_health_audit
from collector_heartbeat import write_heartbeat
from collector_registry import COLLECTORS, COLLECTOR_CRITICAL_SECONDS, COLLECTOR_STALE_SECONDS

PID_FILE = os.path.join("data", "live", "collector_pids.json")
CHECK_INTERVAL_S = 30


def _repo_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _load_pids() -> dict[str, int]:
    if not os.path.exists(PID_FILE):
        return {}
    try:
        with open(PID_FILE, encoding="utf-8") as handle:
            return {k: int(v) for k, v in json.load(handle).items()}
    except Exception:
        return {}


def _save_pids(pids: dict[str, int]) -> None:
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    temp = PID_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(pids, handle, indent=2)
    os.replace(temp, PID_FILE)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start_collector(name: str, python: str, root: str) -> int | None:
    spec = next((c for c in COLLECTORS if c["name"] == name), None)
    if spec is None:
        return None

    script = os.path.join(root, spec["script"])
    if not os.path.exists(script):
        print(f"  [SKIP] {name}: script missing {script}")
        return None

    log_dir = os.path.join(root, "reports", "collector_health", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{name}.log")

    log_handle = open(log_path, "a", encoding="utf-8")
    log_handle.write(f"\n--- START {datetime.now().isoformat()} ---\n")
    log_handle.flush()

    proc = subprocess.Popen(
        [python, script],
        cwd=root,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    print(f"  [START] {name} pid={proc.pid}")
    write_heartbeat(name, status="STARTING", event="watchdog_start", extra={"pid": proc.pid})
    return proc.pid


def start_all(python: str, root: str, only_required: bool = False) -> dict[str, int]:
    pids: dict[str, int] = {}
    for spec in COLLECTORS:
        if only_required and not spec.get("required"):
            continue
        pid = start_collector(spec["name"], python, root)
        if pid:
            pids[spec["name"]] = pid
    _save_pids(pids)
    return pids


def supervise(python: str, root: str, only_required: bool = False) -> None:
    print()
    print("COLLECTOR WATCHDOG")
    print("=" * 60)
    print(f"Root: {root}")
    print(f"Check interval: {CHECK_INTERVAL_S}s")
    print()

    pids = _load_pids()
    if not pids:
        print("Starting collectors...")
        pids = start_all(python, root, only_required=only_required)

    while True:
        audit = build_collector_audit(pids)
        export_collector_health_audit(pids)

        for spec in COLLECTORS:
            if only_required and not spec.get("required"):
                continue
            name = spec["name"]
            pid = pids.get(name)
            needs_restart = False

            if pid is None or not _pid_alive(pid):
                print(f"[{datetime.now().isoformat()}] RESTART {name}: process dead")
                needs_restart = True
            else:
                collector = next(c for c in audit["collectors"] if c["name"] == name)
                hb_age = collector.get("heartbeat_age_seconds")
                parquet_age = collector.get("parquet", {}).get("age_seconds")
                if hb_age is not None and hb_age > COLLECTOR_CRITICAL_SECONDS:
                    print(f"[{datetime.now().isoformat()}] RESTART {name}: heartbeat stale ({hb_age}s)")
                    needs_restart = True
                elif parquet_age is not None and parquet_age > COLLECTOR_CRITICAL_SECONDS and spec.get("required"):
                    print(f"[{datetime.now().isoformat()}] RESTART {name}: parquet stale ({parquet_age}s)")
                    needs_restart = True

            if needs_restart:
                if pid and _pid_alive(pid):
                    try:
                        os.kill(pid, 15)
                    except OSError:
                        pass
                new_pid = start_collector(name, python, root)
                if new_pid:
                    pids[name] = new_pid
                    _save_pids(pids)

        write_heartbeat(
            "watchdog",
            status="ALIVE",
            event="supervise_tick",
            extra={"managed_pids": pids, "overall": audit["overall"]},
        )
        time.sleep(CHECK_INTERVAL_S)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collector watchdog")
    parser.add_argument("--audit-only", action="store_true", help="Export audit and exit")
    parser.add_argument("--start-only", action="store_true", help="Start collectors once and exit")
    parser.add_argument("--required-only", action="store_true", help="Manage required collectors only")
    args = parser.parse_args()

    root = _repo_root()
    os.chdir(root)
    python = sys.executable

    if args.audit_only:
        paths = export_collector_health_audit(_load_pids())
        audit = build_collector_audit(_load_pids())
        print(json.dumps({"overall": audit["overall"], "exports": paths}, indent=2))
        return 0 if audit["overall"] != "CRITICAL" else 1

    if args.start_only:
        start_all(python, root, only_required=args.required_only)
        export_collector_health_audit(_load_pids())
        return 0

    try:
        supervise(python, root, only_required=args.required_only)
    except KeyboardInterrupt:
        print("\nWatchdog stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
