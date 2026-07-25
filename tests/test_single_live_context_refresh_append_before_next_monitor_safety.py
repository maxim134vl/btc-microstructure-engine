"""Tests for single live refresh append before-next-monitor safety audit."""

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
    / "audit_single_live_context_refresh_append_before_next_monitor_safety.py"
)
RESEARCH = ROOT / "data" / "research" / "paper_simulator"
LIVE = ROOT / "data" / "live"
COGNITION = ROOT / "data" / "cognition"

spec = importlib.util.spec_from_file_location(
    "audit_single_live_context_refresh_append_before_next_monitor_safety", AUDIT_PATH
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["audit_single_live_context_refresh_append_before_next_monitor_safety"] = mod
spec.loader.exec_module(mod)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)


def _seed(tmp_path: Path, *, refresh_ok: bool = True) -> Path:
    research = tmp_path / "data" / "research" / "paper_simulator"
    live = tmp_path / "data" / "live"
    cognition = tmp_path / "data" / "cognition"
    scripts_live = tmp_path / "scripts" / "live"
    docs = tmp_path / "docs"
    for d in (research, live, cognition, scripts_live, docs):
        d.mkdir(parents=True)

    for name in (
        "paper_position_monitor_dry_run_qa_final_decision.json",
        "single_live_refresh_append_final_decision.json",
        "single_live_refresh_append_append_result.json",
        "single_live_refresh_append_refresh_result.json",
        "single_live_refresh_append_before_snapshot.json",
        "single_live_refresh_append_no_paper_signal_check.json",
        "single_live_refresh_append_no_write_safety.json",
        "paper_signals.parquet",
        *mod.EXPECTED_LEDGER_COUNTS.keys(),
    ):
        # EXPECTED includes paper_signals twice potentially - unique via set of names above
        src = RESEARCH / name
        if src.exists():
            _copy(src, research / name)

    if not refresh_ok:
        final = json.loads(
            (research / "single_live_refresh_append_final_decision.json").read_text()
        )
        final["status"] = "FAIL"
        (research / "single_live_refresh_append_final_decision.json").write_text(
            json.dumps(final, indent=2) + "\n", encoding="utf-8"
        )

    _copy(LIVE / "live_market_feed.parquet", live / "live_market_feed.parquet")
    _copy(LIVE / "context_decision_log.parquet", live / "context_decision_log.parquet")
    for name in (
        "final_market_context_memory.parquet",
        "market_context_lifecycle_memory.parquet",
    ):
        _copy(COGNITION / name, cognition / name)
    _copy(
        ROOT
        / "scripts"
        / "live"
        / "single_live_context_refresh_and_decision_log_append_no_paper_signal.py",
        scripts_live
        / "single_live_context_refresh_and_decision_log_append_no_paper_signal.py",
    )
    return tmp_path


def test_01_invalid_refresh_blocks(tmp_path: Path):
    root = _seed(tmp_path, refresh_ok=False)
    assert mod.main(["--root", str(root)]) == 2


def test_02_safety_pass_and_no_ledger_mutation(tmp_path: Path):
    root = _seed(tmp_path)
    research = root / "data/research/paper_simulator"
    log = root / "data/live/context_decision_log.parquet"
    positions = research / "paper_positions.parquet"
    before_log = log.read_bytes()
    before_pos = positions.read_bytes()
    assert mod.main(["--root", str(root)]) == 0
    assert log.read_bytes() == before_log
    assert positions.read_bytes() == before_pos

    inputs = json.loads(
        (
            research
            / "single_live_context_refresh_append_before_next_monitor_input.json"
        ).read_text()
    )
    assert inputs["approval_verified"] is True
    assert inputs["prior_monitor_qa_found"] is True
    assert inputs["prior_context_freshness_warning_found"] is True
    assert inputs["live_feed_found"] is True
    assert inputs["context_decision_log_found"] is True
    assert inputs["paper_ledgers_found"] is True
    assert inputs["input_validation_status"] == "VALID"

    ba = json.loads(
        (
            research
            / "single_live_context_refresh_append_before_next_monitor_before_after.json"
        ).read_text()
    )
    assert ba["refresh_performed"] is True
    assert ba["decision_log_append_performed"] is True
    assert ba["appended_rows_count"] == 1
    assert ba["latest_decision_log_ts_before"] == "2026-07-21T06:45:00Z"
    assert ba["latest_decision_log_ts_after"] == "2026-07-21T08:30:00Z"
    assert ba["latest_context_after"] == "LONG_CONTEXT"
    assert ba["latest_lifecycle_state_after"] == "CHALLENGED"
    assert ba["latest_stale_flag_after"] is False

    ledger = json.loads(
        (
            research
            / "single_live_context_refresh_append_before_next_monitor_paper_ledger_safety.json"
        ).read_text()
    )
    assert ledger["paper_ledger_safety_status"] == "PASS"
    assert ledger["paper_signals_before"] == 1
    assert ledger["paper_signals_after"] == 1
    assert ledger["paper_orders_before"] == 3
    assert ledger["paper_orders_after"] == 3
    assert ledger["paper_events_before"] == 3
    assert ledger["paper_events_after"] == 3
    assert ledger["paper_trades_before"] == 3
    assert ledger["paper_trades_after"] == 3
    assert ledger["paper_positions_before"] == 3
    assert ledger["paper_positions_after"] == 3
    assert ledger["paper_equity_rows_before"] == 3
    assert ledger["paper_equity_rows_after"] == 3
    assert ledger["paper_risk_blocks_before"] == 0
    assert ledger["paper_risk_blocks_after"] == 0
    assert ledger["paper_ledger_write_performed"] is False

    final = json.loads(
        (
            research
            / "single_live_context_refresh_append_before_next_monitor_final_decision.json"
        ).read_text()
    )
    assert (
        final["status"]
        == "SINGLE_LIVE_CONTEXT_REFRESH_APPEND_BEFORE_NEXT_MONITOR_DONE_WITH_LIMITATIONS"
    )
    assert final["qa_status"] == "PASS_WITH_LIMITATIONS"
    assert final["approval_verified"] is True
    assert final["decision_log_append_performed"] is True
    assert final["appended_rows_count"] == 1
    assert final["latest_context_after"] == "LONG_CONTEXT"
    assert final["latest_lifecycle_state_after"] == "CHALLENGED"
    assert final["latest_stale_flag_after"] is False
    assert final["paper_ledger_write_performed"] is False
    assert final["execution_enabled"] is False
    assert final["paper_trading_loop_started"] is False
    assert (
        final["run_readiness_status"]
        == "READY_FOR_PAPER_POSITION_MONITOR_AFTER_REFRESH_DRY_RUN_NO_LEDGER_NO_EXECUTION"
    )
    assert (
        final["next_recommended_step"]
        == "PAPER_POSITION_MONITOR_AFTER_REFRESH_DRY_RUN_NO_LEDGER_NO_EXECUTION"
    )


def test_03_no_forbidden_imports_or_fit_calls():
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
