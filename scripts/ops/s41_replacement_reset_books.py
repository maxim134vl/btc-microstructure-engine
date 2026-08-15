#!/usr/bin/env python3
"""Archive stuck S4.1 books and install empty per-TF books for replacement cutover.

Does NOT start processes. Does NOT stop LIVE1B (use intrabar_paper_ctl stop first).

  venv/bin/python scripts/ops/s41_replacement_reset_books.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.command_bus import (  # noqa: E402
    COMMAND_COLUMNS,
    PRODUCTION_COMMAND_MEMORY,
    PRODUCTION_LATEST_SNAPSHOT,
    PRODUCTION_MANAGER_STATE,
    PRODUCTION_PORTFOLIO_SUMMARY,
)
from btc_ml.trading.paper_core import (  # noqa: E402
    ORDER_COLUMNS,
    POSITION_COLUMNS,
    SIGNAL_COLUMNS,
    TRADE_COLUMNS,
)
from btc_ml.trading.trader_book import (  # noqa: E402
    CLOSED_TRADE_COLUMNS,
    LEDGER_IDENTITY_COLUMNS,
    PRODUCTION_BOOKS_ROOT,
    atomic_write_json,
    atomic_write_parquet,
)

ACTIVATION_PATH = ROOT / "data" / "trading" / "manager" / "activation.json"
TIMEFRAMES = ("M15", "M30", "H1", "H4")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def reset_books(*, archive_root: Path) -> dict:
    archive_root.mkdir(parents=True, exist_ok=True)
    books_archive = archive_root / "timeframe_traders"
    if PRODUCTION_BOOKS_ROOT.exists():
        shutil.copytree(PRODUCTION_BOOKS_ROOT, books_archive, dirs_exist_ok=True)

    installed = {}
    for tf in TIMEFRAMES:
        root = PRODUCTION_BOOKS_ROOT / tf
        root.mkdir(parents=True, exist_ok=True)
        specs = {
            "signals.parquet": SIGNAL_COLUMNS + ["timeframe", "command_id"] + LEDGER_IDENTITY_COLUMNS,
            "orders.parquet": ORDER_COLUMNS + ["timeframe", "command_id"],
            "fills.parquet": TRADE_COLUMNS + ["timeframe", "command_id"] + LEDGER_IDENTITY_COLUMNS,
            "positions.parquet": POSITION_COLUMNS + ["timeframe", "command_id"] + LEDGER_IDENTITY_COLUMNS,
            "trades.parquet": CLOSED_TRADE_COLUMNS,
        }
        for name, cols in specs.items():
            # de-dupe columns
            seen = []
            for c in cols:
                if c not in seen:
                    seen.append(c)
            atomic_write_parquet(root / name, _empty(seen))
        atomic_write_json(
            root / "controller_state.json",
            {
                "timeframe": tf,
                "processed_command_ids": [],
                "updated_at": _utc_iso(),
                "cutover_reset": True,
            },
        )
        atomic_write_json(
            root / "runtime_status.json",
            {
                "timeframe": tf,
                "status": "RESET_EMPTY",
                "updated_at": _utc_iso(),
            },
        )
        installed[tf] = str(root)
    return {"books_archive": str(books_archive), "installed": installed}


def reset_manager(*, archive_root: Path, activation_boundary: str) -> dict:
    mgr_archive = archive_root / "manager"
    mgr_archive.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in (
        PRODUCTION_COMMAND_MEMORY,
        PRODUCTION_MANAGER_STATE,
        PRODUCTION_PORTFOLIO_SUMMARY,
        PRODUCTION_LATEST_SNAPSHOT,
        ACTIVATION_PATH,
    ):
        if path.exists():
            shutil.copy2(path, mgr_archive / path.name)
            copied.append(path.name)

    atomic_write_parquet(PRODUCTION_COMMAND_MEMORY, _empty(list(COMMAND_COLUMNS)))
    atomic_write_json(
        PRODUCTION_MANAGER_STATE,
        {
            "cycles": 0,
            "timeframes": {},
            "last_manager_cycle_id": None,
            "last_evaluation_timestamp": None,
            "updated_at": _utc_iso(),
            "cutover_reset": True,
            "activation_boundary": activation_boundary,
        },
    )
    atomic_write_json(
        PRODUCTION_PORTFOLIO_SUMMARY,
        {
            "generated_at": _utc_iso(),
            "manager_cycle_id": None,
            "evaluation_timestamp": None,
            "read_model_only": True,
            "traders": {tf: {"timeframe": tf, "open_position": None, "open_risk_usd": 0.0} for tf in TIMEFRAMES},
            "cutover_reset": True,
        },
    )
    atomic_write_json(
        PRODUCTION_LATEST_SNAPSHOT,
        {
            "generated_at": _utc_iso(),
            "cutover_reset": True,
            "activation_boundary": activation_boundary,
            "commands": {},
        },
    )

    activation = {}
    if ACTIVATION_PATH.exists():
        activation = json.loads(ACTIVATION_PATH.read_text(encoding="utf-8"))
    activation["activation_timestamp"] = activation_boundary
    activation["cutover_reset_at"] = _utc_iso()
    activation["cutover_reason"] = "REPLACE_LIVE1B_WITH_S41_INDEPENDENT_TF"
    activation["paper_only"] = True
    activation["execution_enabled"] = False
    atomic_write_json(ACTIVATION_PATH, activation)

    return {
        "manager_archive": str(mgr_archive),
        "copied": copied,
        "activation_boundary": activation_boundary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Perform archive+reset writes")
    parser.add_argument(
        "--activation-boundary",
        type=str,
        default=None,
        help="UTC ISO boundary (default: now)",
    )
    args = parser.parse_args(argv)

    boundary = args.activation_boundary or _utc_iso()
    stamp = _utc_stamp()
    archive_root = ROOT / "data" / "archive" / f"s41_pre_replacement_{stamp}"
    plan = {
        "archive_root": str(archive_root),
        "activation_boundary": boundary,
        "apply": bool(args.apply),
    }
    if not args.apply:
        plan["status"] = "DRY_RUN"
        print(json.dumps(plan, indent=2))
        return 0

    books = reset_books(archive_root=archive_root)
    manager = reset_manager(archive_root=archive_root, activation_boundary=boundary)
    out = {
        "status": "RESET_APPLIED",
        "archive_root": str(archive_root),
        "books": books,
        "manager": manager,
        "next": [
            "Confirm LIVE1B paper stopped",
            "bash scripts/timeframe_trading_ctl.sh start manager",
            "bash scripts/timeframe_trading_ctl.sh start traders",
            "venv/bin/python scripts/research/s41_replacement_preflight.py",
        ],
    }
    summary = archive_root / "cutover_reset_summary.json"
    summary.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
