"""Tests for bounded paper controller runtime stability QA (read-only)."""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "scripts"
    / "research"
    / "audit_bounded_paper_controller_runtime_stability_qa.py"
)
RESEARCH = ROOT / "data" / "research" / "paper_simulator"
LIVE_LOG = ROOT / "logs" / "bounded_paper_trading_controller_auto_ledger.log"

spec = importlib.util.spec_from_file_location(
    "audit_bounded_paper_controller_runtime_stability_qa", AUDIT_PATH
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["audit_bounded_paper_controller_runtime_stability_qa"] = mod
spec.loader.exec_module(mod)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)


def test_01_no_forbidden_imports_or_fit_calls():
    tree = ast.parse(AUDIT_PATH.read_text(encoding="utf-8"))
    forbidden = {"ccxt", "binance", "bybit", "exchange_api", "broker"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            assert name.lower() not in {"fit", "retrain", "train_model"}


def test_02_classify_death_detach_issue():
    log = """
2026-07-21T09:29:20.471766Z controller_start pid=16064 max_cycles=96
2026-07-21T09:29:20.471766Z cycle=1 status=OK action=OBSERVE_NO_TRADE
2026-07-21T09:31:53.733396Z controller_start pid=17074 max_cycles=1
2026-07-21T09:32:14.616824Z cycle=1 status=OK action=CLOSE_POSITION
2026-07-21T09:32:14.650918Z controller_stop reason=ONE_CYCLE
2026-07-21T09:32:46.589111Z controller_start pid=17392 max_cycles=96
2026-07-21T09:32:51.560180Z cycle=1 status=OK action=OBSERVE_NO_TRADE
2026-07-21T09:34:36.739139Z controller_start pid=18118 max_cycles=96
2026-07-21T09:37:44.522374Z controller_start pid=19160 max_cycles=96
""".strip()
    events = mod.parse_log_events(log)
    death = mod.classify_death(events, current_pids=[18118, 19160])
    assert death["prior_process_died"] is True
    assert death["death_cause_classification"] == "PID_DETACH_ISSUE"
    assert death["restart_detected"] is True
    assert death["detach_launcher_used"] is True


def test_03_classify_crash_exception():
    log = """
2026-07-21T09:00:00.000000Z controller_start pid=1 max_cycles=96
2026-07-21T09:00:01.000000Z cycle_error=boom
2026-07-21T09:00:01.000000Z Traceback (most recent call last):
""".strip()
    events = mod.parse_log_events(log)
    death = mod.classify_death(events, current_pids=[])
    assert death["death_cause_classification"] == "CRASH_EXCEPTION"


def test_04_ledger_closed_position(tmp_path: Path):
    research = tmp_path / "data/research/paper_simulator"
    research.mkdir(parents=True)
    _copy(RESEARCH / "paper_positions.parquet", research / "paper_positions.parquet")
    _copy(RESEARCH / "paper_trades.parquet", research / "paper_trades.parquet")
    out = mod.check_ledger(tmp_path)
    assert out["closed_position_verified"] is True
    assert out["open_position_count"] == 0
    assert out["duplicate_close_rows"] == 0
    assert out["ledger_consistency_status"] == "PASS"


def test_05_latest_cycle_observe_no_trade(tmp_path: Path):
    research = tmp_path / "data/research/paper_simulator"
    research.mkdir(parents=True)
    status = {
        "controller_running": True,
        "interval_seconds": 900,
        "execution_enabled": False,
        "exchange_api_call_used": False,
        "paper_only_mode": True,
        "last_cycle": {
            "cycle_id": "CYCLE_0001_TEST",
            "cycle_ts": "2026-07-21T09:37:44.719795Z",
            "cycle_status": "OK",
            "action_taken": "OBSERVE_NO_TRADE",
            "position_state_before": "FLAT",
            "latest_context": "OBSERVE",
            "latest_lifecycle_state": "NO_ACTIVE_CONTEXT",
            "new_trade_written": False,
        },
    }
    (research / "bounded_paper_controller_status.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    # empty cycles parquet optional
    out = mod.check_latest_cycle(tmp_path)
    assert out["ok"] is True
    assert out["latest_action"] == "OBSERVE_NO_TRADE"
    assert out["position_state_before"] == "FLAT"
    assert out["context"] == "OBSERVE"
    assert out["lifecycle_state"] == "NO_ACTIVE_CONTEXT"
    assert out["new_trade_opened"] is False


def test_06_audit_does_not_mutate_protected_artifacts(tmp_path: Path, monkeypatch):
    # Minimal seed for full main(); mock process listing to single alive pid.
    research = tmp_path / "data/research/paper_simulator"
    logs = tmp_path / "logs"
    run = tmp_path / "run"
    scripts = tmp_path / "scripts"
    docs = tmp_path / "docs"
    for d in (research, logs, run, scripts, docs):
        d.mkdir(parents=True)

    for name in (
        "bounded_paper_controller_status.json",
        "bounded_paper_controller_safety.json",
        "bounded_paper_controller_cycles.parquet",
        "paper_positions.parquet",
        "paper_trades.parquet",
    ):
        _copy(RESEARCH / name, research / name)

    status = json.loads(
        (research / "bounded_paper_controller_status.json").read_text()
    )
    status["last_cycle"] = {
        "cycle_id": "CYCLE_0001_TEST",
        "cycle_ts": "2026-07-21T09:37:44.719795Z",
        "cycle_status": "OK",
        "action_taken": "OBSERVE_NO_TRADE",
        "position_state_before": "FLAT",
        "latest_context": "OBSERVE",
        "latest_lifecycle_state": "NO_ACTIVE_CONTEXT",
        "new_trade_written": False,
    }
    status["execution_enabled"] = False
    status["exchange_api_call_used"] = False
    status["paper_only_mode"] = True
    status["controller_running"] = True
    status["interval_seconds"] = 900
    (research / "bounded_paper_controller_status.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )

    safety = {
        "paper_only_mode": True,
        "exchange_api_call_used": False,
        "execution_enabled": False,
        "real_order_routing_enabled": False,
        "dashboard_started": False,
        "model_fit_used": False,
        "retraining_used": False,
        "bounded_loop": True,
        "safety_status": "PASS",
    }
    (research / "bounded_paper_controller_safety.json").write_text(
        json.dumps(safety, indent=2) + "\n", encoding="utf-8"
    )

    (run / "bounded_paper_trading_controller_auto_ledger.pid").write_text(
        "424242\n", encoding="utf-8"
    )
    log = LIVE_LOG.read_text(encoding="utf-8") if LIVE_LOG.exists() else (
        "2026-07-21T09:29:20.471766Z controller_start pid=16064\n"
        "2026-07-21T09:37:44.522374Z controller_start pid=424242\n"
        "2026-07-21T09:37:54.121940Z cycle=1 status=OK action=OBSERVE_NO_TRADE\n"
    )
    (logs / "bounded_paper_trading_controller_auto_ledger.log").write_text(
        log, encoding="utf-8"
    )
    (scripts / "bounded_paper_trading_controller_ctl.sh").write_text(
        "start_new_session=True\n", encoding="utf-8"
    )

    monkeypatch.setattr(mod, "pid_alive", lambda pid: pid == 424242)
    monkeypatch.setattr(mod, "list_controller_pids", lambda: [424242])

    before_pos = (research / "paper_positions.parquet").read_bytes()
    before_pid = (run / "bounded_paper_trading_controller_auto_ledger.pid").read_text()
    rc = mod.main(["--root", str(tmp_path)])
    assert rc == 0
    assert (research / "paper_positions.parquet").read_bytes() == before_pos
    assert (
        run / "bounded_paper_trading_controller_auto_ledger.pid"
    ).read_text() == before_pid
    final = json.loads(
        (
            research
            / "bounded_paper_controller_runtime_stability_qa_final_decision.json"
        ).read_text()
    )
    assert (
        final["qa_decision"]
        == "BOUNDED_PAPER_CONTROLLER_RUNTIME_STABILITY_QA_PASS_WITH_PRIOR_RESTART_NOTE"
    )
    assert final["next_recommended_step"] == "OBSERVE_NEXT_CONTROLLER_CYCLE"


def test_07_duplicate_process_fails(tmp_path: Path, monkeypatch):
    research = tmp_path / "data/research/paper_simulator"
    logs = tmp_path / "logs"
    run = tmp_path / "run"
    scripts = tmp_path / "scripts"
    docs = tmp_path / "docs"
    for d in (research, logs, run, scripts, docs):
        d.mkdir(parents=True)
    for name in (
        "bounded_paper_controller_status.json",
        "bounded_paper_controller_safety.json",
        "bounded_paper_controller_cycles.parquet",
        "paper_positions.parquet",
        "paper_trades.parquet",
    ):
        _copy(RESEARCH / name, research / name)
    status = json.loads(
        (research / "bounded_paper_controller_status.json").read_text()
    )
    status["last_cycle"] = {
        "cycle_id": "CYCLE_0001_TEST",
        "cycle_ts": "2026-07-21T09:37:44.719795Z",
        "cycle_status": "OK",
        "action_taken": "OBSERVE_NO_TRADE",
        "position_state_before": "FLAT",
        "latest_context": "OBSERVE",
        "latest_lifecycle_state": "NO_ACTIVE_CONTEXT",
        "new_trade_written": False,
    }
    status["execution_enabled"] = False
    status["exchange_api_call_used"] = False
    status["paper_only_mode"] = True
    (research / "bounded_paper_controller_status.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    (research / "bounded_paper_controller_safety.json").write_text(
        json.dumps(
            {
                "paper_only_mode": True,
                "exchange_api_call_used": False,
                "execution_enabled": False,
                "real_order_routing_enabled": False,
                "dashboard_started": False,
                "model_fit_used": False,
                "retraining_used": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "bounded_paper_trading_controller_auto_ledger.pid").write_text(
        "19160\n", encoding="utf-8"
    )
    (logs / "bounded_paper_trading_controller_auto_ledger.log").write_text(
        "2026-07-21T09:34:36.739139Z controller_start pid=18118\n"
        "2026-07-21T09:37:44.522374Z controller_start pid=19160\n",
        encoding="utf-8",
    )
    (scripts / "bounded_paper_trading_controller_ctl.sh").write_text(
        "start_new_session=True\n", encoding="utf-8"
    )
    monkeypatch.setattr(mod, "pid_alive", lambda pid: pid in {18118, 19160})
    monkeypatch.setattr(mod, "list_controller_pids", lambda: [18118, 19160])
    rc = mod.main(["--root", str(tmp_path)])
    assert rc == 1
    final = json.loads(
        (
            research
            / "bounded_paper_controller_runtime_stability_qa_final_decision.json"
        ).read_text()
    )
    assert (
        final["qa_decision"]
        == "BOUNDED_PAPER_CONTROLLER_RUNTIME_STABILITY_QA_FAIL_REPAIR_REQUIRED"
    )
    assert final["next_recommended_step"] == "FIX_CONTROLLER_DETACH_OR_SUPERVISOR"
    assert final["single_process_verified"] is False
    assert final["duplicate_process_count"] == 1
