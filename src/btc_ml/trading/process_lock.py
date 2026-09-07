"""PID/lock handling for manager and trader processes (S4.1).

One live process per role. Stale PID files are recovered, live duplicates are
refused so two writers can never share a book.
"""

from __future__ import annotations

import fcntl
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SHARED_LOCKS: dict[str, object] = {}

ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = ROOT / "run"
LOG_DIR = ROOT / "logs"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def paths_for(role: str) -> dict[str, Path]:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "pid": RUN_DIR / f"{role}.pid",
        "lock": RUN_DIR / f"{role}.lock",
        "log": LOG_DIR / f"{role}.log",
    }


def acquire(role: str, *, pid: int | None = None) -> dict[str, Any]:
    targets = paths_for(role)
    own = int(pid or os.getpid())
    for key in ("pid", "lock"):
        existing = _read_pid(targets[key])
        if existing is None:
            continue
        if existing == own:
            continue
        if pid_alive(existing):
            return {
                "acquired": False,
                "reason": "ALREADY_RUNNING",
                "role": role,
                "existing_pid": existing,
            }
        targets[key].unlink(missing_ok=True)
    targets["pid"].write_text(f"{own}\n", encoding="utf-8")
    targets["lock"].write_text(f"{own}\n", encoding="utf-8")
    return {
        "acquired": True,
        "role": role,
        "pid": own,
        "pid_path": str(targets["pid"]),
        "lock_path": str(targets["lock"]),
        "log_path": str(targets["log"]),
        "acquired_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def acquire_shared(path: Path, *, pid: int | None = None) -> dict[str, Any]:
    """Exclusive lock on a shared data-volume file. Survives Docker PID namespaces."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    own = int(pid or os.getpid())
    key = str(target.resolve())
    fh = target.open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return {
            "acquired": False,
            "reason": "ALREADY_RUNNING",
            "path": str(target),
        }
    fh.seek(0)
    fh.truncate()
    fh.write(f"{own}\n")
    fh.flush()
    _SHARED_LOCKS[key] = fh
    return {
        "acquired": True,
        "path": str(target),
        "pid": own,
        "acquired_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def release(role: str, *, pid: int | None = None) -> None:
    targets = paths_for(role)
    own = int(pid or os.getpid())
    for key in ("pid", "lock"):
        if _read_pid(targets[key]) == own:
            targets[key].unlink(missing_ok=True)


def status(role: str) -> dict[str, Any]:
    targets = paths_for(role)
    pid = _read_pid(targets["pid"])
    lock_pid = _read_pid(targets["lock"])
    alive = pid_alive(pid) if pid else False
    return {
        "role": role,
        "pid": pid,
        "lock_pid": lock_pid,
        "alive": alive,
        "stale_pid_file": bool(pid and not alive),
        "log_path": str(targets["log"]),
    }


def log_line(role: str, message: str) -> None:
    targets = paths_for(role)
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with targets["log"].open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} [{role}] {message}\n")
