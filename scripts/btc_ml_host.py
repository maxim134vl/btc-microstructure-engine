#!/usr/bin/env python3
"""Host launchers for the current hybrid runtime.

  ./scripts/btc_ml model start|stop|status|restart
  ./scripts/btc_ml dashboard start|stop|status|restart
  ./scripts/btc_ml drift start     # only after ~400 closed trades

Hybrid model: S4.1 TimeframeManager + LIVE1B paper books. S4.1 traders stay stopped.
Dashboard: OPS API + UI + visual refresher + chart :8765.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "run"
LOGS = ROOT / "run" / "logs"
STACK_LOGS = ROOT / "logs" / "runtime_stack"
TF_CTL = ROOT / "scripts" / "timeframe_trading_ctl.sh"
DAEMON_CTL = ROOT / "scripts/ops/context_refresh_daemon_ctl.sh"
DRIFT_CTL = ROOT / "scripts/model_assurance/drift_monitoring_ctl.py"

MODEL_CTLS: list[tuple[str, Path]] = [
    ("live1a", ROOT / "scripts/live/intrabar_cognition_ctl.py"),
    ("live1b", ROOT / "scripts/live/intrabar_paper_ctl.py"),
    ("timeframe_manager", ROOT / "scripts/live/timeframe_manager_ctl.py"),
    ("intrabar_supervisor", ROOT / "scripts/live/intrabar_process_supervisor_ctl.py"),
    ("stp_be33", ROOT / "scripts/live/shadow_stp_be33_ctl.py"),
    ("trd_outcome2", ROOT / "scripts/live/trd_outcome2_ctl.py"),
    ("shadow_auction", ROOT / "scripts/live/shadow_auction_ctl.py"),
    ("shadow_structural_protection", ROOT / "scripts/live/shadow_structural_protection_ctl.py"),
    ("shadow_economic_correlation", ROOT / "scripts/live/shadow_economic_correlation_ctl.py"),
    ("shadow_model", ROOT / "scripts/model_assurance/shadow_model_ctl.py"),
    ("behavioral_validation", ROOT / "scripts/model_assurance/behavioral_validation_ctl.py"),
    ("economic_validation", ROOT / "scripts/model_assurance/economic_validation_ctl.py"),
    ("external_data_toxicity", ROOT / "scripts/model_assurance/external_data_toxicity_ctl.py"),
    ("current_toxicity", ROOT / "scripts/model_assurance/current_toxicity_ctl.py"),
    ("incident_correlation", ROOT / "scripts/model_assurance/incident_correlation_ctl.py"),
    ("promotion_gate", ROOT / "scripts/model_assurance/promotion_gate_ctl.py"),
    ("model_assurance_summary", ROOT / "scripts/model_assurance/model_assurance_summary_ctl.py"),
]

# Full stop matches by command line. Dashboard stop must not match model, and vice versa.
MODEL_STOP_PATTERNS: list[tuple[str, str]] = [
    ("timeframe_trader", r"timeframe_trader_daemon\.py"),
    ("timeframe_manager", r"timeframe_manager_daemon\.py"),
    ("live1b", r"run_intrabar_paper_manager\.py"),
    ("live1a", r"run_intrabar_cognition_service\.py"),
    ("intrabar_supervisor", r"intrabar_process_supervisor\.py"),
    ("stp_be33", r"run_shadow_stp_be33\.py"),
    ("trd_outcome2", r"run_trd_outcome2_refresh\.py"),
    ("shadow_auction", r"run_shadow_auction\.py"),
    ("shadow_structural", r"run_shadow_structural_protection\.py"),
    ("eqcorr", r"run_shadow_economic_correlation\.py"),
    ("collector_watchdog", r"collector_watchdog\.py"),
    ("run.py", str(ROOT / "run.py")),
    ("context_refresh_daemon", r"run_context_refresh_daemon\.py"),
]

DASHBOARD_STOP_PATTERNS: list[tuple[str, str]] = [
    ("ops_api", r"dashboard/backend/run_api\.py"),
    ("dashboard_ui", r"vite --host 127\.0\.0\.1 --port 5173"),
    ("trade_chart", r"http\.server 8765"),
    ("visual_refresher", r"run_market_context_visual_refresher\.py"),
]


def _python() -> str:
    for cand in (ROOT / "venv" / "bin" / "python", ROOT / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["BTC_ML_CONTEXT_REFRESH_DAEMON"] = "1"
    env.setdefault("BTC_ML_ENGINE_EXECUTION_MODE", "persistent_worker")
    return env


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, TypeError, ValueError):
        return None


def _pattern_pids(pattern: str) -> list[int]:
    try:
        out = subprocess.check_output(["pgrep", "-f", pattern], text=True)
    except subprocess.CalledProcessError:
        return []
    pids: list[int] = []
    for line in out.split():
        try:
            pid = int(line)
        except ValueError:
            continue
        if pid != os.getpid() and _alive(pid):
            pids.append(pid)
    return pids


def _pattern_alive(pattern: str) -> int | None:
    pids = _pattern_pids(pattern)
    return pids[0] if pids else None


def _ok_already(stdout: str) -> bool:
    text = stdout.lower()
    return any(
        token in text
        for token in ("already_running", "already running", "stp_be33_already_running")
    )


def run_ctl(script: Path, action: str) -> dict[str, object]:
    proc = subprocess.run(
        [_python(), str(script), action],
        cwd=ROOT,
        env=_env(),
        capture_output=True,
        text=True,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 or (action == "start" and _ok_already(combined))
    return {
        "script": str(script.relative_to(ROOT)),
        "action": action,
        "ok": ok,
        "returncode": proc.returncode,
        "stdout": combined.strip()[-800:],
    }


def run_tf_ctl(action: str, target: str) -> dict[str, object]:
    proc = subprocess.run(
        ["bash", str(TF_CTL), action, target],
        cwd=ROOT,
        env=_env(),
        capture_output=True,
        text=True,
    )
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    ok = proc.returncode == 0 or (action == "start" and _ok_already(text))
    return {
        "script": "scripts/timeframe_trading_ctl.sh",
        "action": f"{action} {target}",
        "ok": ok,
        "returncode": proc.returncode,
        "stdout": text[-800:],
    }


def detach(
    name: str,
    pid_path: Path,
    log_path: Path,
    argv: list[str],
    *,
    cwd: Path | None = None,
    pattern: str | None = None,
) -> dict[str, object]:
    existing = _read_pid(pid_path)
    if _alive(existing):
        return {"name": name, "ok": True, "pid": existing, "note": "already_running"}
    if pattern:
        found = _pattern_alive(pattern)
        if found:
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(f"{found}\n", encoding="utf-8")
            return {"name": name, "ok": True, "pid": found, "note": "adopted"}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd or ROOT),
        env=_env(),
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_path.write_text(f"{proc.pid}\n", encoding="utf-8")
    time.sleep(0.4)
    return {"name": name, "ok": _alive(proc.pid), "pid": proc.pid}


def _kill_pid(pid: int) -> None:
    if not _alive(pid):
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if not _alive(pid):
            return
        time.sleep(0.15)
    if _alive(pid):
        os.kill(pid, signal.SIGKILL)


def stop_pid_file(name: str, pid_path: Path) -> dict[str, object]:
    pid = _read_pid(pid_path)
    stopped: list[int] = []
    if _alive(pid) and pid is not None:
        _kill_pid(pid)
        stopped.append(pid)
    pid_path.unlink(missing_ok=True)
    return {"name": name, "stopped": stopped}


def stop_patterns(pairs: list[tuple[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, pattern in pairs:
        pids = _pattern_pids(pattern)
        for pid in pids:
            _kill_pid(pid)
        rows.append({"name": name, "pattern": pattern, "stopped": pids})
    return rows


def _start_daemon() -> dict[str, object]:
    proc = subprocess.run(
        ["bash", str(DAEMON_CTL), "start"],
        cwd=ROOT,
        env=_env(),
        capture_output=True,
        text=True,
    )
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return {
        "script": "scripts/ops/context_refresh_daemon_ctl.sh",
        "action": "start",
        "ok": proc.returncode == 0 or "already" in text.lower(),
        "returncode": proc.returncode,
        "stdout": text[-800:],
    }


def _stop_daemon() -> dict[str, object]:
    proc = subprocess.run(
        ["bash", str(DAEMON_CTL), "stop"],
        cwd=ROOT,
        env=_env(),
        capture_output=True,
        text=True,
    )
    return {"script": "context_refresh_daemon_ctl.sh", "ok": proc.returncode == 0, "returncode": proc.returncode}


def model_start() -> int:
    results: list[dict[str, object]] = [
        detach(
            "collector_watchdog",
            RUN / "collector_watchdog.pid",
            LOGS / "collector_watchdog.log",
            [_python(), str(ROOT / "collector_watchdog.py"), "--required-only"],
            pattern="collector_watchdog.py",
        ),
        detach(
            "run.py",
            RUN / "canonical_runtime.pid",
            STACK_LOGS / "runtime.log",
            [_python(), str(ROOT / "run.py")],
            pattern=str(ROOT / "run.py"),
        ),
        _start_daemon(),
        run_tf_ctl("stop", "traders"),
        run_tf_ctl("start", "manager"),
    ]
    for _name, script in MODEL_CTLS:
        results.append(run_ctl(script, "start"))
    print(json.dumps({"profile": "model", "action": "start", "hybrid": True, "results": results}, indent=2, default=str))
    return 0 if all(bool(row.get("ok", True)) for row in results) else 1


def model_stop() -> int:
    """Full model teardown: traders (if any), manager, LIVE1A/B, shadows, run.py."""
    results: list[dict[str, object]] = [
        run_tf_ctl("stop", "traders"),
        run_tf_ctl("stop", "manager"),
    ]
    results.extend(run_ctl(script, "stop") for _name, script in reversed(MODEL_CTLS))
    results.append(_stop_daemon())
    results.append(stop_pid_file("run.py", RUN / "canonical_runtime.pid"))
    results.append(stop_pid_file("collector_watchdog", RUN / "collector_watchdog.pid"))
    results.extend(stop_patterns(MODEL_STOP_PATTERNS))
    print(json.dumps({"profile": "model", "action": "stop", "results": results}, indent=2, default=str))
    return 0


def _pid_status(name: str, pid_path: Path, pattern: str, *, required: bool = True) -> dict[str, object]:
    pid = _read_pid(pid_path) or _pattern_alive(pattern)
    return {"name": name, "pid": pid, "alive": _alive(pid), "required": required}


def model_status() -> int:
    trader_pids = {
        tf: _pattern_alive(rf"timeframe_trader_daemon\.py --timeframe {tf}( |$)")
        for tf in ("M15", "M30", "H1", "H4")
    }
    rows = [
        _pid_status("run.py", RUN / "canonical_runtime.pid", str(ROOT / "run.py")),
        _pid_status("collector_watchdog", RUN / "collector_watchdog.pid", "collector_watchdog.py"),
        _pid_status("timeframe_manager", RUN / "timeframe_manager.pid", r"timeframe_manager_daemon\.py"),
        _pid_status("live1a", RUN / "intrabar_cognition.pid", "run_intrabar_cognition_service.py"),
        _pid_status("live1b", RUN / "intrabar_paper_manager.pid", "run_intrabar_paper_manager.py"),
        _pid_status("supervisor", RUN / "intrabar_process_supervisor.pid", "intrabar_process_supervisor.py"),
        _pid_status("stp_be33", RUN / "shadow_stp_be33.pid", "run_shadow_stp_be33.py"),
        _pid_status("trd_outcome2", RUN / "trd_outcome2_refresh.pid", "run_trd_outcome2_refresh.py", required=False),
        _pid_status("shadow_auction", RUN / "shadow_auction.pid", "run_shadow_auction.py"),
        _pid_status("shadow_structural", RUN / "shadow_structural_protection.pid", "run_shadow_structural_protection.py"),
        _pid_status("eqcorr", RUN / "shadow_economic_correlation.pid", "run_shadow_economic_correlation.py"),
        _pid_status("drift", RUN / "drift_monitoring.pid", "run_drift_monitoring.py", required=False),
        {
            "name": "s41_traders",
            "required": False,
            "expected": "STOPPED",
            "pids": trader_pids,
            "alive": any(_alive(pid) for pid in trader_pids.values()),
        },
    ]
    print(json.dumps({"profile": "model", "hybrid": True, "processes": rows}, indent=2))
    required_ok = all(row.get("alive") for row in rows if row.get("required") is True)
    traders_down = not any(_alive(pid) for pid in trader_pids.values())
    return 0 if required_ok and traders_down else 1


def dashboard_start() -> int:
    results = [
        run_ctl(ROOT / "dashboard/backend/scripts/ops_api_ctl.py", "start"),
        detach(
            "dashboard_ui",
            STACK_LOGS / "dashboard_ui.pid",
            STACK_LOGS / "dashboard_ui.log",
            ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
            cwd=ROOT / "dashboard" / "frontend",
            pattern="vite --host 127.0.0.1 --port 5173",
        ),
        detach(
            "visual_refresher",
            STACK_LOGS / "context_visual_refresher.pid",
            ROOT / "logs" / "context_visual_refresher.log",
            [
                _python(),
                str(ROOT / "scripts/live/run_market_context_visual_refresher.py"),
                "--interval-seconds",
                "20",
            ],
            pattern="run_market_context_visual_refresher.py",
        ),
        detach(
            "trade_chart",
            STACK_LOGS / "context_visual_viewer.pid",
            STACK_LOGS / "context_visual_viewer.log",
            [_python(), "-m", "http.server", "8765", "--bind", "127.0.0.1"],
            cwd=ROOT / "apps/context_visualizer/public",
            pattern="http.server 8765",
        ),
    ]
    print(json.dumps({"profile": "dashboard", "action": "start", "results": results}, indent=2, default=str))
    print("OPS UI  http://127.0.0.1:5173", file=sys.stderr)
    print("OPS API http://127.0.0.1:8080/health", file=sys.stderr)
    print("Chart   http://127.0.0.1:8765/index.html", file=sys.stderr)
    return 0 if all(bool(row.get("ok", True)) for row in results) else 1


def dashboard_stop() -> int:
    """Full dashboard teardown: API, UI, chart :8765, visual refresher."""
    results: list[dict[str, object]] = [
        run_ctl(ROOT / "dashboard/backend/scripts/ops_api_ctl.py", "stop"),
        stop_pid_file("dashboard_ui", STACK_LOGS / "dashboard_ui.pid"),
        stop_pid_file("visual_refresher", STACK_LOGS / "context_visual_refresher.pid"),
        stop_pid_file("visual_refresher_legacy", ROOT / "runtime_context_visual_refresher.pid"),
        stop_pid_file("trade_chart", STACK_LOGS / "context_visual_viewer.pid"),
    ]
    results.extend(stop_patterns(DASHBOARD_STOP_PATTERNS))
    print(json.dumps({"profile": "dashboard", "action": "stop", "results": results}, indent=2, default=str))
    return 0


def dashboard_status() -> int:
    rows = [
        _pid_status("dashboard_api", RUN / "ops_api.pid", r"dashboard/backend/run_api\.py"),
        _pid_status("dashboard_ui", STACK_LOGS / "dashboard_ui.pid", "vite --host 127.0.0.1 --port 5173"),
        _pid_status("visual_refresher", STACK_LOGS / "context_visual_refresher.pid", "run_market_context_visual_refresher.py"),
        _pid_status("trade_chart", STACK_LOGS / "context_visual_viewer.pid", "http.server 8765"),
    ]
    print(json.dumps({"profile": "dashboard", "processes": rows}, indent=2))
    return 0 if all(row["alive"] for row in rows) else 1


def drift_start() -> int:
    result = run_ctl(DRIFT_CTL, "start")
    print(json.dumps({"profile": "drift", "action": "start", "result": result}, indent=2))
    return 0 if result["ok"] else 1


def drift_stop() -> int:
    result = run_ctl(DRIFT_CTL, "stop")
    print(json.dumps({"profile": "drift", "action": "stop", "result": result}, indent=2))
    return 0 if result["ok"] else 1


def drift_status() -> int:
    result = run_ctl(DRIFT_CTL, "status")
    print(result.get("stdout") or json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="BTC-ML host profiles: model / dashboard / drift")
    parser.add_argument("profile", choices=("model", "dashboard", "drift"))
    parser.add_argument("action", choices=("start", "stop", "status", "restart"))
    args = parser.parse_args()
    table = {
        ("model", "start"): model_start,
        ("model", "stop"): model_stop,
        ("model", "status"): model_status,
        ("dashboard", "start"): dashboard_start,
        ("dashboard", "stop"): dashboard_stop,
        ("dashboard", "status"): dashboard_status,
        ("drift", "start"): drift_start,
        ("drift", "stop"): drift_stop,
        ("drift", "status"): drift_status,
    }
    if args.action == "restart":
        table[(args.profile, "stop")]()
        return table[(args.profile, "start")]()
    return table[(args.profile, args.action)]()


if __name__ == "__main__":
    raise SystemExit(main())
