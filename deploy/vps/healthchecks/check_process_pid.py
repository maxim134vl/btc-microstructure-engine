#!/usr/bin/env python3
"""Generic process readiness via pid file and/or health JSON under data/runtime or run/."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app"))


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid-file", type=Path, default=None)
    ap.add_argument(
        "--health-file",
        type=Path,
        action="append",
        default=[],
        help="Relative to repo root or absolute; may repeat",
    )
    ap.add_argument(
        "--allow-missing-health",
        action="store_true",
        help="Pass if pid is alive even when health JSON is not yet present",
    )
    ap.add_argument("--name", default="process")
    args = ap.parse_args()

    pid_path = args.pid_file
    if pid_path is not None and not pid_path.is_absolute():
        pid_path = REPO / pid_path

    pid = _read_pid(pid_path) if pid_path is not None else None
    pid_ok = _alive(pid) if pid_path is not None else True

    health_ok = True
    health_hit: Path | None = None
    if args.health_file:
        health_ok = False
        for rel in args.health_file:
            path = rel if rel.is_absolute() else REPO / rel
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            status = str(payload.get("status") or payload.get("state") or payload.get("service_status") or "")
            if status.upper() in {"FAILED", "UNHEALTHY", "CRITICAL", "REFUSED"}:
                print(f"UNHEALTHY: {args.name} health_status={status} path={path}")
                return 1
            health_ok = True
            health_hit = path
            break
        if not health_ok and args.allow_missing_health and pid_ok:
            print(f"HEALTHY_OR_STARTING: {args.name} pid={pid} health=pending")
            return 0
        if not health_ok:
            print(f"STARTING: {args.name} missing health artifact")
            return 1

    if pid_path is not None and not pid_ok:
        print(f"UNHEALTHY: {args.name} pid_dead path={pid_path} pid={pid}")
        return 1

    print(f"HEALTHY: {args.name} pid={pid} health={health_hit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
