#!/usr/bin/env python3
"""Hybrid cutover: S4.1 manager + LIVE1B execution/books/capital.

Stops S4.1 traders (no dual writers), restores LIVE1B ACTIVE epoch,
archives current S4.1 opens, seeds command consume-after boundary,
restarts LIVE1B paper + S4.1 manager.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = REPO / "data" / "archive" / f"s41_hybrid_cutover_{stamp}"
    report: dict = {"stamp": stamp, "archive": str(archive), "executed": bool(args.execute)}

    if not args.execute:
        report["status"] = "DRY_RUN"
        print(json.dumps(report, indent=2))
        print("Re-run with --execute to apply.")
        return 0

    archive.mkdir(parents=True, exist_ok=True)

    # 1) Stop S4.1 traders only
    stop = _run(["bash", "scripts/timeframe_trading_ctl.sh", "stop", "traders"])
    report["stop_traders"] = {"rc": stop.returncode, "out": stop.stdout[-2000:], "err": stop.stderr[-1000:]}

    # 2) Archive + clear S4.1 books (manager must not see ghost opens)
    tf_root = REPO / "data" / "trading" / "timeframe_traders"
    archived_books = archive / "timeframe_traders"
    if tf_root.exists():
        shutil.copytree(tf_root, archived_books, dirs_exist_ok=True)
    for tf in ("M15", "M30", "H1", "H4"):
        book = tf_root / tf
        book.mkdir(parents=True, exist_ok=True)
        # Empty positions/trades via existing reset helper if present; else wipe parquet.
        for name in ("positions.parquet", "trades.parquet", "orders.parquet", "fills.parquet"):
            path = book / name
            if path.exists():
                path.unlink()
        # Keep controller_state but clear open id
        state_path = book / "controller_state.json"
        state = {}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {}
        if not isinstance(state, dict):
            state = {}
        state.update(
            {
                "open_position_id": None,
                "last_result": "HYBRID_CUTOVER_CLEARED",
                "last_reason": "S41_TRADERS_STOPPED_LIVE1B_OWNS_BOOKS",
                "updated_at": _utc(),
                "hybrid_cutover_at": _utc(),
            }
        )
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Recreate empty parquet stubs expected by tooling
    try:
        import pandas as pd

        from btc_ml.trading.trader_book import POSITION_COLUMNS, TRADE_COLUMNS, TraderBook, atomic_write_parquet

        for tf in ("M15", "M30", "H1", "H4"):
            book = TraderBook.production(tf)
            book.ensure_dirs()
            atomic_write_parquet(
                book.positions,
                pd.DataFrame(columns=POSITION_COLUMNS + ["timeframe", "command_id"]),
            )
            atomic_write_parquet(
                book.trades,
                pd.DataFrame(columns=TRADE_COLUMNS + ["timeframe", "command_id"]),
            )
    except Exception as exc:  # noqa: BLE001
        report["book_reset_warning"] = f"{type(exc).__name__}: {exc}"

    # 3) Restore LIVE1B active epoch
    active_path = REPO / "data" / "trading" / "paper_epochs" / "active.json"
    before = json.loads(active_path.read_text(encoding="utf-8"))
    (archive / "active.json.before").write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")
    restored = dict(before)
    restored["epoch_status"] = "ACTIVE"
    restored["closed_at"] = None
    restored.pop("closed_reason", None)
    restored.pop("superseded_by", None)
    restored["paper_execution_owner"] = "LIVE1B_INTRABAR_PAPER"
    restored["reactivated_at"] = _utc()
    restored["reactivation_reason"] = "S41_LIVE1B_HYBRID"
    active_path.write_text(json.dumps(restored, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["active_epoch"] = restored.get("paper_epoch_id")

    # 4) Activation hybrid pointer + consume-after = now (skip failed-cutover OPENs)
    consume_after = _utc()
    activation_path = REPO / "data" / "trading" / "manager" / "activation.json"
    activation = json.loads(activation_path.read_text(encoding="utf-8"))
    (archive / "activation.json.before").write_text(json.dumps(activation, indent=2) + "\n", encoding="utf-8")
    activation["execution_owner"] = "LIVE1B_INTRABAR_PAPER"
    activation["hybrid"] = {
        "enabled": True,
        "position_source": "live1b_epoch_books",
        "entry_source": "s41_command_bus",
        "consume_commands_after": consume_after,
        "cutover_at": consume_after,
        "note": "S4.1 manager commands; LIVE1B books/capital/PnL",
    }
    activation_path.write_text(json.dumps(activation, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # 5) Config consume-after
    cfg_path = REPO / "config" / "intrabar_paper_execution.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    (archive / "intrabar_paper_execution.json.before").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    cfg["entry_source"] = "s41_command_bus"
    cfg["s41_consume_commands_after"] = consume_after
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    # Keep manager_state episode seeds (prevent mid-context re-entry)
    mgr_state_path = REPO / "data" / "trading" / "manager" / "manager_state.json"
    if mgr_state_path.exists():
        shutil.copy2(mgr_state_path, archive / "manager_state.json")
        mgr_state = json.loads(mgr_state_path.read_text(encoding="utf-8"))
        mgr_state["hybrid_cutover_at"] = consume_after
        mgr_state["execution_owner"] = "LIVE1B_INTRABAR_PAPER"
        mgr_state_path.write_text(json.dumps(mgr_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    pointer = REPO / "data" / "trading" / "paper_epochs" / "s41_active_pointer.json"
    if pointer.exists():
        shutil.move(str(pointer), str(archive / "s41_active_pointer.json"))

    # 6) Restart LIVE1B paper + manager (code reload for views)
    paper = _run([str(REPO / "venv" / "bin" / "python"), "scripts/live/intrabar_paper_ctl.py", "restart"])
    report["paper_restart"] = {"rc": paper.returncode, "out": paper.stdout[-2000:], "err": paper.stderr[-1000:]}
    mgr = _run(["bash", "scripts/timeframe_trading_ctl.sh", "restart", "manager"])
    report["manager_restart"] = {"rc": mgr.returncode, "out": mgr.stdout[-2000:], "err": mgr.stderr[-1000:]}
    status = _run(["bash", "scripts/timeframe_trading_ctl.sh", "status"])
    report["status_out"] = status.stdout
    report["consume_after"] = consume_after
    report["status"] = "APPLIED"
    (archive / "cutover_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if paper.returncode == 0 else 1


if __name__ == "__main__":
    # ensure src import for TraderBook
    sys.path.insert(0, str(REPO / "src"))
    raise SystemExit(main())
