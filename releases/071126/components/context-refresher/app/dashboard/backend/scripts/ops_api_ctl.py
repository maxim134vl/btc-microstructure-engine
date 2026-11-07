#!/usr/bin/env python3
"""Durable control wrapper for the OPS dashboard API (run_api.py).

Starts the API in a new session so Cursor/shell teardown cannot kill it.
Does not touch LIVE1A/LIVE1B/MODEL services or frontend.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "dashboard" / "backend"
PYTHON = ROOT / "venv" / "bin" / "python"
SERVICE = BACKEND / "run_api.py"
DEFAULT_PID = ROOT / "run" / "ops_api.pid"
DEFAULT_LOG = ROOT / "logs" / "ops_api.log"
DEFAULT_HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))
HEALTH_URL_TMPL = "http://127.0.0.1:{port}/health"
SNAPSHOT_URL_TMPL = "http://127.0.0.1:{port}/api/v1/ops/snapshot"
COMMAND_MARKERS = ("run_api.py",)


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


def _write_pid_atomic(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(f"{pid}\n", encoding="utf-8")
    os.replace(tmp, path)


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _proc_command(pid: int) -> str:
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
        return out.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _command_identity_ok(command: str) -> bool:
    if not command:
        return False
    if not any(marker in command for marker in COMMAND_MARKERS):
        return False
    # Prefer repo-scoped identity when absolute path is present.
    if str(ROOT) in command or str(SERVICE) in command or "dashboard/backend/run_api.py" in command:
        return True
    # Accept bare run_api.py only when cwd cannot be proven here.
    return "run_api.py" in command


def resolve_managed_pid(pid_file: Path) -> dict[str, Any]:
    """Resolve PID file against a live process with run_api.py identity."""
    pid = _read_pid(pid_file)
    if pid is None:
        return {
            "pid": None,
            "alive": False,
            "stale_pid_file": False,
            "identity_ok": False,
            "command": None,
            "note": "no_pid_file",
        }
    if not _alive(pid):
        return {
            "pid": pid,
            "alive": False,
            "stale_pid_file": True,
            "identity_ok": False,
            "command": None,
            "note": "stale_pid_process_missing",
        }
    command = _proc_command(pid)
    identity_ok = _command_identity_ok(command)
    if not identity_ok:
        return {
            "pid": pid,
            "alive": True,
            "stale_pid_file": True,
            "identity_ok": False,
            "command": command,
            "note": "stale_pid_wrong_command_identity",
        }
    return {
        "pid": pid,
        "alive": True,
        "stale_pid_file": False,
        "identity_ok": True,
        "command": command,
        "note": "ok",
    }


def clear_stale_pid_file(pid_file: Path) -> dict[str, Any]:
    resolved = resolve_managed_pid(pid_file)
    if resolved["stale_pid_file"] and pid_file.exists():
        pid_file.unlink(missing_ok=True)
        resolved["cleared"] = True
    else:
        resolved["cleared"] = False
    return resolved


def _port_listener_pids(port: int) -> list[int]:
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return pids


def _port_available_or_ours(port: int, our_pid: int | None = None) -> dict[str, Any]:
    listeners = _port_listener_pids(port)
    if not listeners:
        return {"available": True, "listeners": [], "ours": False, "foreign": False}
    ours = []
    foreign = []
    for pid in listeners:
        cmd = _proc_command(pid)
        if _command_identity_ok(cmd) or (our_pid is not None and pid == our_pid):
            ours.append({"pid": pid, "command": cmd})
        else:
            foreign.append({"pid": pid, "command": cmd})
    return {
        "available": len(foreign) == 0 and (not ours or our_pid in {row["pid"] for row in ours}),
        "listeners": listeners,
        "ours": bool(ours),
        "foreign": bool(foreign),
        "our_listeners": ours,
        "foreign_listeners": foreign,
    }


def _http_get_json(url: str, timeout: float = 15.0) -> tuple[int | None, Any, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            status = int(resp.status)
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                return status, None, f"invalid_json:{exc}"
            return status, payload, None
    except urllib.error.HTTPError as exc:
        return int(exc.code), None, str(exc)
    except Exception as exc:  # noqa: BLE001 — surface exact probe failure
        return None, None, f"{type(exc).__name__}:{exc}"


def _wait_health(port: int, pid: int, timeout_s: float = 30.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {"ok": False}
    while time.time() < deadline:
        if not _alive(pid):
            return {"ok": False, "error": "process_died_during_health_wait", "pid": pid}
        status, payload, err = _http_get_json(HEALTH_URL_TMPL.format(port=port), timeout=3.0)
        last = {"ok": status == 200, "http_status": status, "payload": payload, "error": err}
        if status == 200:
            return last
        time.sleep(0.4)
    last["error"] = last.get("error") or "health_timeout"
    return last


def cmd_status(args: argparse.Namespace) -> int:
    resolved = resolve_managed_pid(args.pid_file)
    port_info = _port_available_or_ours(args.port, resolved.get("pid") if resolved.get("alive") else None)
    health_status, health_payload, health_err = _http_get_json(
        HEALTH_URL_TMPL.format(port=args.port), timeout=5.0
    )
    snap_status, snap_payload, snap_err = _http_get_json(
        SNAPSHOT_URL_TMPL.format(port=args.port), timeout=20.0
    )
    generated_at = None
    if isinstance(snap_payload, dict):
        generated_at = snap_payload.get("generated_at")
    out = {
        "pid": resolved.get("pid"),
        "alive": resolved.get("alive"),
        "command": resolved.get("command"),
        "identity_ok": resolved.get("identity_ok"),
        "stale_pid_file": resolved.get("stale_pid_file"),
        "pid_note": resolved.get("note"),
        "host": args.host,
        "port": args.port,
        "health_http_status": health_status,
        "health_error": health_err,
        "snapshot_http_status": snap_status,
        "snapshot_error": snap_err,
        "generated_at": generated_at,
        "log_path": str(args.log_file),
        "pid_file": str(args.pid_file),
        "port_listeners": port_info,
        "health_payload": health_payload if isinstance(health_payload, dict) else None,
    }
    print(json.dumps(out, indent=2, default=str))
    return 0 if resolved.get("alive") and health_status == 200 else 1


def cmd_health(args: argparse.Namespace) -> int:
    status, payload, err = _http_get_json(HEALTH_URL_TMPL.format(port=args.port), timeout=5.0)
    print(json.dumps({"http_status": status, "payload": payload, "error": err}, indent=2, default=str))
    return 0 if status == 200 else 1


def cmd_stop(args: argparse.Namespace) -> int:
    resolved = resolve_managed_pid(args.pid_file)
    pid = resolved.get("pid")
    if resolved.get("stale_pid_file"):
        clear_stale_pid_file(args.pid_file)
        print(json.dumps({"stopped": True, "pid": pid, "note": "cleared_stale_pid_file"}))
        return 0
    if not resolved.get("alive"):
        print(json.dumps({"stopped": True, "pid": pid, "note": "not_running"}))
        return 0
    assert isinstance(pid, int)
    if not resolved.get("identity_ok"):
        print(
            json.dumps(
                {
                    "stopped": False,
                    "pid": pid,
                    "error": "refusing_to_stop_foreign_or_unknown_identity",
                    "command": resolved.get("command"),
                }
            )
        )
        return 2
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if not _alive(pid):
            break
        time.sleep(0.25)
    forced = False
    if _alive(pid):
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.3)
        forced = True
    if args.pid_file.exists() and not _alive(pid):
        args.pid_file.unlink(missing_ok=True)
    print(json.dumps({"stopped": not _alive(pid), "pid": pid, "forced_kill": forced}))
    return 0 if not _alive(pid) else 1


def cmd_start(args: argparse.Namespace) -> int:
    cleared = clear_stale_pid_file(args.pid_file)
    resolved = resolve_managed_pid(args.pid_file)
    if resolved.get("alive") and resolved.get("identity_ok"):
        health = _wait_health(args.port, int(resolved["pid"]), timeout_s=5.0)
        print(
            json.dumps(
                {
                    "started": False,
                    "already_running": True,
                    "pid": resolved["pid"],
                    "health": health,
                    "stale_cleared": cleared.get("cleared"),
                },
                indent=2,
                default=str,
            )
        )
        return 0 if health.get("ok") else 1

    port_info = _port_available_or_ours(args.port)
    if port_info.get("foreign"):
        print(
            json.dumps(
                {
                    "started": False,
                    "error": "port_conflict_foreign_listener",
                    "port": args.port,
                    "foreign_listeners": port_info.get("foreign_listeners"),
                },
                indent=2,
                default=str,
            )
        )
        return 3
    if port_info.get("ours"):
        # Repo run_api already listening but PID file was missing/stale — adopt.
        adopt_pid = port_info["our_listeners"][0]["pid"]
        _write_pid_atomic(args.pid_file, adopt_pid)
        health = _wait_health(args.port, adopt_pid, timeout_s=10.0)
        print(
            json.dumps(
                {
                    "started": False,
                    "adopted": True,
                    "pid": adopt_pid,
                    "health": health,
                },
                indent=2,
                default=str,
            )
        )
        return 0 if health.get("ok") else 1

    if not PYTHON.exists():
        print(json.dumps({"started": False, "error": f"missing_interpreter:{PYTHON}"}))
        return 4
    if not SERVICE.exists():
        print(json.dumps({"started": False, "error": f"missing_service:{SERVICE}"}))
        return 4

    args.pid_file.parent.mkdir(parents=True, exist_ok=True)
    args.log_file.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{BACKEND}{os.pathsep}{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["PYTHONUNBUFFERED"] = "1"
    env["DASHBOARD_HOST"] = args.host
    env["DASHBOARD_PORT"] = str(args.port)

    log_fh = args.log_file.open("a", encoding="utf-8")
    log_fh.write(f"\n--- ops_api_ctl start {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ---\n")
    log_fh.flush()

    proc = subprocess.Popen(
        [str(PYTHON), str(SERVICE)],
        cwd=str(BACKEND),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _write_pid_atomic(args.pid_file, proc.pid)

    if not _alive(proc.pid):
        print(
            json.dumps(
                {
                    "started": False,
                    "error": "process_exited_immediately",
                    "pid": proc.pid,
                    "log_path": str(args.log_file),
                },
                indent=2,
            )
        )
        return 5

    health = _wait_health(args.port, proc.pid, timeout_s=args.health_timeout)
    if not health.get("ok"):
        print(
            json.dumps(
                {
                    "started": False,
                    "error": "health_check_failed",
                    "pid": proc.pid,
                    "health": health,
                    "log_path": str(args.log_file),
                },
                indent=2,
                default=str,
            )
        )
        return 6

    print(
        json.dumps(
            {
                "started": True,
                "pid": proc.pid,
                "host": args.host,
                "port": args.port,
                "pid_file": str(args.pid_file),
                "log_path": str(args.log_file),
                "start_new_session": True,
                "health_http_status": health.get("http_status"),
                "command": _proc_command(proc.pid),
            },
            indent=2,
            default=str,
        )
    )
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    stop_code = cmd_stop(args)
    if stop_code not in (0,):
        # stop may return 2 for foreign identity — do not start over it
        if stop_code == 2:
            return stop_code
    time.sleep(0.5)
    return cmd_start(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Durable OPS API control")
    parser.add_argument("command", choices=["start", "stop", "restart", "status", "health"])
    parser.add_argument("--pid-file", type=Path, default=DEFAULT_PID)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--health-timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "start":
        return cmd_start(args)
    if args.command == "stop":
        return cmd_stop(args)
    if args.command == "restart":
        return cmd_restart(args)
    if args.command == "health":
        return cmd_health(args)
    return cmd_status(args)


if __name__ == "__main__":
    raise SystemExit(main())
