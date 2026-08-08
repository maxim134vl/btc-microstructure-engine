"""Collector health audits — exports to reports/collector_health/."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

import pandas as pd

from collector_heartbeat import evaluate_heartbeat_timestamp, read_heartbeat
from collector_registry import COLLECTORS, COLLECTOR_CRITICAL_SECONDS, COLLECTOR_STALE_SECONDS
from storage.path_registry import resolve_read

REPORT_DIR = os.path.join("reports", "collector_health")


def _ensure_dir() -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    return REPORT_DIR


def _parquet_freshness(name: str | None, path_hint: str | None) -> dict[str, Any]:
    if not name and not path_hint:
        return {"exists": False, "freshness": "UNKNOWN"}

    paths = []
    if name:
        try:
            paths.append(resolve_read(name))
        except Exception:
            pass
    if path_hint and os.path.exists(path_hint):
        paths.append(path_hint)

    for path in paths:
        if not os.path.exists(path):
            continue
        age = time.time() - os.path.getmtime(path)
        freshness = "LIVE" if age <= COLLECTOR_STALE_SECONDS else "STALE"
        if age > COLLECTOR_CRITICAL_SECONDS:
            freshness = "CRITICAL"
        row_count = None
        latest_ts = None
        try:
            if path.endswith(".parquet"):
                df = pd.read_parquet(path)
                row_count = len(df)
                if len(df) > 0 and "timestamp" in df.columns:
                    latest_ts = str(pd.to_datetime(df["timestamp"].iloc[-1]))
        except Exception as error:
            return {
                "path": path,
                "exists": True,
                "freshness": "CORRUPT",
                "age_seconds": round(age, 1),
                "error": str(error),
            }
        return {
            "path": path,
            "exists": True,
            "freshness": freshness,
            "age_seconds": round(age, 1),
            "mtime": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
            "row_count": row_count,
            "latest_timestamp": latest_ts,
        }

    return {"exists": False, "freshness": "MISSING", "paths_checked": paths}


def build_collector_audit(running_pids: dict[str, int] | None = None) -> dict[str, Any]:
    running_pids = running_pids or {}
    collectors: list[dict[str, Any]] = []

    for spec in COLLECTORS:
        hb = read_heartbeat(spec["name"])
        hb_age = None
        hb_time = {
            "valid": False,
            "freshness_status": "missing",
            "age_seconds": None,
        }
        if hb and hb.get("timestamp"):
            hb_time = evaluate_heartbeat_timestamp(hb["timestamp"])
            hb_age = hb_time.get("age_seconds")

        parquet = _parquet_freshness(
            spec.get("output_parquet"),
            spec.get("output_path"),
        )

        pid = running_pids.get(spec["name"])
        process_alive = pid is not None and _pid_alive(pid)

        if process_alive and parquet.get("freshness") == "LIVE":
            status = "CONNECTED"
            level = "GREEN"
        elif (
            process_alive
            and hb
            and hb_time.get("valid")
            and hb_age is not None
            and hb_age <= COLLECTOR_STALE_SECONDS
        ):
            status = "CONNECTED"
            level = "GREEN" if spec.get("kind") == "websocket" else "YELLOW"
        elif process_alive and parquet.get("freshness") in ("STALE", "CRITICAL"):
            status = "DEGRADED"
            level = "YELLOW"
        elif (
            hb
            and hb_time.get("valid")
            and hb_age is not None
            and hb_age <= COLLECTOR_STALE_SECONDS
        ):
            status = "DEGRADED"
            level = "YELLOW"
        else:
            status = "DISCONNECTED"
            level = "RED"

        collectors.append(
            {
                **spec,
                "status": status,
                "level": level,
                "pid": pid,
                "process_alive": process_alive,
                "heartbeat": hb,
                "heartbeat_age_seconds": round(hb_age, 1) if hb_age is not None else None,
                "heartbeat_timestamp_valid": bool(hb_time.get("valid")),
                "heartbeat_timestamp_status": hb_time.get("freshness_status"),
                "heartbeat_timestamp_utc": hb_time.get("timestamp_utc"),
                "heartbeat_future_offset_seconds": hb_time.get("future_offset_seconds"),
                "parquet": parquet,
            }
        )

    stale_parquets = [c["parquet"] for c in collectors if c.get("parquet", {}).get("freshness") in ("STALE", "CRITICAL")]
    missing = [c for c in collectors if c["status"] == "DISCONNECTED" and c.get("required")]

    if missing:
        overall = "CRITICAL"
    elif any(c["status"] == "DEGRADED" for c in collectors):
        overall = "DEGRADED"
    elif stale_parquets and not any(
        c.get("kind") == "websocket" and c["status"] == "CONNECTED" for c in collectors
    ):
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"

    return {
        "generated_at": datetime.now().isoformat(),
        "overall": overall,
        "collectors": collectors,
        "stale_parquet_count": len(stale_parquets),
        "disconnected_required": [c["name"] for c in missing],
    }


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def export_collector_health_audit(running_pids: dict[str, int] | None = None) -> dict[str, str]:
    report_dir = _ensure_dir()
    audit = build_collector_audit(running_pids)

    paths = {
        "collector_health_audit": os.path.join(report_dir, "collector_health_audit.json"),
        "parquet_freshness_audit": os.path.join(report_dir, "parquet_freshness_audit.json"),
        "ingress_chain_audit": os.path.join(report_dir, "ingress_chain_audit.json"),
    }

    with open(paths["collector_health_audit"], "w", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2)

    parquet_rows = [c["parquet"] for c in audit["collectors"] if c.get("parquet")]
    with open(paths["parquet_freshness_audit"], "w", encoding="utf-8") as handle:
        json.dump(
            {
                "generated_at": audit["generated_at"],
                "rows": parquet_rows,
                "stale_count": audit["stale_parquet_count"],
            },
            handle,
            indent=2,
        )

    chain = {
        "generated_at": audit["generated_at"],
        "chain": [
            "exchange",
            "websocket/rest collector",
            "parser",
            "parquet writer",
            "data/live",
            "runtime readers (candle_structure_engine)",
        ],
        "breakpoints": [],
    }
    for collector in audit["collectors"]:
        if collector["status"] == "DISCONNECTED":
            chain["breakpoints"].append(
                {
                    "stage": "collector process",
                    "collector": collector["name"],
                    "reason": "process not alive / no heartbeat",
                }
            )
        elif (
            collector.get("parquet", {}).get("freshness") in ("STALE", "CRITICAL", "MISSING")
            and collector["status"] != "CONNECTED"
        ):
            chain["breakpoints"].append(
                {
                    "stage": "parquet writer",
                    "collector": collector["name"],
                    "reason": collector["parquet"].get("freshness"),
                    "path": collector["parquet"].get("path"),
                }
            )

    with open(paths["ingress_chain_audit"], "w", encoding="utf-8") as handle:
        json.dump(chain, handle, indent=2)

    return paths
