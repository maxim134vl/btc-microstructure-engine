#!/usr/bin/env python3
"""S4.1 preflight: baseline inventory + legacy migration mode.

Read-only. Writes data/research/s4_1_preflight_<timestamp>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.paper_core import core_fingerprint  # noqa: E402
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402
from btc_ml.trading.timeframe_state_adapter import (  # noqa: E402
    SUPPORTED_TIMEFRAMES,
    UNSUPPORTED_TIMEFRAMES,
    load_sources,
    resolve_all_states,
)

LEGACY_PAPER_DIR = ROOT / "data" / "research" / "paper_simulator"
LEGACY_PID = ROOT / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
AVAILABILITY_LATEST = ROOT / "data" / "runtime" / "multi_timeframe_availability_latest.json"

MODE_EMPTY = "EMPTY"
MODE_CLOSED_HISTORY_ONLY = "CLOSED_HISTORY_ONLY"
MODE_OPEN_POSITION_PRESENT = "OPEN_POSITION_PRESENT"
MODE_AMBIGUOUS = "AMBIGUOUS"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def legacy_migration_mode() -> dict[str, Any]:
    positions_path = LEGACY_PAPER_DIR / "paper_positions.parquet"
    trades_path = LEGACY_PAPER_DIR / "paper_trades.parquet"
    detail: dict[str, Any] = {
        "positions_path": str(positions_path.relative_to(ROOT)),
        "positions_exists": positions_path.exists(),
        "rows": 0,
        "open_rows": 0,
        "closed_rows": 0,
        "unknown_status_rows": 0,
        "trades_rows": 0,
    }
    if trades_path.exists():
        try:
            detail["trades_rows"] = int(len(pd.read_parquet(trades_path)))
        except Exception as exc:
            detail["trades_read_error"] = str(exc)
    if not positions_path.exists():
        detail["mode"] = MODE_EMPTY
        return detail
    try:
        frame = pd.read_parquet(positions_path)
    except Exception as exc:
        detail["mode"] = MODE_AMBIGUOUS
        detail["read_error"] = str(exc)
        return detail
    detail["rows"] = int(len(frame))
    if not len(frame):
        detail["mode"] = MODE_EMPTY
        return detail
    status = frame["status"].astype(str).str.upper() if "status" in frame.columns else pd.Series(dtype=str)
    detail["open_rows"] = int((status == "OPEN").sum())
    detail["closed_rows"] = int((status == "CLOSED").sum())
    detail["unknown_status_rows"] = int(len(status) - detail["open_rows"] - detail["closed_rows"])
    if detail["open_rows"] > 0:
        detail["mode"] = MODE_OPEN_POSITION_PRESENT
        detail["blocking_status"] = "S4_ACTIVATION_BLOCKED_BY_LEGACY_OPEN_POSITION"
    elif detail["unknown_status_rows"] > 0:
        detail["mode"] = MODE_AMBIGUOUS
    else:
        detail["mode"] = MODE_CLOSED_HISTORY_ONLY
    return detail


def running_processes() -> dict[str, Any]:
    try:
        out = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except Exception as exc:
        return {"error": str(exc)}
    wanted = {
        "legacy_paper_controller": "bounded_paper_trading_controller_auto_ledger_no_real_execution.py",
        "pipeline": "canonical_pipeline",
        "context_refresher": "run_market_context_visual_refresher.py",
        "context_refresh_daemon": "context_refresh_daemon",
        "intrabar_feed": "intrabar",
        "timeframe_manager": "timeframe_manager_daemon.py",
        "trader_M15": "timeframe_trader_daemon.py --timeframe M15",
        "trader_M30": "timeframe_trader_daemon.py --timeframe M30",
        "trader_H1": "timeframe_trader_daemon.py --timeframe H1",
        "trader_H4": "timeframe_trader_daemon.py --timeframe H4",
    }
    found: dict[str, list[int]] = {name: [] for name in wanted}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, _, command = line.partition(" ")
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        for name, needle in wanted.items():
            if needle in command and "ps -ax" not in command:
                found[name].append(pid)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(ROOT / "data" / "research"))
    args = parser.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    availability_latest: dict[str, Any] = {}
    if AVAILABILITY_LATEST.exists():
        availability_latest = json.loads(AVAILABILITY_LATEST.read_text(encoding="utf-8"))

    evaluation_ts = availability_latest.get("latest_evaluation_timestamp")
    sources = load_sources()
    states = resolve_all_states(evaluation_timestamp=evaluation_ts, sources=sources) if evaluation_ts else {}
    risk = PortfolioRiskCoordinator.load()

    payload = {
        "generated_at": _now(),
        "stage": "S4_1_PREFLIGHT",
        "read_only": True,
        "asset": "BTCUSDT",
        "supported_timeframes": list(SUPPORTED_TIMEFRAMES),
        "unsupported_timeframes": list(UNSUPPORTED_TIMEFRAMES),
        "shared_execution_core": core_fingerprint(),
        "risk_config": {
            "portfolio_max_risk_usd": risk.portfolio_max_risk_usd,
            "per_trader_max_risk_usd": risk.per_trader_max_risk_usd,
            "weights": risk.weights,
            "auto_reallocation_of_unused_risk": risk.auto_reallocation,
        },
        "mtf_availability_latest": {
            "generated_at": availability_latest.get("generated_at"),
            "latest_evaluation_timestamp": evaluation_ts,
            "overall_health": availability_latest.get("overall_health"),
            "status_counts": availability_latest.get("status_counts"),
        },
        "timeframe_states": states,
        "legacy_paper_ledger": legacy_migration_mode(),
        "legacy_controller_pid_file": {
            "path": str(LEGACY_PID.relative_to(ROOT)),
            "exists": LEGACY_PID.exists(),
            "pid": LEGACY_PID.read_text(encoding="utf-8").strip() if LEGACY_PID.exists() else None,
        },
        "processes": running_processes(),
        "environment": {
            "BTC_ML_CONTINUATION_PROGRESSION": os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0"),
            "PRICE_GATE": os.environ.get("PRICE_GATE", "OFF"),
        },
        "safety": {
            "paper_only": True,
            "real_execution": False,
            "exchange_enabled": False,
            "d1_trader": False,
        },
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"s4_1_preflight_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"preflight_path": str(out_path.relative_to(ROOT)), "legacy_mode": payload["legacy_paper_ledger"]["mode"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
