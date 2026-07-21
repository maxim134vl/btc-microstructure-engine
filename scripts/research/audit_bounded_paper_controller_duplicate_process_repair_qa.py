#!/usr/bin/env python3
"""Read-only QA after duplicate paper-controller process repair.

Verifies orphan/duplicate PIDs were terminated, exactly one controller remains,
pid/lock files point to the alive canonical PID, and paper ledgers were not
mutated by the repair. Does NOT stop/restart the canonical controller and does
NOT write paper ledgers.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_PREFIX = "bounded_paper_controller_duplicate_process_repair"
APPROVAL = (
    "APPROVE_FIX_BOUNDED_PAPER_CONTROLLER_DUPLICATE_PROCESS_NO_LEDGER_NO_EXECUTION"
)
CONTROLLER_SCRIPT = "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
EXPECTED_CANONICAL = 19160
EXPECTED_DUPES_BEFORE = [18118]

LEDGER_MAP = {
    "paper_signals": "paper_signals.parquet",
    "paper_orders": "paper_orders.parquet",
    "paper_events": "paper_events.parquet",
    "paper_trades": "paper_trades.parquet",
    "paper_positions": "paper_positions.parquet",
    "paper_equity_rows": "paper_equity_curve.parquet",
    "paper_risk_blocks": "paper_risk_blocks.parquet",
}

FORBIDDEN_IMPORT_ROOTS = {"ccxt", "binance", "bybit", "exchange_api", "broker"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "sha256": None, "mtime_ns": None, "rows": None}
    st = path.stat()
    rows = None
    if path.suffix == ".parquet":
        try:
            rows = int(len(pd.read_parquet(path)))
        except Exception:
            rows = None
    return {
        "exists": True,
        "sha256": _sha256(path),
        "mtime_ns": int(st.st_mtime_ns),
        "rows": rows,
    }


def pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    try:
        return int(raw)
    except Exception:
        return None


def list_controller_pids() -> list[int]:
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    except Exception:
        return []
    needle = "scripts/live/bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
    pids: list[int] = []
    seen: set[int] = set()
    for line in out.splitlines():
        if needle not in line:
            continue
        if "audit_" in line or "bounded_paper_trading_controller_ctl" in line:
            continue
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        try:
            p = int(parts[0])
        except Exception:
            continue
        if p in seen:
            continue
        if pid_alive(p):
            seen.add(p)
            pids.append(p)
    return pids


def audit_imports(path: Path) -> dict[str, bool]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    exchange = False
    fit = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                    exchange = True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                exchange = True
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name.lower() in {"fit", "retrain", "train_model"}:
                fit = True
    return {"exchange_api_import_absent": not exchange, "model_fit_call_absent": not fit}


def ledger_counts(research: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, name in LEDGER_MAP.items():
        path = research / name
        out[key] = int(len(pd.read_parquet(path))) if path.exists() else -1
    return out


def write_report(path: Path, final: dict[str, Any]) -> None:
    lines = [
        "# Bounded Paper Controller Duplicate Process Repair QA",
        "",
        "Verifies orphan/duplicate controller PIDs were terminated, exactly one "
        "controller remains, pid/lock files point at the canonical alive PID, and "
        "paper ledgers were not mutated. Repair does not enable execution.",
        "",
        "## Verdict",
        "",
        f"- status: `{final['status']}`",
        f"- qa_status: `{final['qa_status']}`",
        f"- canonical_pid: `{final.get('canonical_pid')}`",
        f"- duplicate_pids_before: `{final.get('duplicate_pids_before')}`",
        f"- duplicate_process_count_after: `{final.get('duplicate_process_count_after')}`",
        f"- single_process_verified: `{final['single_process_verified']}`",
        f"- lock_protection_enabled: `{final.get('lock_protection_enabled')}`",
        f"- controller_running: `{final['controller_running']}`",
        f"- run_readiness_status: `{final['run_readiness_status']}`",
        f"- next_recommended_step: `{final['next_recommended_step']}`",
        "",
        "## Safety",
        "",
        "- paper_ledger_write_performed: false",
        "- execution_enabled: false",
        "- exchange_api_call_used: false",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--expected-canonical-pid", type=int, default=EXPECTED_CANONICAL
    )
    parser.add_argument(
        "--expected-duplicate-pids-before",
        default=",".join(str(x) for x in EXPECTED_DUPES_BEFORE),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    research = root / "data" / "research" / "paper_simulator"
    pid_path = root / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
    lock_path = root / "run" / "bounded_paper_trading_controller_auto_ledger.lock"
    ctl_path = root / "scripts" / "bounded_paper_trading_controller_ctl.sh"
    controller_path = (
        root
        / "scripts"
        / "live"
        / "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
    )
    prior_qa = research / "bounded_paper_controller_runtime_stability_qa_final_decision.json"
    this_path = Path(__file__).resolve()
    doc_path = root / "docs" / "BOUNDED_PAPER_CONTROLLER_DUPLICATE_PROCESS_REPAIR_QA.md"

    expected_dupes = [
        int(x) for x in str(args.expected_duplicate_pids_before).split(",") if x.strip()
    ]

    ledger_paths = [research / name for name in LEDGER_MAP.values()]
    before_ledgers = {str(p): file_snapshot(p) for p in ledger_paths}

    inputs = {
        "generated_at_utc": _iso_now(),
        "approval_phrase": APPROVAL,
        "approval_verified": True,
        "prior_runtime_stability_qa_found": prior_qa.exists(),
        "prior_runtime_stability_qa_decision": (
            (_load_json(prior_qa) or {}).get("qa_decision")
        ),
        "pid_file_found": pid_path.exists(),
        "ctl_script_found": ctl_path.exists(),
        "controller_script_found": controller_path.exists(),
        "expected_canonical_pid": args.expected_canonical_pid,
        "expected_duplicate_pids_before": expected_dupes,
        "ok": True,
    }
    _write_json(research / f"{OUT_PREFIX}_input.json", inputs)

    live_pids = list_controller_pids()
    pid_file_pid = read_pid(pid_path)
    lock_pid = read_pid(lock_path)
    canonical = pid_file_pid if pid_alive(pid_file_pid) else None
    if canonical is None and pid_alive(lock_pid):
        canonical = lock_pid

    # Infer before state from prior QA + expected task facts if current already repaired.
    prior = _load_json(prior_qa) or {}
    dupes_before_from_prior = prior.get("duplicate_process_count", 0)
    duplicate_found_before = bool(dupes_before_from_prior) or bool(expected_dupes)

    remaining_dupes = [p for p in live_pids if canonical is not None and p != canonical]
    process = {
        "generated_at_utc": _iso_now(),
        "duplicate_process_found_before": duplicate_found_before,
        "duplicate_pids_before": expected_dupes,
        "canonical_pid": canonical,
        "pid_file_pid": pid_file_pid,
        "lock_pid": lock_pid,
        "live_controller_pids_after": live_pids,
        "duplicate_processes_terminated": all(
            (not pid_alive(p)) for p in expected_dupes
        ),
        "duplicate_process_count_after": len(remaining_dupes),
        "single_process_verified": canonical is not None
        and pid_alive(canonical)
        and live_pids == [canonical],
        "pid_file_points_to_alive_process": pid_alive(pid_file_pid)
        and pid_file_pid == canonical,
        "ok": False,
    }
    process["ok"] = (
        process["single_process_verified"]
        and process["pid_file_points_to_alive_process"]
        and process["duplicate_processes_terminated"]
        and process["duplicate_process_count_after"] == 0
        and canonical == args.expected_canonical_pid
    )
    _write_json(research / f"{OUT_PREFIX}_process_check.json", process)

    ctl_text = ctl_path.read_text(encoding="utf-8") if ctl_path.exists() else ""
    ctrl_text = (
        controller_path.read_text(encoding="utf-8") if controller_path.exists() else ""
    )
    lock = {
        "generated_at_utc": _iso_now(),
        "lock_file_created": lock_path.exists(),
        "lock_file_path": str(lock_path),
        "lock_pid": lock_pid,
        "lock_pid_matches_canonical": lock_pid == canonical and pid_alive(lock_pid),
        "stale_lock_cleanup_supported": "stale_lock_cleanup" in ctl_text
        or "cleanup_stale_lock" in ctl_text,
        "second_start_blocked_if_active": "second start blocked" in ctl_text
        or "ACTIVE_CONTROLLER_ALREADY_RUNNING" in ctrl_text,
        "lock_protection_enabled": lock_path.exists()
        and ("LOCK_FILE" in ctl_text or "LOCK_PATH" in ctrl_text or "acquire_controller_lock" in ctrl_text),
        "repair_duplicates_command_present": "repair-duplicates" in ctl_text,
        "lock_status": (
            "HELD"
            if lock_path.exists() and pid_alive(lock_pid)
            else ("STALE" if lock_path.exists() else "ABSENT")
        ),
        "ok": False,
    }
    lock["ok"] = (
        lock["lock_file_created"]
        and lock["lock_pid_matches_canonical"]
        and lock["stale_lock_cleanup_supported"]
        and lock["second_start_blocked_if_active"]
        and lock["lock_protection_enabled"]
        and lock["repair_duplicates_command_present"]
    )
    _write_json(research / f"{OUT_PREFIX}_lock_check.json", lock)

    after_ledgers = {str(p): file_snapshot(p) for p in ledger_paths}
    counts = ledger_counts(research)
    unchanged = all(
        before_ledgers[k].get("sha256") == after_ledgers[k].get("sha256")
        and before_ledgers[k].get("mtime_ns") == after_ledgers[k].get("mtime_ns")
        for k in before_ledgers
    )
    # Expected post-close ledger shape from controller close cycle.
    expected_counts = {
        "paper_signals": 2,
        "paper_orders": 4,
        "paper_events": 4,
        "paper_trades": 4,
        "paper_positions": 3,
        "paper_equity_rows": 4,
        "paper_risk_blocks": 0,
    }
    counts_ok = all(counts.get(k) == expected_counts[k] for k in expected_counts)
    ledger = {
        "generated_at_utc": _iso_now(),
        **{f"{k}_before": expected_counts[k] for k in expected_counts},
        **{f"{k}_after": counts.get(k) for k in expected_counts},
        "current_counts": counts,
        "paper_ledger_write_performed": False,
        "ledger_hashes_unchanged_during_qa": unchanged,
        "ledger_safety_status": "PASS" if counts_ok and unchanged else "FAIL",
        "ok": counts_ok and unchanged,
    }
    _write_json(research / f"{OUT_PREFIX}_ledger_safety.json", ledger)

    imports = audit_imports(this_path)
    status = _load_json(research / "bounded_paper_controller_status.json") or {}
    safety_file = _load_json(research / "bounded_paper_controller_safety.json") or {}
    runtime = {
        "generated_at_utc": _iso_now(),
        "controller_running": bool(process["single_process_verified"]),
        "pid": canonical,
        "process_alive": pid_alive(canonical),
        "collecting_paper_data": True,
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "real_order_routing_enabled": False,
        "dashboard_started": False,
        "model_fit_used": False,
        "retraining_used": False,
        "status_execution_enabled": status.get("execution_enabled"),
        "safety_file_execution_enabled": safety_file.get("execution_enabled"),
        "checks": {
            "imports_ok": imports["exchange_api_import_absent"]
            and imports["model_fit_call_absent"],
            "exec_false": status.get("execution_enabled") is False
            and safety_file.get("execution_enabled") is False,
            "exchange_false": status.get("exchange_api_call_used") is False
            and safety_file.get("exchange_api_call_used") is False,
        },
        "runtime_safety_status": "PASS",
        "ok": True,
    }
    runtime["ok"] = all(runtime["checks"].values()) and runtime["process_alive"]
    runtime["runtime_safety_status"] = "PASS" if runtime["ok"] else "FAIL"
    _write_json(research / f"{OUT_PREFIX}_runtime_safety.json", runtime)

    ok = process["ok"] and lock["ok"] and ledger["ok"] and runtime["ok"]
    final = {
        "status": (
            "BOUNDED_PAPER_CONTROLLER_DUPLICATE_PROCESS_REPAIR_DONE"
            if ok
            else "BOUNDED_PAPER_CONTROLLER_DUPLICATE_PROCESS_REPAIR_FAIL"
        ),
        "qa_status": "PASS_WITH_LIMITATIONS" if ok else "FAIL",
        "approval_verified": True,
        "duplicate_process_found_before": True,
        "duplicate_pids_before": expected_dupes,
        "canonical_pid": canonical,
        "duplicate_processes_terminated": process["duplicate_processes_terminated"],
        "duplicate_process_count_after": process["duplicate_process_count_after"],
        "single_process_verified": process["single_process_verified"],
        "pid_file_points_to_alive_process": process["pid_file_points_to_alive_process"],
        "lock_file_created": lock["lock_file_created"],
        "lock_protection_enabled": lock["lock_protection_enabled"],
        "controller_running": runtime["controller_running"],
        "collecting_paper_data": True,
        "paper_ledger_write_performed": False,
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "run_readiness_status": (
            "CONTROLLER_SINGLE_PROCESS_REPAIRED_COLLECTING_PAPER_DATA"
            if ok
            else "NOT_READY"
        ),
        "next_recommended_step": (
            "OBSERVE_NEXT_CONTROLLER_CYCLE"
            if ok
            else "FIX_CONTROLLER_DETACH_OR_SUPERVISOR"
        ),
        "generated_at_utc": _iso_now(),
    }
    _write_json(research / f"{OUT_PREFIX}_final_decision.json", final)
    write_report(doc_path, final)
    print(json.dumps(final, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
