#!/usr/bin/env python3
"""Collector process watchdog — start, monitor, restart ingress layer.

Patch 2A restart contract:
- canonical interpreter = <repo>/venv/bin/python (not bare Cellar / sys.executable)
- zombie children are classified dead (kill(0) alone is insufficient)
- bounded restart backoff with RESTART_STORM_BLOCKED
- preflight: interpreter / websocket / entrypoint / cwd before start
- wait + reap between stop and start to avoid dual writers
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from collector_health_audit import build_collector_audit, export_collector_health_audit
from collector_heartbeat import write_heartbeat
from collector_registry import COLLECTORS, COLLECTOR_CRITICAL_SECONDS, COLLECTOR_STALE_SECONDS

PID_FILE = os.path.join("data", "live", "collector_pids.json")
RESTART_STATE_FILE = os.path.join("data", "live", "collector_restart_state.json")
CHECK_INTERVAL_S = 30
STOP_WAIT_S = 8.0
RESTART_MIN_DELAY_S = 2.0
RESTART_MAX_DELAY_S = 60.0
RESTART_WINDOW_S = 600.0
RESTART_WINDOW_MAX_ATTEMPTS = 5
PS_BIN = "/bin/ps"


def _repo_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_canonical_python(root: str | None = None) -> str:
    """Return the only allowed collector interpreter (repo venv path string)."""
    root = root or _repo_root()
    override = os.environ.get("BTC_ML_COLLECTOR_PYTHON", "").strip()
    candidates = []
    if override:
        candidates.append(override)
    candidates.append(os.path.join(root, "venv", "bin", "python"))
    candidates.append(os.path.join(root, "venv", "bin", "python3"))

    for path in candidates:
        if not path:
            continue
        if _is_forbidden_interpreter(path, root):
            continue
        if os.path.exists(path) and os.access(path, os.X_OK):
            # Keep the venv path string (do not resolve symlink to Cellar).
            return path
    raise RuntimeError(
        "canonical collector interpreter missing: expected "
        f"{os.path.join(root, 'venv', 'bin', 'python')}"
    )


def _is_forbidden_interpreter(path: str, root: str) -> bool:
    """Reject bare Cellar / system interpreters when a repo venv exists.

    The venv entrypoint may *resolve* to a Cellar binary on macOS; that is
    allowed only when the invocation path itself is under `<root>/venv/`.
    """
    venv_python = os.path.join(root, "venv", "bin", "python")
    venv_python3 = os.path.join(root, "venv", "bin", "python3")
    if not (os.path.exists(venv_python) or os.path.exists(venv_python3)):
        return False

    normalized = os.path.abspath(path).replace("\\", "/")
    root_norm = os.path.abspath(root).replace("\\", "/")
    if normalized.startswith(root_norm + "/venv/"):
        return False

    forbidden_markers = (
        "/Cellar/python",
        "/Frameworks/Python.framework/",
        "/opt/homebrew/opt/python",
        "/usr/bin/python",
        "/bin/python",
        "/usr/local/bin/python",
    )
    if any(marker in normalized for marker in forbidden_markers):
        return True
    base = os.path.basename(normalized)
    if base in {"python", "python3", "python3.11"} and "/venv/" not in normalized:
        return True
    return False


def preflight_collector_launch(
    *,
    python: str,
    root: str,
    script: str,
    require_websocket: bool = True,
) -> dict[str, Any]:
    """Validate interpreter/deps/entrypoint before spawning a collector."""
    errors: list[str] = []
    if _is_forbidden_interpreter(python, root):
        errors.append(f"forbidden interpreter (bare Cellar/system): {python}")
    if not os.path.isfile(python) and not os.path.exists(python):
        errors.append(f"interpreter missing: {python}")
    elif not os.access(python, os.X_OK):
        errors.append(f"interpreter not executable: {python}")
    if not os.path.isdir(root):
        errors.append(f"cwd missing: {root}")
    if not os.path.isfile(script):
        errors.append(f"entrypoint missing: {script}")
    if require_websocket and not errors:
        try:
            proc = subprocess.run(
                [python, "-c", "import websocket"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc.returncode != 0:
                errors.append(
                    "import websocket failed under interpreter "
                    f"{python}: {(proc.stderr or proc.stdout or '').strip()}"
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"websocket preflight error: {exc}")
    return {"ok": not errors, "errors": errors, "python": python, "script": script, "root": root}


def _load_pids() -> dict[str, int]:
    if not os.path.exists(PID_FILE):
        return {}
    try:
        with open(PID_FILE, encoding="utf-8") as handle:
            return {k: int(v) for k, v in json.load(handle).items()}
    except Exception:
        return {}


def _save_pids(pids: dict[str, int]) -> None:
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    temp = PID_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(pids, handle, indent=2)
    os.replace(temp, PID_FILE)


def _load_restart_state() -> dict[str, Any]:
    if not os.path.exists(RESTART_STATE_FILE):
        return {"collectors": {}}
    try:
        with open(RESTART_STATE_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {"collectors": {}}
        data.setdefault("collectors", {})
        return data
    except Exception:
        return {"collectors": {}}


def _save_restart_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(RESTART_STATE_FILE), exist_ok=True)
    temp = RESTART_STATE_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
    os.replace(temp, RESTART_STATE_FILE)


def _pid_exists(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _ps_stat_command(pid: int) -> tuple[str | None, str | None]:
    try:
        out = subprocess.check_output(
            [PS_BIN, "-p", str(pid), "-o", "stat=", "-o", "command="],
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None, None
    if not out:
        return None, None
    # First token is STAT; remainder is COMMAND (may be "<defunct>").
    parts = out.split(None, 1)
    stat = parts[0] if parts else None
    cmd = parts[1] if len(parts) > 1 else ""
    return stat, cmd


def classify_process_state(
    pid: int | None,
    *,
    expected_script: str | None = None,
    expected_ppid: int | None = None,
) -> str:
    """Classify PID: MISSING / ZOMBIE / STOPPED / RUNNING / WRONG_COMMAND / WRONG_PARENT."""
    if pid is None:
        return "MISSING"
    if not _pid_exists(pid):
        return "MISSING"
    stat, cmd = _ps_stat_command(pid)
    if stat is None:
        # kill(0) true but ps gone → treat as missing/racy
        return "MISSING"
    if "Z" in stat:
        return "ZOMBIE"
    if stat.startswith("T"):
        return "STOPPED"
    if expected_script:
        script_name = os.path.basename(expected_script)
        cmd_l = (cmd or "").lower()
        if script_name.lower() not in cmd_l and "<defunct>" not in cmd_l:
            return "WRONG_COMMAND"
    if expected_ppid is not None:
        try:
            out = subprocess.check_output(
                [PS_BIN, "-p", str(pid), "-o", "ppid="], text=True
            ).strip()
            if out and int(out) != expected_ppid:
                return "WRONG_PARENT"
        except Exception:
            pass
    return "RUNNING"


def process_is_live_feed(pid: int | None, *, expected_script: str) -> bool:
    state = classify_process_state(pid, expected_script=expected_script)
    return state == "RUNNING"


def reap_child_processes() -> list[int]:
    """Reap any exited children (clears zombies owned by this watchdog)."""
    reaped: list[int] = []
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if pid == 0:
            break
        reaped.append(int(pid))
    return reaped


def stop_pid(pid: int, *, timeout_s: float = STOP_WAIT_S) -> str:
    """SIGTERM → wait → SIGKILL → reap. Returns final state."""
    if not _pid_exists(pid) and classify_process_state(pid) == "MISSING":
        reap_child_processes()
        return "MISSING"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        reap_child_processes()
        state = classify_process_state(pid)
        if state in {"MISSING"}:
            return "MISSING"
        if state == "ZOMBIE":
            # Only parent can reap; keep waiting for waitpid.
            time.sleep(0.1)
            continue
        time.sleep(0.1)
    state = classify_process_state(pid)
    if state in {"RUNNING", "STOPPED"}:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        time.sleep(0.2)
    reap_child_processes()
    return classify_process_state(pid)


def list_matching_pids(script_basename: str) -> list[int]:
    try:
        out = subprocess.check_output([PS_BIN, "-ax", "-o", "pid=,stat=,command="], text=True)
    except Exception:
        return []
    found: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if script_basename not in line:
            continue
        if "collector_watchdog" in line or "pytest" in line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid_s, stat, _cmd = parts[0], parts[1], parts[2]
        if "Z" in stat:
            continue
        try:
            found.append(int(pid_s))
        except ValueError:
            continue
    return found


def restart_allowed(name: str, state: dict[str, Any], now: float | None = None) -> tuple[bool, str, float]:
    """Bounded backoff. Returns (allowed, reason, delay_s)."""
    now = time.time() if now is None else now
    collectors = state.setdefault("collectors", {})
    entry = collectors.setdefault(
        name,
        {"attempts": [], "blocked": False, "block_reason": None, "last_delay_s": 0.0},
    )
    if entry.get("blocked"):
        return False, str(entry.get("block_reason") or "RESTART_STORM_BLOCKED"), float("inf")

    attempts = [float(x) for x in entry.get("attempts", []) if now - float(x) <= RESTART_WINDOW_S]
    entry["attempts"] = attempts
    if len(attempts) >= RESTART_WINDOW_MAX_ATTEMPTS:
        entry["blocked"] = True
        entry["block_reason"] = "RESTART_STORM_BLOCKED"
        collectors[name] = entry
        return False, "RESTART_STORM_BLOCKED", float("inf")

    delay = min(RESTART_MAX_DELAY_S, RESTART_MIN_DELAY_S * (2 ** max(0, len(attempts) - 1)))
    last = attempts[-1] if attempts else None
    if last is not None and (now - last) < delay:
        return False, "RESTART_BACKOFF", delay - (now - last)
    return True, "OK", delay


def record_restart_attempt(name: str, state: dict[str, Any], now: float | None = None) -> None:
    now = time.time() if now is None else now
    collectors = state.setdefault("collectors", {})
    entry = collectors.setdefault(
        name,
        {"attempts": [], "blocked": False, "block_reason": None, "last_delay_s": 0.0},
    )
    attempts = [float(x) for x in entry.get("attempts", []) if now - float(x) <= RESTART_WINDOW_S]
    attempts.append(now)
    entry["attempts"] = attempts
    entry["last_delay_s"] = min(
        RESTART_MAX_DELAY_S, RESTART_MIN_DELAY_S * (2 ** max(0, len(attempts) - 1))
    )
    collectors[name] = entry


def start_collector(name: str, python: str, root: str) -> int | None:
    spec = next((c for c in COLLECTORS if c["name"] == name), None)
    if spec is None:
        return None

    script = os.path.join(root, spec["script"])
    require_ws = bool(spec.get("kind") == "websocket" or name == "binance_live_feed")
    pre = preflight_collector_launch(
        python=python, root=root, script=script, require_websocket=require_ws
    )
    if not pre["ok"]:
        print(f"  [BLOCK] {name}: preflight failed: {pre['errors']}")
        write_heartbeat(
            name,
            status="ERROR",
            event="preflight_failed",
            extra={"errors": pre["errors"], "python": python},
        )
        return None

    # Prevent duplicate writers for the same entrypoint.
    existing = list_matching_pids(os.path.basename(script))
    if existing:
        print(f"  [CLEANUP] {name}: stopping duplicate pids={existing}")
        for pid in existing:
            stop_pid(pid)

    log_dir = os.path.join(root, "reports", "collector_health", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{name}.log")

    log_handle = open(log_path, "a", encoding="utf-8")
    log_handle.write(f"\n--- START {datetime.now().isoformat()} python={python} ---\n")
    log_handle.flush()

    proc = subprocess.Popen(
        [python, script],
        cwd=root,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    # Keep handle referenced on the process to avoid premature GC close races.
    proc._btc_ml_log_handle = log_handle  # type: ignore[attr-defined]
    print(f"  [START] {name} pid={proc.pid} python={python}")
    try:
        write_heartbeat(
            name,
            status="STARTING",
            event="watchdog_start",
            extra={"pid": proc.pid, "python": python},
        )
    except Exception as exc:  # noqa: BLE001 — metadata must not block feed restart
        print(f"  [WARN] {name}: heartbeat/metadata failed after start: {exc}")
    return proc.pid


def start_all(python: str, root: str, only_required: bool = False) -> dict[str, int]:
    pids: dict[str, int] = {}
    for spec in COLLECTORS:
        if only_required and not spec.get("required"):
            continue
        pid = start_collector(spec["name"], python, root)
        if pid:
            pids[spec["name"]] = pid
    _save_pids(pids)
    return pids


def _collector_needs_restart(
    *,
    name: str,
    spec: dict[str, Any],
    pid: int | None,
    audit: dict[str, Any],
    watchdog_pid: int | None = None,
) -> tuple[bool, str]:
    script = spec.get("script") or ""
    state = classify_process_state(
        pid, expected_script=script, expected_ppid=watchdog_pid
    )
    if state in {"MISSING", "ZOMBIE", "WRONG_COMMAND", "WRONG_PARENT", "STOPPED"}:
        return True, f"process_{state.lower()}"

    collector = next(c for c in audit["collectors"] if c["name"] == name)
    hb_age = collector.get("heartbeat_age_seconds")
    parquet_age = collector.get("parquet", {}).get("age_seconds")
    hb_status = str((collector.get("heartbeat") or {}).get("status") or "").upper()
    hb_event = str((collector.get("heartbeat") or {}).get("event") or "")
    ws_signal_healthy = hb_status in ("CONNECTED", "ALIVE", "STARTING") or hb_event in (
        "candle_saved",
        "kline_tick",
        "websocket_open",
        "process_start",
    )
    heartbeat_fresh = (
        hb_age is not None and hb_age <= COLLECTOR_STALE_SECONDS and ws_signal_healthy
    )
    if hb_age is not None and hb_age > COLLECTOR_CRITICAL_SECONDS:
        return True, f"heartbeat_stale_{hb_age}s"
    if (
        hb_event in ("websocket_error", "websocket_closed", "message_error")
        and parquet_age is not None
        and parquet_age > COLLECTOR_STALE_SECONDS
    ):
        return True, f"websocket_errors_stale_parquet_{parquet_age}s"
    if (
        parquet_age is not None
        and parquet_age > COLLECTOR_CRITICAL_SECONDS
        and spec.get("required")
        and not heartbeat_fresh
    ):
        return True, f"parquet_stale_{parquet_age}s"
    if (
        parquet_age is not None
        and parquet_age > COLLECTOR_CRITICAL_SECONDS
        and heartbeat_fresh
    ):
        print(
            f"[{datetime.now().isoformat()}] HOLD {name}: parquet stale "
            f"({parquet_age}s) but heartbeat fresh ({hb_age}s, {hb_status})"
        )
    return False, "ok"


def supervise(python: str, root: str, only_required: bool = False) -> None:
    print()
    print("COLLECTOR WATCHDOG")
    print("=" * 60)
    print(f"Root: {root}")
    print(f"Python: {python}")
    print(f"Check interval: {CHECK_INTERVAL_S}s")
    print()

    pids = _load_pids()
    restart_state = _load_restart_state()
    if not pids:
        print("Starting collectors...")
        pids = start_all(python, root, only_required=only_required)

    while True:
        reap_child_processes()
        audit = build_collector_audit(pids)
        export_collector_health_audit(pids)

        for spec in COLLECTORS:
            if only_required and not spec.get("required"):
                continue
            name = spec["name"]
            pid = pids.get(name)
            needs_restart, reason = _collector_needs_restart(
                name=name,
                spec=spec,
                pid=pid,
                audit=audit,
                watchdog_pid=os.getpid(),
            )

            if not needs_restart:
                continue

            allowed, allow_reason, delay = restart_allowed(name, restart_state)
            if not allowed:
                print(
                    f"[{datetime.now().isoformat()}] {allow_reason} {name}: "
                    f"reason={reason} delay={delay}"
                )
                write_heartbeat(
                    name,
                    status="ERROR",
                    event=allow_reason,
                    extra={"restart_reason": reason, "delay_s": delay},
                )
                _save_restart_state(restart_state)
                continue

            print(f"[{datetime.now().isoformat()}] RESTART {name}: {reason}")
            if pid:
                final_state = stop_pid(pid)
                print(f"  [STOP] {name} old_pid={pid} final_state={final_state}")
            # Clear stale PID before spawn.
            pids.pop(name, None)
            _save_pids(pids)

            record_restart_attempt(name, restart_state)
            _save_restart_state(restart_state)
            time.sleep(max(RESTART_MIN_DELAY_S, min(delay, RESTART_MAX_DELAY_S)))

            new_pid = start_collector(name, python, root)
            if new_pid:
                # Confirm single live writer.
                live = list_matching_pids(os.path.basename(spec["script"]))
                if len(live) > 1:
                    print(f"  [ERROR] {name}: duplicate writers after start: {live}")
                    for extra in live:
                        if extra != new_pid:
                            stop_pid(extra)
                pids[name] = new_pid
                _save_pids(pids)

        write_heartbeat(
            "watchdog",
            status="ALIVE",
            event="supervise_tick",
            extra={
                "managed_pids": pids,
                "overall": audit["overall"],
                "python": python,
                "restart_state": restart_state.get("collectors", {}),
            },
        )
        time.sleep(CHECK_INTERVAL_S)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collector watchdog")
    parser.add_argument("--audit-only", action="store_true", help="Export audit and exit")
    parser.add_argument("--start-only", action="store_true", help="Start collectors once and exit")
    parser.add_argument("--required-only", action="store_true", help="Manage required collectors only")
    parser.add_argument(
        "--python",
        default=None,
        help="Optional interpreter override (must be repo venv; forbidden bare Cellar)",
    )
    args = parser.parse_args()

    root = _repo_root()
    os.chdir(root)
    if args.python:
        if _is_forbidden_interpreter(args.python, root):
            print(f"ERROR: forbidden interpreter: {args.python}", file=sys.stderr)
            return 2
        python = args.python
    else:
        try:
            python = resolve_canonical_python(root)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    # Prefer invoking via venv path string for child argv clarity.
    venv_py = os.path.join(root, "venv", "bin", "python")
    if os.path.exists(venv_py) and os.access(venv_py, os.X_OK):
        python = venv_py

    if args.audit_only:
        paths = export_collector_health_audit(_load_pids())
        audit = build_collector_audit(_load_pids())
        print(json.dumps({"overall": audit["overall"], "exports": paths, "python": python}, indent=2))
        return 0 if audit["overall"] != "CRITICAL" else 1

    if args.start_only:
        start_all(python, root, only_required=args.required_only)
        export_collector_health_audit(_load_pids())
        return 0

    try:
        supervise(python, root, only_required=args.required_only)
    except KeyboardInterrupt:
        print("\nWatchdog stopped.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
