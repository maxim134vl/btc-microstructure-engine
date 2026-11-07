"""Persistent engine worker — executes engine scripts sequentially on JSON requests."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import traceback


def _kill_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _execute_request(request: dict) -> dict:
    python = sys.executable
    script_path = request["script_path"]
    cwd = request["cwd"]
    engine_name = request["engine_name"]
    timeout = int(request.get("timeout_seconds", 120))
    started = time.time()
    result: dict = {
        "engine": engine_name,
        "status": "error",
        "ok": False,
        "returncode": None,
        "elapsed_sec": 0.0,
    }
    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            [python, script_path],
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        returncode = proc.wait(timeout=timeout)
        stderr_tail = ""
        if proc.stderr is not None:
            stderr_tail = (proc.stderr.read() or "").strip()[-500:]
        result["returncode"] = returncode
        result["ok"] = returncode == 0
        result["status"] = "ok" if returncode == 0 else "error"
        if returncode != 0:
            detail = f": {stderr_tail}" if stderr_tail else ""
            result["error"] = f"ENGINE FAILED: {engine_name} (exit {returncode}){detail}"
    except subprocess.TimeoutExpired:
        if proc is not None:
            _kill_process(proc)
        result["status"] = "timeout"
        result["error"] = f"ENGINE TIMEOUT: {engine_name} exceeded {timeout}s"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)[:500]
        result["exception"] = exc.__class__.__name__
        result["traceback"] = traceback.format_exc()[-500:]
    result["elapsed_sec"] = round(time.time() - started, 2)
    return result


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        command = request.get("command")
        if command == "shutdown":
            print(json.dumps({"status": "shutdown", "ok": True}), flush=True)
            break
        if command == "ping":
            print(json.dumps({"status": "pong", "ok": True}), flush=True)
            continue
        print(json.dumps(_execute_request(request)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
