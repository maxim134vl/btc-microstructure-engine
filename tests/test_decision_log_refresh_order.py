#!/usr/bin/env python3
"""Tests that decision log is built after lifecycle refresh reload."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTRL = ROOT / "scripts" / "live" / "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
SINGLE = ROOT / "scripts" / "live" / "single_live_context_refresh_and_decision_log_append_no_paper_signal.py"
LOGGER = ROOT / "scripts" / "live" / "append_context_decision_log.py"


def test_refresh_order_reload_before_decision_build():
    src = CTRL.read_text(encoding="utf-8")
    assert "decision_built_after_lifecycle_refresh" in src
    assert "lifecycle_row_reloaded_after_refresh" in src
    assert "final_context_row_reloaded_after_refresh" in src
    assert "decision_context_matches_lifecycle" in src
    refresh_fn = src.split("def refresh_and_maybe_append", 1)[1].split("def append_cycle_record", 1)[0]
    assert refresh_fn.find("pd.read_parquet(lifecycle)") < refresh_fn.find("build_decision_preview")
    assert refresh_fn.find("run_one_shot_refresh") < refresh_fn.find("build_decision_preview")


def test_build_decision_preview_accepts_previous_decision():
    src = SINGLE.read_text(encoding="utf-8")
    assert "previous_decision" in src
    assert "build_decision_row" in src


def test_decision_row_exports_candidate_and_active_start_fields():
    src = LOGGER.read_text(encoding="utf-8")
    assert "_derive_decision_start_fields" in src
    assert "candidate_started_at" in src
    assert "active_context_started_at" in src
    assert "context_start_event" in src
    assert "lifecycle_episode_start_time" in src
