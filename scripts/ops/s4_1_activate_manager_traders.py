#!/usr/bin/env python3
"""S4.1 — production activation of the manager and four independent traders.

Sequence (S4.1 §23):
  1. re-check current runtime
  2. evaluate activation gates from the candidate proofs
  3. create production backups + manifest
  4. stop ONLY the legacy global paper controller, confirm no zombie
  5. archive the legacy paper ledger as a read-only historical book
  6. record the activation boundary (command bus starts here)
  7. start manager + M15/M30/H1/H4 traders, one PID each
  8. verify independent cursors, single writer per book, OPS bindings

Feed, pipeline, context refresher and the MTF availability writer are never
restarted. Paper only: no exchange calls, no real execution, D1 trader never
created.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from btc_ml.trading import activation, process_lock  # noqa: E402
from btc_ml.trading.command_bus import CommandBus, CommandBusPaths  # noqa: E402
from btc_ml.trading.timeframe_state_adapter import SUPPORTED_TIMEFRAMES  # noqa: E402
from btc_ml.trading.trader_book import TraderBook, atomic_write_json  # noqa: E402

APPROVAL_FLAG = "--approved-s4-1-production-activation"
CTL = ROOT / "scripts" / "timeframe_trading_ctl.sh"
LEGACY_CTL = ROOT / "scripts" / "bounded_paper_trading_controller_ctl.sh"
ROLES = ("timeframe_manager", *(f"trader_{tf}" for tf in SUPPORTED_TIMEFRAMES))

MUST_NOT_RESTART = (
    "live_binance_intrabar_feed.py",
    "run.py",
    "run_context_refresh_daemon.py",
)


def _run(cmd: list[str], *, timeout: float = 120.0) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        return {
            "cmd": " ".join(cmd),
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"cmd": " ".join(cmd), "returncode": -1, "error": f"{type(exc).__name__}: {exc}"}


def runtime_snapshot() -> dict[str, Any]:
    from ops_dashboard_runtime_truth import build_runtime_truth_snapshot

    snapshot = build_runtime_truth_snapshot()
    return {
        "overall_health": snapshot.get("overall_health"),
        "overall_reason": snapshot.get("overall_reason"),
        "processes": {
            p["process_id"]: {"health": p["health"], "pid": p["pid"]} for p in snapshot.get("processes") or []
        },
        "timeframe_traders": snapshot.get("timeframe_traders"),
        "paper": {
            "representation": (snapshot.get("paper") or {}).get("representation"),
            "health": (snapshot.get("paper") or {}).get("health"),
        },
    }


def preserved_process_pids() -> dict[str, list[int]]:
    return {needle: activation.process_pids(needle) for needle in MUST_NOT_RESTART}


def stop_legacy_controller() -> dict[str, Any]:
    before = activation.legacy_controller_pids()
    result = _run(["bash", str(LEGACY_CTL), "stop"]) if before else {"cmd": "skipped", "returncode": 0}
    deadline = time.time() + 30
    after = activation.legacy_controller_pids()
    while after and time.time() < deadline:
        time.sleep(1)
        after = activation.legacy_controller_pids()
    return {
        "pids_before": before,
        "pids_after": after,
        "stopped": not after,
        "zombie_detected": bool(after),
        "ctl": result,
    }


def start_roles() -> dict[str, Any]:
    started: dict[str, Any] = {}
    for role in ROLES:
        target = "manager" if role == "timeframe_manager" else role.replace("trader_", "")
        started[role] = _run(["bash", str(CTL), "start", target])
        time.sleep(1)
    time.sleep(3)
    for role in ROLES:
        started[role]["status"] = process_lock.status(role)
    return started


def verify_processes() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    single_writer = True
    for role in ROLES:
        needle = (
            "timeframe_manager_daemon.py"
            if role == "timeframe_manager"
            else f"timeframe_trader_daemon.py --timeframe {role.replace('trader_', '')}"
        )
        pids = activation.process_pids(needle)
        state = process_lock.status(role)
        ok = len(pids) == 1 and state.get("alive") is True
        single_writer = single_writer and len(pids) <= 1
        checks[role] = {
            "pids": pids,
            "pid_file": state.get("pid"),
            "alive": state.get("alive"),
            "single_process": len(pids) == 1,
            "ok": ok,
        }
    return {"roles": checks, "single_writer_per_book": single_writer}


def verify_independent_cursors() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tf in SUPPORTED_TIMEFRAMES:
        book = TraderBook.production(tf)
        state = book.load_controller_state()
        commands = book.signals_frame()
        foreign = 0
        if len(commands) and "timeframe" in commands.columns:
            foreign = int((commands["timeframe"].astype(str).str.upper() != tf).sum())
        out[tf] = {
            "cursor_evaluation_timestamp": state.get("cursor_evaluation_timestamp"),
            "processed_commands": len(state.get("processed_command_ids") or []),
            "foreign_timeframe_rows": foreign,
            "book_root": str(book.root.relative_to(ROOT)),
        }
    cursors = [v["cursor_evaluation_timestamp"] for v in out.values()]
    return {
        "traders": out,
        "independent_state_files": True,
        "cross_trader_rows": sum(v["foreign_timeframe_rows"] for v in out.values()),
        "cursor_values": cursors,
    }


def command_bus_health() -> dict[str, Any]:
    bus = CommandBus(CommandBusPaths.production())
    frame = bus.frame()
    duplicates = 0
    per_tf: dict[str, int] = {}
    if len(frame):
        duplicates = int(len(frame) - frame["command_id"].astype(str).nunique())
        per_tf = {
            tf: int((frame["timeframe"].astype(str) == tf).sum()) for tf in SUPPORTED_TIMEFRAMES
        }
    return {
        "path": str(CommandBusPaths.production().memory.relative_to(ROOT)),
        "rows": int(len(frame)),
        "duplicate_command_ids": duplicates,
        "commands_per_timeframe": per_tf,
        "d1_commands": 0 if not len(frame) else int((frame["timeframe"].astype(str) == "D1").sum()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S4.1 production activation")
    parser.add_argument(APPROVAL_FLAG, dest="approved", action="store_true", required=True)
    parser.add_argument("--paper-only", action="store_true", required=True)
    parser.add_argument("--no-real-execution", action="store_true", required=True)
    parser.add_argument("--dry-run", action="store_true", help="evaluate gates only, change nothing")
    args = parser.parse_args(argv)

    stamp = activation.stamp_now()
    print()
    print("S4.1 PRODUCTION ACTIVATION")
    print()

    runtime_before = runtime_snapshot()
    preserved_before = preserved_process_pids()
    gates = activation.evaluate_gates()
    print(f"runtime_before: {runtime_before['overall_health']}")
    print(f"legacy_ledger_mode: {gates['legacy_ledger'].get('mode')}")
    print(f"gates_allowed: {gates['allowed']} blocked={gates['blocked_reasons']}")

    if not gates["allowed"]:
        status = (
            activation.BLOCKED_BY_LEGACY_OPEN
            if gates["checks"]["legacy_open_position"]
            else "S4_MANAGER_TRADER_ARCHITECTURE_BLOCKED"
        )
        payload = {
            "generated_at": activation.utc_now(),
            "status": status,
            "gates": gates,
            "runtime_before": runtime_before,
        }
        atomic_write_json(activation.RESEARCH / f"s4_1_activation_blocked_{stamp}.json", payload)
        print(f"status: {status}")
        return 2
    if args.dry_run:
        print("status: DRY_RUN_GATES_PASSED (no changes applied)")
        return 0

    backup_manifest = activation.create_backups(stamp)
    print(f"backup: {backup_manifest['manifest_path']} files={backup_manifest['file_count']}")

    legacy_stop = stop_legacy_controller()
    print(f"legacy_controller_stopped: {legacy_stop['stopped']} pids_before={legacy_stop['pids_before']}")
    if not legacy_stop["stopped"]:
        payload = {
            "generated_at": activation.utc_now(),
            "status": "S4_MANAGER_TRADER_ARCHITECTURE_BLOCKED",
            "reason": "LEGACY_CONTROLLER_STILL_RUNNING",
            "legacy_stop": legacy_stop,
        }
        atomic_write_json(activation.RESEARCH / f"s4_1_activation_blocked_{stamp}.json", payload)
        print("status: S4_MANAGER_TRADER_ARCHITECTURE_BLOCKED (legacy controller alive)")
        return 3

    legacy_migration = activation.archive_legacy_ledger(stamp, mode=gates["legacy_ledger"].get("mode"))
    print(f"legacy_ledger: {legacy_migration['legacy_ledger_state']} -> {legacy_migration['archive_dir']}")

    activation_timestamp = activation.utc_now()
    for tf in SUPPORTED_TIMEFRAMES:
        TraderBook.production(tf).ensure_dirs()
    activation.write_activation_record(
        stamp=stamp,
        activation_timestamp=activation_timestamp,
        gates=gates,
        backup_manifest=backup_manifest,
        legacy_migration=legacy_migration,
        processes={"roles": list(ROLES), "started": False},
    )
    print(f"activation_boundary: {activation_timestamp}")

    started = start_roles()
    for role, info in started.items():
        print(f"  {role}: {info.get('stdout') or info.get('error')}")
    processes = verify_processes()
    cursors = verify_independent_cursors()
    bus = command_bus_health()
    runtime_after = runtime_snapshot()
    preserved_after = preserved_process_pids()
    preserved_ok = preserved_before == preserved_after

    record = activation.write_activation_record(
        stamp=stamp,
        activation_timestamp=activation_timestamp,
        gates=gates,
        backup_manifest=backup_manifest,
        legacy_migration=legacy_migration,
        processes={
            "roles": list(ROLES),
            "started": True,
            "verification": processes,
            "cursors": cursors,
            "command_bus": bus,
            "legacy_stop": legacy_stop,
            "upstream_processes_untouched": preserved_ok,
            "upstream_pids": preserved_after,
        },
    )
    preservation = activation.preservation_snapshot(stamp)
    all_ok = (
        all(v["ok"] for v in processes["roles"].values())
        and processes["single_writer_per_book"]
        and cursors["cross_trader_rows"] == 0
        and bus["duplicate_command_ids"] == 0
        and bus["d1_commands"] == 0
        and preserved_ok
        and not activation.legacy_controller_pids()
    )
    status = (
        "S4_MANAGER_TRADER_ARCHITECTURE_ACTIVATED"
        if all_ok
        else "S4_MANAGER_TRADER_ARCHITECTURE_ACTIVATED_DEGRADED"
    )
    summary = {
        "generated_at": activation.utc_now(),
        "status": status,
        "stamp": stamp,
        "activation_timestamp": activation_timestamp,
        "gates": gates,
        "processes": processes,
        "cursors": cursors,
        "command_bus": bus,
        "legacy_stop": legacy_stop,
        "legacy_migration": legacy_migration,
        "runtime_before": runtime_before,
        "runtime_after": runtime_after,
        "upstream_processes_untouched": preserved_ok,
        "preservation_stamp": preservation["stamp"],
        "activation_record": str(activation.ACTIVATION_PATH.relative_to(ROOT)),
        "paper_only": True,
        "real_execution": False,
        "exchange_calls": 0,
    }
    atomic_write_json(activation.RESEARCH / f"s4_1_activation_summary_{stamp}.json", summary)
    print()
    print(f"processes_ok: {all(v['ok'] for v in processes['roles'].values())}")
    print(f"command_bus: rows={bus['rows']} duplicates={bus['duplicate_command_ids']} d1={bus['d1_commands']}")
    print(f"runtime_after: {runtime_after['overall_health']}")
    print(f"upstream_untouched: {preserved_ok}")
    print(f"status: {status}")
    print()
    _ = record
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
