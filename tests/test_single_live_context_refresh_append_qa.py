"""Tests for single live context refresh append QA audit (read-only)."""

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
    ROOT / "scripts" / "research" / "audit_single_live_context_refresh_append_qa.py"
)
RESEARCH = ROOT / "data" / "research" / "paper_simulator"
LIVE = ROOT / "data" / "live"
COGNITION = ROOT / "data" / "cognition"

spec = importlib.util.spec_from_file_location(
    "audit_single_live_context_refresh_append_qa", AUDIT_PATH
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["audit_single_live_context_refresh_append_qa"] = mod
spec.loader.exec_module(mod)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)


def _seed(tmp_path: Path, *, with_final: bool = True, bad_status: bool = False) -> Path:
    research = tmp_path / "data" / "research" / "paper_simulator"
    live = tmp_path / "data" / "live"
    cognition = tmp_path / "data" / "cognition"
    scripts_live = tmp_path / "scripts" / "live"
    docs = tmp_path / "docs"
    for d in (research, live, cognition, scripts_live, docs):
        d.mkdir(parents=True)

    for name in (
        "single_live_refresh_append_final_decision.json",
        "single_live_refresh_append_before_snapshot.json",
        "single_live_refresh_append_append_result.json",
        "single_live_refresh_append_status.json",
        "bounded_watcher_diagnosis_correction_final_decision.json",
        "live_policy_signal_candidate_cycle_qa_final_decision.json",
        "visual_trade_panel_qa_final_decision.json",
        *mod.LEDGER_NAMES,
    ):
        _copy(RESEARCH / name, research / name)

    for name in ("context_decision_log.parquet", "live_market_feed.parquet"):
        _copy(LIVE / name, live / name)

    for name in (
        "final_market_context_memory.parquet",
        "market_context_lifecycle_memory.parquet",
        "market_context_lifecycle_episodes.parquet",
        "auction_episode_memory.parquet",
        "cognitive_market_state_memory.parquet",
    ):
        _copy(COGNITION / name, cognition / name)

    for name in (
        "append_context_decision_log.py",
        "single_live_context_refresh_and_decision_log_append_no_paper_signal.py",
        "paper_policy_engine.py",
        "paper_policy_signal_adapter.py",
        "bounded_live_policy_signal_watcher_no_write.py",
    ):
        src = ROOT / "scripts" / "live" / name
        if src.exists():
            _copy(src, scripts_live / name)
        else:
            (scripts_live / name).write_text("# stub\n", encoding="utf-8")

    if not with_final:
        (research / "single_live_refresh_append_final_decision.json").unlink(
            missing_ok=True
        )
    elif bad_status:
        final = json.loads(
            (research / "single_live_refresh_append_final_decision.json").read_text()
        )
        final["status"] = "FAIL"
        (research / "single_live_refresh_append_final_decision.json").write_text(
            json.dumps(final, indent=2) + "\n", encoding="utf-8"
        )
    return tmp_path


def test_missing_one_shot_final_blocks(tmp_path: Path):
    root = _seed(tmp_path, with_final=False)
    assert mod.main(["--root", str(root)]) == 2


def test_bad_one_shot_status_blocks(tmp_path: Path):
    root = _seed(tmp_path, bad_status=True)
    assert mod.main(["--root", str(root)]) == 2


def test_append_and_latest_row(tmp_path: Path):
    root = _seed(tmp_path)
    assert mod.main(["--root", str(root)]) == 0
    research = root / "data/research/paper_simulator"
    ba = json.loads(
        (
            research / "single_live_context_refresh_append_qa_before_after_check.json"
        ).read_text()
    )
    assert ba["previous_decision_log_rows"] == 10
    assert ba["current_decision_log_rows"] == 11
    assert ba["appended_rows_count"] == 1
    assert ba["previous_decision_log_hash"] == (
        "4a3f2c6a2c6ba3dd4da393227abf310fd56b900ca63368e81fcb9e368fbb11e4"
    )
    assert ba["current_decision_log_hash"] == (
        "b2aa2f936f5c45f8a063686a330a3a0dec43aa2ad593ec2f416fae4e16618ba5"
    )
    latest = json.loads(
        (
            research / "single_live_context_refresh_append_qa_latest_row_check.json"
        ).read_text()
    )
    assert latest["latest_decision_log_ts"] == "2026-07-21T07:00:00Z"
    assert latest["latest_context"] == "LONG_CONTEXT"
    assert latest["latest_lifecycle_state"] == "CHALLENGED"
    assert latest["latest_stale_flag"] is False
    assert latest["latest_source_context_ts"] == "2026-07-21T06:45:00Z"


def test_timestamp_semantics_expected_next_bar(tmp_path: Path):
    root = _seed(tmp_path)
    mod.main(["--root", str(root)])
    ts = json.loads(
        (
            root
            / "data/research/paper_simulator/single_live_context_refresh_append_qa_timestamp_check.json"
        ).read_text()
    )
    assert ts["decision_ts_minus_source_context_minutes"] == 15
    assert ts["timestamp_semantics_status"] == "PASS_EXPECTED_NEXT_BAR_DECISION_TS"
    assert ts["timestamp_mismatch_found"] is False
    assert ts["candidate_cycle_timestamp_safe"] is True
    assert ts["classification"] == "EXPECTED_NEXT_BAR_DECISION_TS"


def test_no_write_and_final(tmp_path: Path):
    root = _seed(tmp_path)
    log = root / "data/live/context_decision_log.parquet"
    before = log.read_bytes()
    assert mod.main(["--root", str(root)]) == 0
    assert log.read_bytes() == before
    final = json.loads(
        (
            root
            / "data/research/paper_simulator/single_live_context_refresh_append_qa_final_decision.json"
        ).read_text()
    )
    assert final["qa_decision"] == (
        "SINGLE_LIVE_CONTEXT_REFRESH_APPEND_QA_PASS_WITH_LIMITATIONS"
    )
    assert final["qa_status"] == "PASS_WITH_LIMITATIONS"
    assert final["append_verified"] is True
    assert final["appended_rows_count_verified"] == 1
    assert final["ready_for_candidate_cycle_dry_run_no_write"] is True
    assert final["run_readiness_status"] == (
        "READY_FOR_LIVE_POLICY_SIGNAL_CANDIDATE_CYCLE_DRY_RUN_NO_WRITE"
    )
    assert final["next_recommended_step"] == (
        "LIVE_POLICY_SIGNAL_CANDIDATE_CYCLE_DRY_RUN_NO_WRITE"
    )
    assert final["paper_signal_write_performed"] is False
    assert final["paper_ledger_write_performed"] is False
    assert final["execution_enabled"] is False
    safety = json.loads(
        (
            root
            / "data/research/paper_simulator/single_live_context_refresh_append_qa_no_write_safety.json"
        ).read_text()
    )
    assert safety["bounded_watcher_started"] is False
    assert safety["live_refresh_performed"] is False
    assert safety["live_decision_log_append_performed"] is False
    src = AUDIT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in mod.FORBIDDEN_IMPORT_ROOTS
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in mod.FORBIDDEN_IMPORT_ROOTS


def test_helpers_close_equals_open_plus_15():
    open_ts = pd.Timestamp("2026-07-21T06:45:00Z")
    close = open_ts + pd.Timedelta(minutes=15)
    assert mod._norm_ts(close) == "2026-07-21T07:00:00Z"
