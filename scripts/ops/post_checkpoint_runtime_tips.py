"""Sample the runtime tips used for natural-cycle validation.

Read-only: opens datasets and payloads, writes nothing outside the report path
passed on the command line.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/fontecrypto/btc-ml")
PUBLIC = ROOT / "apps/context_visualizer/public/data"

PROCESSES = {
    "live_feed": "live_binance_intrabar_feed.py",
    "canonical_pipeline": "run_canonical_pipeline",
    "context_refresher": "run_context_refresh_daemon.py",
    "visual_refresher": "run_market_context_visual_refresher.py",
    "manager": "timeframe_manager_daemon.py",
    "trader_M15": "--timeframe M15",
    "trader_M30": "--timeframe M30",
    "trader_H1": "--timeframe H1",
    "trader_H4": "--timeframe H4",
    "ops_backend": "uvicorn",
}


def _iso(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _tail(path: Path, column: str) -> str | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path, columns=[column])
    except Exception:
        return None
    if not len(frame):
        return None
    values = pd.Series([pd.to_datetime(v, utc=True, errors="coerce") for v in frame[column]])
    return _iso(values.max())


def pids() -> dict:
    listing = subprocess.run(["ps", "-eo", "pid,command"], capture_output=True, text=True).stdout
    found = {}
    for name, pattern in PROCESSES.items():
        matches = [
            int(line.split(None, 1)[0])
            for line in listing.splitlines()
            if pattern in line and "post_checkpoint_runtime_tips" not in line
        ]
        found[name] = matches
    return found


def sample() -> dict:
    now = datetime.now(timezone.utc)
    market = _tail(ROOT / "data/live/live_market_feed.parquet", "timestamp")
    context = _tail(ROOT / "data/cognition/market_context_lifecycle_memory.parquet", "timestamp")
    decision = _tail(ROOT / "data/live/context_decision_log.parquet", "candle_timestamp")

    manager = None
    manager_path = ROOT / "data/trading/manager/timeframe_command_memory.parquet"
    if manager_path.exists():
        for column in ("cycle_timestamp", "timestamp", "candle_timestamp"):
            manager = _tail(manager_path, column)
            if manager:
                break

    visual_generated_at = None
    visual_status = None
    closed_trades = None
    open_positions = None
    payload = PUBLIC / "closed_trades.json"
    if payload.exists():
        try:
            data = json.loads(payload.read_text())
            visual_generated_at = data.get("generated_at_utc") or data.get("generated_at")
            visual_status = data.get("visual_status") or data.get("status")
            trades = data.get("trades") or data.get("closed_trades") or []
            closed_trades = len(trades)
            open_positions = data.get("open_positions")
            if isinstance(open_positions, list):
                open_positions = len(open_positions)
        except Exception:
            pass

    lag = None
    if visual_generated_at:
        try:
            lag = round(
                (now - pd.Timestamp(visual_generated_at).tz_convert("UTC").to_pydatetime())
                .total_seconds(),
                1,
            )
        except Exception:
            lag = None

    return {
        "sampled_at": now.isoformat().replace("+00:00", "Z"),
        "market_tip": market,
        "context_tip": context,
        "decision_tip": decision,
        "manager_tip": manager,
        "visual_generated_at": visual_generated_at,
        "visual_status": visual_status,
        "visual_closed_trades": closed_trades,
        "visual_open_positions": open_positions,
        "lag_seconds": lag,
        "pids": pids(),
    }


if __name__ == "__main__":
    result = sample()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
