"""LIVE1A cognition ctl: keep the live runner on model start and adopt its PID."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CTL_PATH = ROOT / "scripts" / "live" / "intrabar_cognition_ctl.py"
HOST = (ROOT / "scripts" / "btc_ml_host.py").read_text(encoding="utf-8")


def _load_ctl():
    spec = importlib.util.spec_from_file_location("intrabar_cognition_ctl", CTL_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        journal_root=tmp_path / "journal",
        context_root=tmp_path / "context",
        health_path=tmp_path / "health.json",
        pid_file=tmp_path / "run" / "intrabar_cognition.pid",
        stop_intent_file=tmp_path / "run" / "intrabar_cognition.stop_intent.json",
        controlled_restart_file=tmp_path / "run" / "intrabar_cognition.controlled_restart.json",
        log_file=tmp_path / "logs" / "intrabar_cognition.log",
        symbol="BTCUSDT",
    )


def test_model_start_includes_cognition_ctl() -> None:
    assert "scripts/live/intrabar_cognition_ctl.py" in HOST
    assert 'run_ctl(script, "start")' in HOST


def test_start_keeps_live_pid_and_does_not_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctl = _load_ctl()
    args = _args(tmp_path)
    args.pid_file.parent.mkdir(parents=True)
    args.pid_file.write_text("48873\n", encoding="utf-8")
    monkeypatch.setattr(ctl, "_read_pid", lambda path: 48873)
    monkeypatch.setattr(ctl, "_alive", lambda pid: pid == 48873)
    monkeypatch.setattr(ctl, "_is_runner", lambda pid: pid == 48873)
    monkeypatch.setattr(ctl, "_runner_pids", lambda: [48873])
    monkeypatch.setattr(ctl, "clear_stop_intent", lambda path: None)

    spawned: list[object] = []
    monkeypatch.setattr(ctl.subprocess, "Popen", lambda *a, **k: spawned.append((a, k)) or None)

    rc = ctl.cmd_start(args)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert spawned == []
    assert out["status"] == "already_running"
    assert out["pid"] == 48873
    assert args.pid_file.read_text(encoding="utf-8").strip() == "48873"


def test_start_adopts_live_runner_when_pid_file_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctl = _load_ctl()
    args = _args(tmp_path)
    args.pid_file.parent.mkdir(parents=True)
    args.pid_file.write_text("93313\n", encoding="utf-8")
    monkeypatch.setattr(ctl, "_read_pid", lambda path: 93313)
    monkeypatch.setattr(ctl, "_alive", lambda pid: pid == 48873)
    monkeypatch.setattr(ctl, "_is_runner", lambda pid: pid == 48873)
    monkeypatch.setattr(ctl, "_runner_pids", lambda: [48873])
    monkeypatch.setattr(ctl, "clear_stop_intent", lambda path: None)

    spawned: list[object] = []
    monkeypatch.setattr(ctl.subprocess, "Popen", lambda *a, **k: spawned.append((a, k)) or None)

    rc = ctl.cmd_start(args)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert spawned == []
    assert out["status"] == "already_running"
    assert out["pid"] == 48873
    assert out["note"] == "adopted"
    assert out["replaced_stale_pid"] == 93313
    assert args.pid_file.read_text(encoding="utf-8").strip() == "48873"
