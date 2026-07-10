"""Tests for persistent engine worker execution mode."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _reset_worker_pool():
    import runtime_engine_guard as guard

    guard.reset_worker_pool_for_tests()
    yield
    guard.reset_worker_pool_for_tests()


@pytest.fixture()
def worker_env(tmp_path, monkeypatch):
    import runtime_config
    import runtime_engine_guard as guard

    audit_path = tmp_path / "engine_worker_audit.jsonl"
    monkeypatch.setattr(runtime_config, "ENGINE_WORKER_AUDIT_PATH", str(audit_path))
    monkeypatch.setattr(guard, "ENGINE_WORKER_AUDIT_PATH", str(audit_path))
    monkeypatch.setenv("BTC_ML_ENGINE_EXECUTION_MODE", "persistent_worker")
    return tmp_path, audit_path


def _write_engine(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def _read_audit(audit_path: Path) -> list[dict]:
    if not audit_path.exists():
        return []
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_successful_engine_execution_through_worker(worker_env) -> None:
    tmp_path, audit_path = worker_env
    import runtime_engine_guard as guard

    script = _write_engine(
        tmp_path,
        "ok_engine.py",
        "import sys\nsys.exit(0)\n",
    )
    returncode = guard.run_engine_subprocess(
        sys.executable,
        script,
        str(tmp_path),
        "ok_engine_v1.py",
        timeout_seconds=10,
        cycle_id=7,
    )
    assert returncode == 0
    rows = _read_audit(audit_path)
    assert rows
    assert rows[-1]["status"] == "ok"
    assert rows[-1]["mode"] == "persistent_worker"
    assert rows[-1]["cycle_id"] == 7


def test_failing_engine_does_not_kill_parent(worker_env) -> None:
    tmp_path, audit_path = worker_env
    import runtime_engine_guard as guard

    script = _write_engine(
        tmp_path,
        "fail_engine.py",
        "import sys\nsys.exit(3)\n",
    )
    with pytest.raises(RuntimeError, match="ENGINE FAILED"):
        guard.run_engine_subprocess(
            sys.executable,
            script,
            str(tmp_path),
            "fail_engine_v1.py",
            timeout_seconds=10,
        )
    rows = _read_audit(audit_path)
    assert rows[-1]["status"] == "error"
    assert rows[-1]["returncode"] == 3


def test_timeout_kills_and_restarts_worker(worker_env, monkeypatch) -> None:
    tmp_path, audit_path = worker_env
    import runtime_engine_guard as guard

    monkeypatch.setattr(guard, "ENGINE_KILL_GRACE_SECONDS", 1)
    script = _write_engine(
        tmp_path,
        "slow_engine.py",
        "import time\ntime.sleep(30)\n",
    )
    with pytest.raises(guard.EngineTimeoutError):
        guard.run_engine_subprocess(
            sys.executable,
            script,
            str(tmp_path),
            "slow_engine_v1.py",
            timeout_seconds=1,
        )

    ok_script = _write_engine(
        tmp_path,
        "ok_after_timeout.py",
        "import sys\nsys.exit(0)\n",
    )
    returncode = guard.run_engine_subprocess(
        sys.executable,
        ok_script,
        str(tmp_path),
        "ok_after_timeout_v1.py",
        timeout_seconds=10,
    )
    assert returncode == 0
    rows = _read_audit(audit_path)
    timeout_rows = [row for row in rows if row.get("status") == "timeout"]
    assert timeout_rows
    assert any(row.get("recycled") for row in rows)


def test_recycle_after_max_jobs(worker_env, monkeypatch) -> None:
    tmp_path, audit_path = worker_env
    import runtime_config
    import runtime_engine_guard as guard

    monkeypatch.setattr(runtime_config, "ENGINE_WORKER_MAX_JOBS", 2)
    monkeypatch.setattr(guard, "ENGINE_WORKER_MAX_JOBS", 2)

    script = _write_engine(
        tmp_path,
        "tiny_engine.py",
        "import sys\nsys.exit(0)\n",
    )
    for idx in range(3):
        guard.run_engine_subprocess(
            sys.executable,
            script,
            str(tmp_path),
            f"tiny_engine_{idx}.py",
            timeout_seconds=10,
        )

    rows = _read_audit(audit_path)
    recycle_rows = [row for row in rows if row.get("recycled")]
    assert recycle_rows


def test_fallback_subprocess_mode_still_works(tmp_path, monkeypatch) -> None:
    import runtime_config
    import runtime_engine_guard as guard

    audit_path = tmp_path / "subprocess_audit.jsonl"
    monkeypatch.setattr(runtime_config, "ENGINE_WORKER_AUDIT_PATH", str(audit_path))
    monkeypatch.setattr(guard, "ENGINE_WORKER_AUDIT_PATH", str(audit_path))
    monkeypatch.setenv("BTC_ML_ENGINE_EXECUTION_MODE", "subprocess")

    script = _write_engine(
        tmp_path,
        "subprocess_ok.py",
        "import sys\nsys.exit(0)\n",
    )
    returncode = guard.run_engine_subprocess(
        sys.executable,
        script,
        str(tmp_path),
        "subprocess_ok_v1.py",
        timeout_seconds=10,
    )
    assert returncode == 0
    rows = _read_audit(audit_path)
    assert rows[-1]["mode"] == "subprocess"
