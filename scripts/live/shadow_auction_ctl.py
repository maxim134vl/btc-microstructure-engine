#!/usr/bin/env python3
"""Operational controller for AUCTION_EPISODE_SHADOW (AES6D).

Manages only Shadow Auction. Never starts/stops canonical trading.
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

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.shadow_auction import SHADOW_REFUSED  # noqa: E402
from btc_ml.trading.shadow_auction.contract import load_config  # noqa: E402
from btc_ml.trading.shadow_auction.integrity import IntegrityAuditor, write_audit_report  # noqa: E402
from btc_ml.trading.shadow_auction.paths import (  # noqa: E402
    assert_not_forbidden_persistent,
    assert_shadow_write_path,
    forbidden_persistent_roots,
)
from btc_ml.trading.shadow_auction.replay import REFUSE_UNBOUNDED, ReplayRunner  # noqa: E402
from btc_ml.trading.shadow_auction.runtime import refuse_without_storage  # noqa: E402
from btc_ml.trading.shadow_auction.storage import (  # noqa: E402
    is_real_mounted_volume,
    validate_external_storage,
)

RUNNER = REPO / "scripts" / "live" / "run_shadow_auction.py"
DEFAULT_PID = REPO / "run" / "shadow_auction.pid"
DEFAULT_LOG = REPO / "run" / "logs" / "shadow_auction.log"
LOCK_NAME = "run/shadow_auction.lock"


def _python() -> str:
    for cand in (REPO / "venv" / "bin" / "python", REPO / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def _cfg(config: Path | None = None) -> dict:
    return load_config(config, repo_root=REPO)


def _pid_path(config: dict | None = None) -> Path:
    cfg = config or {}
    return REPO / str(cfg.get("pid_file") or "run/shadow_auction.pid")


def _lock_path() -> Path:
    return REPO / LOCK_NAME


def _health_path(config: dict) -> Path:
    return Path(config["data_root"]) / "health" / "health.json"


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _identity_ok(pid: int) -> bool:
    """Confirm process is our Shadow Auction runner, not a name collision."""
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
    except Exception:
        return False
    return "run_shadow_auction.py" in out


def _print(payload: dict) -> None:
    print(json.dumps(payload, indent=2, default=str), flush=True)


def cmd_doctor(config_path: Path | None = None) -> int:
    findings: list[dict] = []

    def note(level: str, code: str, message: str, **ctx) -> None:
        findings.append({"severity": level, "code": code, "message": message, **ctx})

    try:
        config = _cfg(config_path)
        note("PASS", "CONFIG_OK", "config readable")
    except Exception as exc:
        _print({"status": "FAIL", "findings": [{"severity": "FAIL", "code": "CONFIG", "message": str(exc)}]})
        return 2

    if not bool(config.get("observer_only", True)):
        note("FAIL", "OBSERVER_ONLY", "observer_only must be true")
    else:
        note("PASS", "OBSERVER_ONLY", "observer_only=true")
    if bool(config.get("enforcement_enabled", False)):
        note("FAIL", "ENFORCEMENT", "enforcement_enabled must be false")
    else:
        note("PASS", "ENFORCEMENT", "enforcement_enabled=false")

    volume = Path(config["required_volume_root"])
    data_root = Path(config["data_root"])
    if not volume.exists() or not is_real_mounted_volume(volume):
        note("FAIL", "SSD_NOT_MOUNTED", f"{volume} not a real mounted volume")
    else:
        note("PASS", "SSD_MOUNTED", f"{volume} mounted")

    validation = validate_external_storage(
        data_root=data_root,
        volume_root=volume,
        min_free_bytes=int(config.get("min_free_bytes") or 0),
        repo=REPO,
    )
    if validation.ok:
        note("PASS", "STORAGE_WRITABLE", "external Shadow root writable")
    else:
        note("FAIL", "STORAGE", validation.error or "storage validation failed")

    # Write boundary self-check against sibling roots.
    for forbidden in forbidden_persistent_roots(REPO):
        try:
            assert_not_forbidden_persistent(forbidden / "probe", repo=REPO)
            note("FAIL", "BOUNDARY", f"forbidden root not blocked: {forbidden}")
        except RuntimeError:
            note("PASS", "BOUNDARY_BLOCKED", f"blocked {forbidden}")

    try:
        assert_shadow_write_path(data_root / "memory" / "probe.json", data_root=data_root, repo=REPO)
        note("PASS", "WRITE_BOUNDARY", "Shadow root write path allowed")
    except Exception as exc:
        note("FAIL", "WRITE_BOUNDARY", str(exc))

    # Source readability (read-only).
    sources = [
        REPO / "data" / "cognition" / "candle_structure_memory.parquet",
        REPO / "data" / "cognition" / "volume_classification_memory.parquet",
    ]
    readable = [str(p) for p in sources if p.exists()]
    if readable:
        note("PASS", "SOURCES_READABLE", "canonical source journals present", paths=readable)
    else:
        note("WARNING", "SOURCES_MISSING", "no cognition parquet sources found")

    pid = _read_pid(_pid_path(config))
    if pid and _alive(pid) and _identity_ok(pid):
        note("PASS", "PID_LIVE", f"live process pid={pid}")
    elif pid and not _alive(pid):
        note("WARNING", "STALE_PID", f"stale pid file pid={pid}")
    else:
        note("PASS", "PID_CLEAR", "no live Shadow Auction process")

    status = "PASS"
    if any(f["severity"] == "FAIL" for f in findings):
        status = "FAIL"
    elif any(f["severity"] == "WARNING" for f in findings):
        status = "WARNING"
    _print({"status": status, "findings": findings, "data_root": str(data_root)})
    return 0 if status != "FAIL" else 2


def cmd_status(config_path: Path | None = None) -> int:
    config = _cfg(config_path)
    pid_path = _pid_path(config)
    pid = _read_pid(pid_path)
    alive = _alive(pid) and (pid is None or _identity_ok(pid))
    health = None
    hp = _health_path(config)
    if hp.exists():
        try:
            health = json.loads(hp.read_text(encoding="utf-8"))
        except Exception as exc:
            health = {"error": str(exc)}
    status = "STOPPED"
    if alive:
        status = str((health or {}).get("status") or "RUNNING")
    elif health and health.get("status") in {"FAILED", "STORAGE_CRITICAL", "DEGRADED_STORAGE"}:
        status = str(health.get("status"))
    summary = {
        "status": status,
        "pid": pid if alive else None,
        "alive": alive,
        "pid_path": str(pid_path),
        "data_root": config.get("data_root"),
        "observer_only": config.get("observer_only"),
        "enforcement_enabled": config.get("enforcement_enabled"),
        "ssd_mounted": bool((health or {}).get("storage_mounted")),
        "storage_free_bytes": (health or {}).get("disk_free_bytes") or (health or {}).get("storage_free_bytes"),
        "shadow_total_bytes": (health or {}).get("shadow_total_bytes"),
        "m15_family": (health or {}).get("m15_family") or (health or {}).get("m15_auction_family"),
        "m30_family": (health or {}).get("m30_family") or (health or {}).get("m30_auction_family"),
        "h1_family": (health or {}).get("h1_family") or (health or {}).get("h1_auction_family"),
        "h4_family": (health or {}).get("h4_family") or (health or {}).get("h4_auction_family"),
        "hierarchy_state": (health or {}).get("hierarchy_state"),
        "last_source_timestamp": (health or {}).get("last_source_timestamp"),
        "source_lag_ms": (health or {}).get("source_lag_ms"),
        "checkpoint_count": (health or {}).get("checkpoint_count")
        or (health or {}).get("canonical_checkpoints_written"),
        "outcome_count": (health or {}).get("outcome_count") or (health or {}).get("closed_cases_evaluated"),
        "postmortems_waiting": (health or {}).get("postmortems_waiting")
        or (health or {}).get("postmortems_waiting_resolution"),
        "rss_memory_mb": (health or {}).get("rss_memory_mb"),
        "last_error": (health or {}).get("last_error") or (health or {}).get("error"),
        "health_path": str(hp),
    }
    _print(summary)
    return 0


def cmd_stop(config_path: Path | None = None) -> int:
    config = _cfg(config_path)
    pid_path = _pid_path(config)
    pid = _read_pid(pid_path)
    targets: list[int] = []
    if pid and _alive(pid) and _identity_ok(pid):
        targets.append(pid)
    # Discover orphans that are clearly our runner.
    try:
        out = subprocess.check_output(["pgrep", "-f", str(RUNNER)], text=True)
        for raw in out.split():
            if raw.strip().isdigit():
                cand = int(raw)
                if cand not in targets and _identity_ok(cand):
                    targets.append(cand)
    except Exception:
        pass
    if not targets:
        pid_path.unlink(missing_ok=True)
        _lock_path().unlink(missing_ok=True)
        _print({"status": "not_running"})
        return 0
    for target in targets:
        try:
            os.kill(target, signal.SIGTERM)
        except OSError:
            continue
        for _ in range(50):
            if not _alive(target):
                break
            time.sleep(0.2)
        # Do not SIGKILL as normal path.
    pid_path.unlink(missing_ok=True)
    _lock_path().unlink(missing_ok=True)
    _print({"status": "stopped", "pids": targets, "forced_kill": False})
    return 0


def _acquire_lock(config: dict) -> tuple[bool, str]:
    lock = _lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    pid_path = _pid_path(config)
    existing = _read_pid(pid_path)
    if existing and _alive(existing) and _identity_ok(existing):
        return False, f"duplicate process refused pid={existing}"
    if existing and not _alive(existing):
        # Stale PID recovery.
        pid_path.unlink(missing_ok=True)
    if lock.exists():
        try:
            stale_pid = int(lock.read_text(encoding="utf-8").strip())
        except Exception:
            stale_pid = None
        if stale_pid and _alive(stale_pid) and _identity_ok(stale_pid):
            return False, f"lock held by pid={stale_pid}"
        lock.unlink(missing_ok=True)
    lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return True, "ok"


def cmd_start(config_path: Path | None = None) -> int:
    # Preflight
    rc = cmd_doctor(config_path)
    if rc != 0:
        _print({"status": "start_refused", "reason": "doctor_failed"})
        return rc
    config = _cfg(config_path)
    ok, reason = _acquire_lock(config)
    if not ok:
        _print({"status": "start_refused", "reason": reason})
        return 1
    gate = refuse_without_storage(repo=REPO, config_path=config_path)
    if not gate.get("ok"):
        _print({"status": SHADOW_REFUSED, **gate})
        return 2
    DEFAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
    pid_path = _pid_path(config)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = DEFAULT_LOG.open("a", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    cmd = [_python(), str(RUNNER)]
    if config_path:
        cmd += ["--config", str(config_path)]
    # Normal start: NO --backfill
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    pid_path.write_text(f"{proc.pid}\n", encoding="utf-8")
    _lock_path().write_text(f"{proc.pid}\n", encoding="utf-8")
    time.sleep(1.0)
    if not _alive(proc.pid):
        _print({"status": "start_failed", "pid": proc.pid, "log": str(DEFAULT_LOG)})
        return 1
    _print(
        {
            "status": "started",
            "pid": proc.pid,
            "log": str(DEFAULT_LOG),
            "data_root": config["data_root"],
            "observer_only": True,
            "enforcement_enabled": False,
            "backfill": False,
        }
    )
    return 0


def cmd_restart(config_path: Path | None = None) -> int:
    cmd_stop(config_path)
    time.sleep(0.5)
    return cmd_start(config_path)


def cmd_once(config_path: Path | None = None) -> int:
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    cmd = [_python(), str(RUNNER), "--once"]
    if config_path:
        cmd += ["--config", str(config_path)]
    proc = subprocess.run(cmd, cwd=str(REPO), env=env)
    return int(proc.returncode)


def cmd_audit(config_path: Path | None = None) -> int:
    config = _cfg(config_path)
    data_root = Path(config["data_root"])
    # Snapshot sizes before to prove read-only.
    mem = data_root / "memory"
    before = {
        p.name: (p.stat().st_size if p.exists() else 0)
        for p in mem.glob("*.jsonl")
    } if mem.exists() else {}
    auditor = IntegrityAuditor(data_root=data_root)
    report = auditor.run()
    write_audit_report(data_root, report, repo=REPO)
    after = {
        p.name: (p.stat().st_size if p.exists() else 0)
        for p in mem.glob("*.jsonl")
    } if mem.exists() else {}
    if before != after:
        report["status"] = "FAIL"
        report.setdefault("findings", []).append(
            {
                "severity": "FAIL",
                "code": "AUDIT_NOT_READONLY",
                "message": "audit mutated live memory sizes",
            }
        )
    _print(report)
    return 0 if report.get("status") != "FAIL" else 2


def cmd_replay(
    *,
    config_path: Path | None,
    from_ts: str | None,
    to_ts: str | None,
    warmup_from: str | None,
) -> int:
    if not from_ts or not to_ts:
        _print({"status": REFUSE_UNBOUNDED, "ok": False})
        return 2
    config = _cfg(config_path)
    live_root = Path(config["data_root"])
    mem = live_root / "memory"
    before = {
        str(p): (p.stat().st_size if p.exists() else 0)
        for p in [
            mem / "tf_event_memory.jsonl",
            mem / "tf_episode_memory.jsonl",
            mem / "hierarchy_memory.jsonl",
            mem / "canonical_checkpoint_memory.jsonl",
            mem / "checkpoint_verdict_memory.jsonl",
            mem / "shadow_outcome_memory.jsonl",
            mem / "postmortem_memory.jsonl",
        ]
    }
    try:
        runner = ReplayRunner.create(
            repo=REPO,
            config_path=config_path,
            evaluation_from=from_ts,
            evaluation_to=to_ts,
            warmup_from=warmup_from,
        )
        result = runner.run()
    except Exception as exc:
        _print({"status": "REPLAY_FAILED", "ok": False, "error": str(exc), "canonical_unaffected": True})
        return 2
    after = {
        str(p): (p.stat().st_size if p.exists() else 0)
        for p in [
            mem / "tf_event_memory.jsonl",
            mem / "tf_episode_memory.jsonl",
            mem / "hierarchy_memory.jsonl",
            mem / "canonical_checkpoint_memory.jsonl",
            mem / "checkpoint_verdict_memory.jsonl",
            mem / "shadow_outcome_memory.jsonl",
            mem / "postmortem_memory.jsonl",
        ]
    }
    result["live_memory_unchanged"] = before == after
    if before != after:
        result["ok"] = False
        result["status"] = "REPLAY_WROTE_LIVE_MEMORY"
        _print(result)
        return 2
    result["status"] = "REPLAY_COMPLETE"
    _print(result)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Shadow Auction AES6 controller")
    ap.add_argument(
        "action",
        choices=("start", "stop", "restart", "status", "once", "doctor", "audit", "replay"),
    )
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--from", dest="from_ts", default=None)
    ap.add_argument("--to", dest="to_ts", default=None)
    ap.add_argument("--warmup-from", dest="warmup_from", default=None)
    args = ap.parse_args()

    if args.action == "doctor":
        return cmd_doctor(args.config)
    if args.action == "status":
        return cmd_status(args.config)
    if args.action == "stop":
        return cmd_stop(args.config)
    if args.action == "start":
        return cmd_start(args.config)
    if args.action == "restart":
        return cmd_restart(args.config)
    if args.action == "once":
        return cmd_once(args.config)
    if args.action == "audit":
        return cmd_audit(args.config)
    if args.action == "replay":
        return cmd_replay(
            config_path=args.config,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            warmup_from=args.warmup_from,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
