#!/usr/bin/env python3
"""Stability gate + survival check unit tests (mocked / static)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SURVIVAL = ROOT / "scripts/research/check_intrabar_feed_daemon_survival.py"
GATE = ROOT / "scripts/research/run_intrabar_feed_stability_gate.py"
CTL = ROOT / "scripts/intrabar_feed_ctl.sh"
FEED = ROOT / "scripts/live/live_binance_intrabar_feed.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_survival_script_exists_and_writes_outputs():
    text = SURVIVAL.read_text(encoding="utf-8")
    assert "POST_SHELL_WAIT_SECONDS = 90" in text
    assert "intrabar_feed_daemon_survival_check.json" in text
    assert "INTRABAR_FEED_DAEMON_SURVIVAL_CHECK.md" in text
    assert "make" in text and "intrabar-feed-restart" in text


def test_stability_gate_includes_post_shell_survival():
    text = GATE.read_text(encoding="utf-8")
    assert "post_shell_wait" in text
    assert "parent_shell_exited" in text
    assert "APPROVE_START_PAPER_CONTROLLER_WITH_STABLE_INTRABAR_FEED_NO_REAL_EXECUTION" in text


def test_post_shell_survival_check_passes_with_mocked_process(tmp_path, monkeypatch):
    mod = _load(SURVIVAL, "check_intrabar_feed_daemon_survival")

    class CP:
        def __init__(self, stdout: str, returncode: int = 0):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    status_running = (
        "status=RUNNING\n"
        "pid_file_pid=12345\n"
        "pid_file_alive=true\n"
        "rows=20\n"
        "latest_observed_at_utc=2026-07-21T18:00:00.000000Z\n"
        "seconds_since_latest_row=10\n"
        "duplicate_count=0\n"
        "orphan_count=0\n"
    )
    health_pass = "healthcheck=PASS\nhealth_duplicate_count=0\nhealth_orphan_count=0\n"
    controller_stopped = "status=STOPPED\nlive_controller_count=0\n"

    def fake_run(cmd, **kwargs):
        joined = " ".join(cmd)
        if "intrabar-feed-restart" in joined:
            return CP("restart ok\n", 0)
        if "healthcheck" in joined:
            return CP(health_pass, 0)
        if "bounded_paper" in joined:
            return CP(controller_stopped, 0)
        if "status" in joined:
            return CP(status_running, 0)
        return CP("", 0)

    monkeypatch.setattr(mod, "_run", fake_run)
    monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "OUT_JSON", tmp_path / "surv.json")
    monkeypatch.setattr(mod, "OUT_MD", tmp_path / "surv.md")

    payload = mod.run_check(wait_seconds=1)
    mod.write_outputs(payload)
    assert payload["result"] == "PASS"
    assert payload["pid_alive_after_shell_exit"] is True
    assert payload["rows_fresh_after_shell_exit"] is True
    assert payload["duplicate_count"] == 0
    assert payload["orphan_count"] == 0
    assert payload["paper_controller_running"] is False
    assert (tmp_path / "surv.json").exists()


def test_paper_controller_remains_stopped_contract():
    for path in (SURVIVAL, GATE):
        text = path.read_text(encoding="utf-8")
        assert "paper_controller_started" in text
        assert "False" in text or "false" in text


def test_no_exchange_order_api_in_feed():
    text = FEED.read_text(encoding="utf-8")
    assert "api/v3/order" not in text
    assert "execution_enabled" in text
    assert "False" in text
    assert "paper_only" in text.lower() or "paper_only" in text


def test_no_paper_ledger_writes_in_gate_and_survival():
    for path in (SURVIVAL, GATE, CTL):
        text = path.read_text(encoding="utf-8")
        assert "paper_ledger" not in text or "paper_ledger_write\": False" in text or "paper_ledger_write: false" in text
