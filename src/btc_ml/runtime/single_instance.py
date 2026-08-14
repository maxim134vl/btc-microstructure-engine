"""Exclusive pid-file lock so a host/VPS cannot run two writers of the same role."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path


class AlreadyRunningError(RuntimeError):
    def __init__(self, path: Path, pid: int | None) -> None:
        self.path = path
        self.pid = pid
        extra = f" pid={pid}" if pid else ""
        super().__init__(f"already running:{path}{extra}")


class InstanceLock:
    """Hold an exclusive flock on ``path`` and write this process pid."""

    def __init__(self, handle: object, path: Path) -> None:
        self._handle = handle
        self.path = path

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if self.path.exists() and self.path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                self.path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            handle.close()
        except OSError:
            pass
        self._handle = None


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, TypeError, ValueError):
        return None


def acquire_pid_lock(path: Path | str) -> InstanceLock:
    """Acquire exclusive lock or raise AlreadyRunningError.

    The returned lock must stay referenced until the process should exit.
    """
    pid_path = Path(path)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    handle = pid_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        existing = _read_pid(pid_path)
        handle.close()
        raise AlreadyRunningError(pid_path, existing) from exc
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    os.fsync(handle.fileno())
    return InstanceLock(handle, pid_path)
