"""S4.1 timeframe manager ctl is part of the hybrid start/stop stack."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL_PATH = ROOT / "scripts" / "live" / "timeframe_manager_ctl.py"
HOST = (ROOT / "scripts" / "btc_ml_host.py").read_text(encoding="utf-8")
CFG = json.loads((ROOT / "config" / "intrabar_supervision.json").read_text(encoding="utf-8"))


def _load_ctl():
    spec = importlib.util.spec_from_file_location("timeframe_manager_ctl", CTL_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_host_model_start_includes_manager_ctl() -> None:
    assert "scripts/live/timeframe_manager_ctl.py" in HOST
    assert CFG["services"]["timeframe_manager"]["ctl_script"] == "scripts/live/timeframe_manager_ctl.py"
    assert CFG["services"]["timeframe_manager"]["runner_script"] == "scripts/live/timeframe_manager_daemon.py"


def test_start_adopts_live_pid_and_does_not_spawn(tmp_path: Path, monkeypatch, capsys) -> None:
    ctl = _load_ctl()
    monkeypatch.setattr(ctl, "_keep_live_runner", lambda: 13218)
    monkeypatch.setattr(ctl, "_read_pid", lambda: 99999)
    monkeypatch.setattr(ctl, "clear_stop_intent", lambda path: None)
    ctl.PID_PATH = tmp_path / "timeframe_manager.pid"
    spawned: list[object] = []
    monkeypatch.setattr(ctl.subprocess, "Popen", lambda *a, **k: spawned.append((a, k)) or None)
    rc = ctl.cmd_start()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert spawned == []
    assert out["status"] == "already_running"
    assert out["pid"] == 13218
    assert ctl.PID_PATH.read_text(encoding="utf-8").strip() == "13218"
