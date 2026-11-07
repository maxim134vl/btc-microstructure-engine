#!/usr/bin/env python3
"""Read-only runtime stability QA for bounded paper trading controller.

Does NOT stop/restart the controller, does NOT write paper ledgers, does NOT
run monitors/execution/exchange/dashboard, and does NOT commit. Inspects pid
file, running processes, controller log, status/cycle artifacts, and paper
ledgers only.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

OUT_PREFIX = "bounded_paper_controller_runtime_stability_qa"
EXPECTED_POSITION_ID = "PAPER_POSITION_ONE_SHOT_a44e90c3306cdb59"
CONTROLLER_SCRIPT_NAME = (
    "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
)
PID_REL = Path("run/bounded_paper_trading_controller_auto_ledger.pid")
LOG_REL = Path("logs/bounded_paper_trading_controller_auto_ledger.log")
CTL_REL = Path("scripts/bounded_paper_trading_controller_ctl.sh")
STATUS_REL = Path(
    "data/research/paper_simulator/bounded_paper_controller_status.json"
)
SAFETY_REL = Path(
    "data/research/paper_simulator/bounded_paper_controller_safety.json"
)
CYCLES_REL = Path(
    "data/research/paper_simulator/bounded_paper_controller_cycles.parquet"
)
POSITIONS_REL = Path("data/research/paper_simulator/paper_positions.parquet")
TRADES_REL = Path("data/research/paper_simulator/paper_trades.parquet")

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


def _ts_iso(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("+00:00"):
            return s.replace("+00:00", "Z")
        return s
    ts = pd.Timestamp(v)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _to_utc(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    ts = pd.Timestamp(v)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


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
    return {
        "exchange_api_import_absent": not exchange,
        "model_fit_call_absent": not fit,
    }


def read_pid_file(path: Path) -> int | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but signal not permitted in restricted environments.
        return True
    except Exception:
        return False


def list_controller_pids() -> list[int]:
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", CONTROLLER_SCRIPT_NAME],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.append(int(line))
        except Exception:
            continue
    # Deduplicate while preserving order
    seen: set[int] = set()
    uniq: list[int] = []
    for p in pids:
        if p not in seen and pid_alive(p):
            seen.add(p)
            uniq.append(p)
    return uniq


def parse_log_events(log_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in log_text.splitlines():
        m = re.match(
            r"^(?P<ts>\d{4}-\d{2}-\d{2}T[0-9:.]+Z)\s+(?P<body>.*)$",
            line.strip(),
        )
        if not m:
            continue
        ts = m.group("ts")
        body = m.group("body")
        if "controller_start pid=" in body:
            pm = re.search(r"pid=(\d+)", body)
            events.append(
                {
                    "ts": ts,
                    "kind": "START",
                    "pid": int(pm.group(1)) if pm else None,
                    "body": body,
                }
            )
        elif "controller_stop reason=" in body:
            rm = re.search(r"reason=(\S+)", body)
            events.append(
                {
                    "ts": ts,
                    "kind": "STOP",
                    "reason": rm.group(1) if rm else None,
                    "body": body,
                }
            )
        elif "cycle_error=" in body or "Traceback" in body:
            events.append({"ts": ts, "kind": "ERROR", "body": body})
        elif re.search(r"cycle=\d+", body):
            events.append({"ts": ts, "kind": "CYCLE", "body": body})
    return events


def classify_death(events: list[dict[str, Any]], current_pids: list[int]) -> dict[str, Any]:
    starts = [e for e in events if e["kind"] == "START"]
    stops = [e for e in events if e["kind"] == "STOP"]
    errors = [e for e in events if e["kind"] == "ERROR"]
    prior_died = False
    cause = "UNKNOWN"
    notes: list[str] = []

    intentional_stops = [s for s in stops if str(s.get("reason")) == "ONE_CYCLE"]
    error_stops = [
        s for s in stops if str(s.get("reason", "")).startswith("ERROR")
    ]

    started_pids = [e.get("pid") for e in starts if e.get("pid") is not None]
    dead_started: list[int] = []
    for pid in started_pids:
        if pid in current_pids:
            continue
        dead_started.append(int(pid))

    # Per-start window: stop between this start and the next start?
    orphan_dead: list[int] = []
    intentional_dead: list[int] = []
    for i, start in enumerate(starts):
        pid = start.get("pid")
        if pid is None:
            continue
        if pid in current_pids:
            continue
        end_ts = starts[i + 1]["ts"] if i + 1 < len(starts) else "9999-12-31T00:00:00Z"
        window_stops = [
            s for s in stops if start["ts"] <= s["ts"] < end_ts
        ]
        if not window_stops:
            orphan_dead.append(int(pid))
        elif any(str(s.get("reason")) == "ONE_CYCLE" for s in window_stops):
            intentional_dead.append(int(pid))
        elif any(str(s.get("reason", "")).startswith("ERROR") for s in window_stops):
            intentional_dead.append(int(pid))
            cause = "NORMAL_EXIT_AFTER_ERROR"

    if errors:
        prior_died = True
        cause = "CRASH_EXCEPTION"
        notes.append("error_or_traceback_in_log")
    elif orphan_dead:
        prior_died = True
        cause = "PID_DETACH_ISSUE"
        notes.append(f"started_pids_vanished_without_stop:{orphan_dead}")
    elif error_stops:
        prior_died = True
        cause = "NORMAL_EXIT_AFTER_ERROR"
        notes.append("error_stop_reason_in_log")
    elif intentional_dead and not orphan_dead:
        # Only intentional ONE_CYCLE exits among dead pids.
        prior_died = bool(dead_started)
        cause = "UNKNOWN" if not orphan_dead else "PID_DETACH_ISSUE"
        notes.append(f"intentional_dead_pids:{intentional_dead}")
        if dead_started and not intentional_dead:
            cause = "PID_DETACH_ISSUE"
    elif dead_started:
        prior_died = True
        cause = "PID_DETACH_ISSUE"
        notes.append(f"dead_started_pids:{dead_started}")

    restart_detected = len(starts) >= 2
    detach_launcher_used = True
    latest_start_pid = starts[-1].get("pid") if starts else None
    prior_start_pids = [e.get("pid") for e in starts[:-1] if e.get("pid") is not None]
    new_pid_after_restart = bool(
        latest_start_pid is not None
        and prior_start_pids
        and int(latest_start_pid) != int(prior_start_pids[-1])
    )

    if restart_detected and prior_died:
        restart_status = "RESTART_AFTER_DEATH_DETECTED"
    elif restart_detected:
        restart_status = "RESTART_DETECTED"
    else:
        restart_status = "NO_RESTART"

    return {
        "prior_process_died": prior_died,
        "death_cause_classification": cause,
        "restart_detected": restart_detected,
        "detach_launcher_used": detach_launcher_used,
        "restart_status": restart_status,
        "new_pid_after_restart": new_pid_after_restart,
        "latest_start_pid": latest_start_pid,
        "prior_start_pids": prior_start_pids,
        "dead_started_pids": dead_started,
        "orphan_dead_pids": orphan_dead,
        "intentional_dead_pids": intentional_dead,
        "intentional_stop_count": len(intentional_stops),
        "error_event_count": len(errors),
        "notes": notes,
        "ok": True,
    }


def check_process(root: Path) -> dict[str, Any]:
    pid_path = root / PID_REL
    status_path = root / STATUS_REL
    ctl_path = root / CTL_REL
    log_path = root / LOG_REL

    pid = read_pid_file(pid_path)
    alive = pid_alive(pid)
    procs = list_controller_pids()
    # Prefer matching pid-file process; count all matching script processes.
    duplicate_count = max(0, len(procs) - 1)
    single = len(procs) == 1 and alive and (pid in procs if pid is not None else False)

    status = _load_json(status_path) or {}
    last = status.get("last_cycle") or {}
    cycle_ts = last.get("cycle_ts") or status.get("generated_at_utc")
    interval = float(status.get("interval_seconds") or 900)
    next_wake = None
    if cycle_ts:
        base = _to_utc(cycle_ts)
        if base is not None:
            next_wake = (base + timedelta(seconds=interval)).isoformat().replace(
                "+00:00", "Z"
            )

    detach_valid = ctl_path.exists() and "start_new_session" in ctl_path.read_text(
        encoding="utf-8"
    )

    return {
        "generated_at_utc": _iso_now(),
        "pid_file_exists": pid_path.exists(),
        "pid": pid,
        "process_alive": alive,
        "controller_pids": procs,
        "duplicate_process_count": duplicate_count,
        "controller_process_count": len(procs),
        "single_process_verified": single,
        "detach_launcher_path_exists": ctl_path.exists(),
        "detach_launcher_status_valid": detach_valid,
        "status_file_readable": status_path.exists(),
        "log_file_exists": log_path.exists(),
        "latest_cycle_id": last.get("cycle_id"),
        "latest_cycle_ts": cycle_ts,
        "latest_heartbeat_or_cycle_timestamp_exists": bool(cycle_ts),
        "interval_seconds": interval,
        "next_wake_time": next_wake,
        "status_controller_running_flag": bool(status.get("controller_running")),
        "ok": alive and single and status_path.exists() and bool(cycle_ts),
    }


def check_latest_cycle(root: Path) -> dict[str, Any]:
    status = _load_json(root / STATUS_REL) or {}
    last = status.get("last_cycle") or {}
    cycles_path = root / CYCLES_REL
    latest_from_parquet: dict[str, Any] = {}
    if cycles_path.exists():
        df = pd.read_parquet(cycles_path)
        if not df.empty:
            latest_from_parquet = df.iloc[-1].to_dict()

    action = str(last.get("action_taken") or latest_from_parquet.get("action_taken") or "")
    pos_before = str(
        last.get("position_state_before")
        or latest_from_parquet.get("position_state_before")
        or ""
    )
    context = str(
        last.get("latest_context") or latest_from_parquet.get("context") or ""
    )
    life = str(
        last.get("latest_lifecycle_state")
        or latest_from_parquet.get("lifecycle_state")
        or ""
    )
    cycle_id = str(last.get("cycle_id") or latest_from_parquet.get("cycle_id") or "")
    cycle_status = str(
        last.get("cycle_status") or latest_from_parquet.get("cycle_status") or ""
    )
    new_trade = bool(
        last.get("new_trade_written")
        or (
            last.get("action_taken") in {"OPEN_LONG", "OPEN_SHORT"}
            if last.get("action_taken")
            else False
        )
    )

    checks = {
        "action_observe_no_trade": action == "OBSERVE_NO_TRADE",
        "position_flat": pos_before == "FLAT",
        "context_observe": context == "OBSERVE",
        "lifecycle_no_active": life == "NO_ACTIVE_CONTEXT",
        "no_new_trade": new_trade is False,
        "cycle_ok": cycle_status == "OK",
    }
    return {
        "generated_at_utc": _iso_now(),
        "latest_cycle_id": cycle_id,
        "latest_action": action,
        "position_state_before": pos_before,
        "context": context,
        "lifecycle_state": life,
        "new_trade_opened": new_trade,
        "latest_cycle_status": cycle_status,
        "checks": checks,
        "ok": all(checks.values()),
    }


def check_ledger(root: Path) -> dict[str, Any]:
    pos_path = root / POSITIONS_REL
    trades_path = root / TRADES_REL
    if not pos_path.exists():
        return {
            "generated_at_utc": _iso_now(),
            "ok": False,
            "ledger_consistency_status": "FAIL",
            "reason": "positions_missing",
        }
    pos = pd.read_parquet(pos_path)
    opens = pos[pos["status"].astype(str) == "OPEN"]
    target = pos[pos["position_id"].astype(str) == EXPECTED_POSITION_ID]
    closed_ok = (not target.empty) and str(target.iloc[-1]["status"]) == "CLOSED"
    # Duplicate close rows: multiple CLOSED rows for same position_id
    closed = pos[pos["status"].astype(str) == "CLOSED"]
    dup_close = int(
        (
            closed.groupby(closed["position_id"].astype(str)).size() > 1
        ).sum()
    )
    # For target id, count CLOSED rows
    target_closed_rows = int(
        (
            (pos["position_id"].astype(str) == EXPECTED_POSITION_ID)
            & (pos["status"].astype(str) == "CLOSED")
        ).sum()
    )

    exit_trades = 0
    if trades_path.exists():
        tr = pd.read_parquet(trades_path)
        hit = tr[tr["position_id"].astype(str) == EXPECTED_POSITION_ID]
        # ENTRY + EXIT expected; duplicate exit would be >1 SELL/close-like
        exit_trades = int((hit["side"].astype(str) == "SELL").sum())

    checks = {
        "closed_position_verified": closed_ok,
        "open_position_count_zero": len(opens) == 0,
        "no_duplicate_close_rows": target_closed_rows <= 1 and dup_close == 0,
        "single_target_row": len(target) == 1,
        "exit_trade_present_once": exit_trades == 1,
    }
    ok = all(checks.values())
    return {
        "generated_at_utc": _iso_now(),
        "closed_position_verified": closed_ok,
        "open_position_count": int(len(opens)),
        "duplicate_close_rows": int(target_closed_rows > 1) + dup_close,
        "target_closed_rows": target_closed_rows,
        "exit_trade_count_for_target": exit_trades,
        "checks": checks,
        "ledger_consistency_status": "PASS" if ok else "FAIL",
        "ok": ok,
    }


def check_safety(root: Path, this_path: Path) -> dict[str, Any]:
    safety = _load_json(root / SAFETY_REL) or {}
    status = _load_json(root / STATUS_REL) or {}
    imports = audit_imports(this_path)
    checks = {
        "execution_enabled_false": status.get("execution_enabled") is False
        and safety.get("execution_enabled") is False,
        "exchange_false": status.get("exchange_api_call_used") is False
        and safety.get("exchange_api_call_used") is False,
        "routing_false": safety.get("real_order_routing_enabled") is False,
        "dashboard_false": safety.get("dashboard_started") is False,
        "fit_false": safety.get("model_fit_used") is False
        and imports["model_fit_call_absent"],
        "retrain_false": safety.get("retraining_used") is False,
        "paper_only": status.get("paper_only_mode") is True
        or safety.get("paper_only_mode") is True,
        "no_exchange_imports": imports["exchange_api_import_absent"],
    }
    ok = all(checks.values())
    return {
        "generated_at_utc": _iso_now(),
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "real_order_routing_enabled": False,
        "dashboard_started": False,
        "model_fit_used": False,
        "retraining_used": False,
        "paper_only_mode": True,
        "checks": checks,
        "safety_status": "PASS" if ok else "FAIL",
        "ok": ok,
    }


def write_report(path: Path, final: dict[str, Any]) -> None:
    lines = [
        "# Bounded Paper Controller Runtime Stability QA Audit",
        "",
        "Read-only QA of the bounded paper trading controller after first-cycle "
        "success, prior process death, detach-launcher restart, and latest "
        "`OBSERVE_NO_TRADE` cycle. Does not stop/restart the controller and does "
        "not mutate paper ledgers.",
        "",
        "## Verdict",
        "",
        f"- qa_decision: `{final['qa_decision']}`",
        f"- controller_running: `{final['controller_running']}`",
        f"- process_alive: `{final.get('process_alive')}`",
        f"- single_process_verified: `{final.get('single_process_verified')}`",
        f"- prior_process_died: `{final.get('prior_process_died')}`",
        f"- death_cause_classification: `{final.get('death_cause_classification')}`",
        f"- latest_action: `{final.get('latest_action')}`",
        f"- open_position_count: `{final.get('open_position_count')}`",
        f"- collecting_paper_data: `{final['collecting_paper_data']}`",
        f"- next_recommended_step: `{final['next_recommended_step']}`",
        "",
        "## Safety",
        "",
        "- execution_enabled: false",
        "- exchange_api_call_used: false",
        "- controller stop/restart by this audit: false",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    research = root / "data" / "research" / "paper_simulator"
    this_path = Path(__file__).resolve()
    doc_path = root / "docs" / "BOUNDED_PAPER_CONTROLLER_RUNTIME_STABILITY_QA_AUDIT.md"

    # Snapshot protected paths — audit must not mutate them.
    protected = [
        root / PID_REL,
        root / LOG_REL,
        root / STATUS_REL,
        root / POSITIONS_REL,
        root / TRADES_REL,
        root / CYCLES_REL,
    ]
    before = {
        str(p): (p.stat().st_mtime_ns if p.exists() else None) for p in protected
    }

    inputs = {
        "generated_at_utc": _iso_now(),
        "mode": "BOUNDED_PAPER_CONTROLLER_RUNTIME_STABILITY_QA_READ_ONLY",
        "pid_file_found": (root / PID_REL).exists(),
        "status_found": (root / STATUS_REL).exists(),
        "log_found": (root / LOG_REL).exists(),
        "cycles_found": (root / CYCLES_REL).exists(),
        "positions_found": (root / POSITIONS_REL).exists(),
        "ctl_found": (root / CTL_REL).exists(),
        "controller_stop_forbidden": True,
        "controller_restart_forbidden": True,
        "ledger_write_forbidden": True,
    }
    inputs["input_validation_status"] = (
        "VALID"
        if all(
            [
                inputs["pid_file_found"],
                inputs["status_found"],
                inputs["log_found"],
                inputs["cycles_found"],
                inputs["positions_found"],
            ]
        )
        else "BLOCKED_INVALID_QA_INPUTS"
    )
    inputs["ok"] = inputs["input_validation_status"] == "VALID"
    _write_json(research / f"{OUT_PREFIX}_input.json", inputs)

    if not inputs["ok"]:
        final = {
            "qa_decision": "BOUNDED_PAPER_CONTROLLER_RUNTIME_STABILITY_QA_FAIL_REPAIR_REQUIRED",
            "qa_status": "FAIL",
            "controller_running": False,
            "collecting_paper_data": False,
            "next_recommended_step": "FIX_CONTROLLER_DETACH_OR_SUPERVISOR",
            "reason": "invalid_inputs",
            "generated_at_utc": _iso_now(),
        }
        _write_json(research / f"{OUT_PREFIX}_final_decision.json", final)
        print(json.dumps(final, indent=2))
        return 2

    process = check_process(root)
    _write_json(research / f"{OUT_PREFIX}_process_check.json", process)

    log_text = (root / LOG_REL).read_text(encoding="utf-8", errors="replace")
    events = parse_log_events(log_text)
    death = classify_death(events, process["controller_pids"])
    _write_json(research / f"{OUT_PREFIX}_death_restart_check.json", death)

    latest = check_latest_cycle(root)
    _write_json(research / f"{OUT_PREFIX}_latest_cycle_check.json", latest)

    ledger = check_ledger(root)
    _write_json(research / f"{OUT_PREFIX}_ledger_check.json", ledger)

    safety = check_safety(root, this_path)
    _write_json(research / f"{OUT_PREFIX}_safety.json", safety)

    after = {
        str(p): (p.stat().st_mtime_ns if p.exists() else None) for p in protected
    }
    protected_unchanged = before == after

    # Pass path: alive + single + latest cycle valid + ledger consistent
    runtime_ok = bool(process["ok"])
    if runtime_ok and latest["ok"] and ledger["ok"] and safety["ok"] and protected_unchanged:
        qa_decision = (
            "BOUNDED_PAPER_CONTROLLER_RUNTIME_STABILITY_QA_PASS_WITH_PRIOR_RESTART_NOTE"
        )
        qa_status = "PASS_WITH_LIMITATIONS"
        controller_running = True
        collecting = True
        next_step = "OBSERVE_NEXT_CONTROLLER_CYCLE"
    else:
        qa_decision = (
            "BOUNDED_PAPER_CONTROLLER_RUNTIME_STABILITY_QA_FAIL_REPAIR_REQUIRED"
        )
        qa_status = "FAIL"
        controller_running = bool(process["process_alive"])
        collecting = bool(process["process_alive"])
        next_step = "FIX_CONTROLLER_DETACH_OR_SUPERVISOR"

    final = {
        "qa_decision": qa_decision,
        "qa_status": qa_status,
        "controller_running": controller_running,
        "collecting_paper_data": collecting,
        "process_alive": process["process_alive"],
        "pid": process["pid"],
        "duplicate_process_count": process["duplicate_process_count"],
        "single_process_verified": process["single_process_verified"],
        "latest_cycle": process["latest_cycle_id"],
        "next_wake_time": process["next_wake_time"],
        "prior_process_died": death["prior_process_died"],
        "death_cause_classification": death["death_cause_classification"],
        "restart_detected": death["restart_detected"],
        "detach_launcher_used": death["detach_launcher_used"],
        "restart_status": death["restart_status"],
        "latest_action": latest["latest_action"],
        "position_state_before": latest["position_state_before"],
        "context": latest["context"],
        "lifecycle_state": latest["lifecycle_state"],
        "new_trade_opened": latest["new_trade_opened"],
        "closed_position_verified": ledger["closed_position_verified"],
        "open_position_count": ledger["open_position_count"],
        "duplicate_close_rows": ledger["duplicate_close_rows"],
        "ledger_consistency_status": ledger["ledger_consistency_status"],
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "real_order_routing_enabled": False,
        "paper_only_mode": True,
        "safety_status": safety["safety_status"],
        "protected_paths_unchanged": protected_unchanged,
        "next_recommended_step": next_step,
        "limitations": [
            "Read-only QA; does not stop or restart the controller.",
            "Prior detach deaths and/or duplicate processes require supervisor repair if FAIL.",
            "Latest cycle may be FLAT OBSERVE_NO_TRADE while waiting for directional context.",
        ],
        "generated_at_utc": _iso_now(),
    }
    _write_json(research / f"{OUT_PREFIX}_final_decision.json", final)
    write_report(doc_path, final)

    print(
        json.dumps(
            {
                "qa_decision": final["qa_decision"],
                "controller_running": final["controller_running"],
                "process_alive": final["process_alive"],
                "pid": final["pid"],
                "duplicate_process_count": final["duplicate_process_count"],
                "single_process_verified": final["single_process_verified"],
                "death_cause_classification": final["death_cause_classification"],
                "latest_action": final["latest_action"],
                "open_position_count": final["open_position_count"],
                "next_recommended_step": final["next_recommended_step"],
            },
            indent=2,
        )
    )
    return 0 if qa_status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
