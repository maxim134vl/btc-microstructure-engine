"""Tests for bounded paper controller duplicate process repair QA."""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "scripts"
    / "research"
    / "audit_bounded_paper_controller_duplicate_process_repair_qa.py"
)
RESEARCH = ROOT / "data" / "research" / "paper_simulator"
CTL = ROOT / "scripts" / "bounded_paper_trading_controller_ctl.sh"
CTRL = (
    ROOT
    / "scripts"
    / "live"
    / "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
)

spec = importlib.util.spec_from_file_location(
    "audit_bounded_paper_controller_duplicate_process_repair_qa", AUDIT_PATH
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["audit_bounded_paper_controller_duplicate_process_repair_qa"] = mod
spec.loader.exec_module(mod)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)


def test_01_no_forbidden_imports():
    tree = ast.parse(AUDIT_PATH.read_text(encoding="utf-8"))
    forbidden = {"ccxt", "binance", "bybit", "exchange_api", "broker"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden


def test_02_ctl_has_repair_and_lock():
    text = CTL.read_text(encoding="utf-8")
    assert "repair-duplicates" in text
    assert "LOCK_FILE" in text
    assert "cleanup_stale_lock" in text
    assert "second start blocked" in text


def test_03_controller_has_lock_helpers():
    text = CTRL.read_text(encoding="utf-8")
    assert "acquire_controller_lock" in text
    assert "LOCK_PATH" in text
    assert "ACTIVE_CONTROLLER_ALREADY_RUNNING" in text


def test_04_pass_path(tmp_path: Path, monkeypatch):
    research = tmp_path / "data/research/paper_simulator"
    run = tmp_path / "run"
    scripts = tmp_path / "scripts"
    live_scripts = scripts / "live"
    docs = tmp_path / "docs"
    for d in (research, run, live_scripts, docs):
        d.mkdir(parents=True)

    for name in [
        "paper_signals.parquet",
        "paper_orders.parquet",
        "paper_events.parquet",
        "paper_trades.parquet",
        "paper_positions.parquet",
        "paper_equity_curve.parquet",
        "paper_risk_blocks.parquet",
        "bounded_paper_controller_status.json",
        "bounded_paper_controller_safety.json",
        "bounded_paper_controller_runtime_stability_qa_final_decision.json",
    ]:
        _copy(RESEARCH / name, research / name)

    (run / "bounded_paper_trading_controller_auto_ledger.pid").write_text(
        "19160\n", encoding="utf-8"
    )
    (run / "bounded_paper_trading_controller_auto_ledger.lock").write_text(
        "19160\n", encoding="utf-8"
    )
    _copy(CTL, scripts / "bounded_paper_trading_controller_ctl.sh")
    _copy(CTRL, live_scripts / CTRL.name)

    monkeypatch.setattr(mod, "list_controller_pids", lambda: [19160])
    monkeypatch.setattr(
        mod, "pid_alive", lambda pid: pid == 19160
    )

    rc = mod.main(
        [
            "--root",
            str(tmp_path),
            "--expected-canonical-pid",
            "19160",
            "--expected-duplicate-pids-before",
            "18118",
        ]
    )
    assert rc == 0
    final = json.loads(
        (
            research
            / "bounded_paper_controller_duplicate_process_repair_final_decision.json"
        ).read_text()
    )
    assert final["status"] == "BOUNDED_PAPER_CONTROLLER_DUPLICATE_PROCESS_REPAIR_DONE"
    assert final["qa_status"] == "PASS_WITH_LIMITATIONS"
    assert final["single_process_verified"] is True
    assert final["canonical_pid"] == 19160
    assert final["duplicate_process_count_after"] == 0
    assert final["lock_file_created"] is True
    assert final["paper_ledger_write_performed"] is False
    assert (
        final["run_readiness_status"]
        == "CONTROLLER_SINGLE_PROCESS_REPAIRED_COLLECTING_PAPER_DATA"
    )
    assert final["next_recommended_step"] == "OBSERVE_NEXT_CONTROLLER_CYCLE"


def test_05_fail_if_duplicate_still_alive(tmp_path: Path, monkeypatch):
    research = tmp_path / "data/research/paper_simulator"
    run = tmp_path / "run"
    scripts = tmp_path / "scripts"
    live_scripts = scripts / "live"
    docs = tmp_path / "docs"
    for d in (research, run, live_scripts, docs):
        d.mkdir(parents=True)
    for name in [
        "paper_signals.parquet",
        "paper_orders.parquet",
        "paper_events.parquet",
        "paper_trades.parquet",
        "paper_positions.parquet",
        "paper_equity_curve.parquet",
        "paper_risk_blocks.parquet",
        "bounded_paper_controller_status.json",
        "bounded_paper_controller_safety.json",
        "bounded_paper_controller_runtime_stability_qa_final_decision.json",
    ]:
        _copy(RESEARCH / name, research / name)
    (run / "bounded_paper_trading_controller_auto_ledger.pid").write_text(
        "19160\n", encoding="utf-8"
    )
    (run / "bounded_paper_trading_controller_auto_ledger.lock").write_text(
        "19160\n", encoding="utf-8"
    )
    _copy(CTL, scripts / "bounded_paper_trading_controller_ctl.sh")
    _copy(CTRL, live_scripts / CTRL.name)
    monkeypatch.setattr(mod, "list_controller_pids", lambda: [18118, 19160])
    monkeypatch.setattr(mod, "pid_alive", lambda pid: pid in {18118, 19160})
    rc = mod.main(
        [
            "--root",
            str(tmp_path),
            "--expected-canonical-pid",
            "19160",
            "--expected-duplicate-pids-before",
            "18118",
        ]
    )
    assert rc == 1
    final = json.loads(
        (
            research
            / "bounded_paper_controller_duplicate_process_repair_final_decision.json"
        ).read_text()
    )
    assert final["status"] == "BOUNDED_PAPER_CONTROLLER_DUPLICATE_PROCESS_REPAIR_FAIL"
    assert final["single_process_verified"] is False
