"""Structural Stop/Take Shadow ctl: keep the live runner on model start."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CTL_PATH = ROOT / "scripts" / "live" / "shadow_structural_protection_ctl.py"
HOST = (ROOT / "scripts" / "btc_ml_host.py").read_text(encoding="utf-8")


def _load_ctl():
    spec = importlib.util.spec_from_file_location("shadow_structural_protection_ctl", CTL_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_model_start_includes_structural_protection_ctl() -> None:
    assert "scripts/live/shadow_structural_protection_ctl.py" in HOST
    assert 'run_ctl(script, "start")' in HOST
    assert "shadow_structural_protection" in HOST


def test_health_path_uses_active_paper_epoch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctl = _load_ctl()
    monkeypatch.setattr(ctl, "REPO", tmp_path)
    epoch = "PER_TF_EQUITY_1PCT_V1_20260802_155305"
    active = tmp_path / "data" / "trading" / "paper_epochs" / "active.json"
    active.parent.mkdir(parents=True)
    active.write_text(json.dumps({"paper_epoch_id": epoch}), encoding="utf-8")
    path = ctl._health_path()
    assert path == (
        tmp_path
        / "data"
        / "trading"
        / "shadow_structural_protection"
        / "epochs"
        / epoch
        / "health.json"
    )


def test_start_keeps_live_pid_and_does_not_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctl = _load_ctl()
    pid_path = tmp_path / "run" / "shadow_structural_protection.pid"
    pid_path.parent.mkdir(parents=True)
    pid_path.write_text("34218\n", encoding="utf-8")
    monkeypatch.setattr(ctl, "PID_PATH", pid_path)
    monkeypatch.setattr(ctl, "_read_pid", lambda: 34218)
    monkeypatch.setattr(ctl, "_alive", lambda pid: pid == 34218)
    monkeypatch.setattr(ctl, "_is_runner", lambda pid: pid == 34218)
    monkeypatch.setattr(ctl, "_runner_pids", lambda: [34218])

    spawned: list[object] = []
    monkeypatch.setattr(ctl.subprocess, "Popen", lambda *a, **k: spawned.append((a, k)) or None)
    monkeypatch.setattr(ctl, "cmd_stop", lambda: (_ for _ in ()).throw(AssertionError("start must not stop a live runner")))

    rc = ctl.cmd_start()
    assert rc == 0
    assert spawned == []
    assert pid_path.read_text(encoding="utf-8").strip() == "34218"


def test_start_adopts_live_runner_when_pid_file_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctl = _load_ctl()
    pid_path = tmp_path / "run" / "shadow_structural_protection.pid"
    pid_path.parent.mkdir(parents=True)
    pid_path.write_text("25660\n", encoding="utf-8")
    monkeypatch.setattr(ctl, "PID_PATH", pid_path)
    monkeypatch.setattr(ctl, "_read_pid", lambda: 25660)
    monkeypatch.setattr(ctl, "_alive", lambda pid: pid == 34218)
    monkeypatch.setattr(ctl, "_is_runner", lambda pid: pid == 34218)
    monkeypatch.setattr(ctl, "_runner_pids", lambda: [34218])

    spawned: list[object] = []
    monkeypatch.setattr(ctl.subprocess, "Popen", lambda *a, **k: spawned.append((a, k)) or None)

    rc = ctl.cmd_start()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert spawned == []
    assert out["status"] == "already_running"
    assert out["pid"] == 34218
    assert out["note"] == "adopted"
    assert out["replaced_stale_pid"] == 25660
    assert pid_path.read_text(encoding="utf-8").strip() == "34218"
