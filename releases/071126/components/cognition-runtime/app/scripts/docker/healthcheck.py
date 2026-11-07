#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fresh(path: str, limit: float) -> bool:
    try:
        data = json.loads((ROOT / path).read_text())
        stamp = data.get("updated_at") or data.get("last_heartbeat_at") or data.get("heartbeat_at_utc")
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() <= limit
    except Exception:
        return False


def load(path: str) -> dict:
    try:
        value = json.loads((ROOT / path).read_text())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


status = load("run/docker_model_runtime_status.json")
paper = load("data/runtime/intrabar_paper_health.json")
market = ((paper.get("execution_market") or {}).get("state") or {})
pid = status.get("pid")
pid_alive = False
try:
    os.kill(int(pid), 0)
    pid_alive = True
except (OSError, TypeError, ValueError):
    pass

ok = (
    pid_alive
    and status.get("state") == "READY"
    and fresh("run/live_binance_intrabar_feed_heartbeat.json", 150)
    and fresh("data/runtime/intrabar_cognition_health.json", 60)
    and fresh("data/runtime/intrabar_paper_health.json", 60)
    and paper.get("paper_only") is True
    and paper.get("real_execution_enabled") is False
    and paper.get("manager_status") == "CONNECTED"
    and market.get("state") == "HEALTHY"
    and market.get("unresolved_gap") is False
    and market.get("book_ticker_stream_fresh") is True
    and market.get("agg_trade_stream_fresh") is True
    and market.get("entry_allowed") is True
    and market.get("wal_write_failures", 0) == 0
)
sys.exit(0 if ok else 1)
