#!/usr/bin/env python3
"""Tests for paper policy action timestamp semantics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "live"))

from paper_action_clock import resolve_paper_action_ts  # noqa: E402
from paper_policy_engine import (  # noqa: E402
    is_context_start_event,
    is_directional_flip,
)


def test_flip_still_is_start():
    assert is_context_start_event("LONG_CONTEXT", "SHORT_CONTEXT") is True
    assert is_directional_flip("LONG_CONTEXT", "SHORT_CONTEXT") is True
    assert is_context_start_event("SHORT_CONTEXT", "SHORT_CONTEXT") is False


def test_paper_action_prefers_detected_not_source():
    out = resolve_paper_action_ts(
        context_event_detected_at="2026-07-21T15:07:00Z",
        source_context_ts="2026-07-21T15:00:00Z",
    )
    assert out["paper_action_ts"].startswith("2026-07-21T15:07:00")
    assert out["action_used_source_context_ts"] is False


def test_no_m15_close_when_detected_present():
    out = resolve_paper_action_ts(
        context_event_detected_at="2026-07-21T15:07:00Z",
        m15_bar_close="2026-07-21T15:15:00Z",
        source_context_ts="2026-07-21T15:00:00Z",
        allow_m15_close_fallback=True,
    )
    assert out["action_used_m15_close"] is False


def test_controller_helper_resolves_from_decision_fields():
    # Import controller helper without running main.
    import importlib.util

    path = ROOT / "scripts/live/bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
    spec = importlib.util.spec_from_file_location("bounded_paper_ctrl_clock", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Avoid executing full module side effects heavily — still loads.
    sys.modules["bounded_paper_ctrl_clock"] = mod
    spec.loader.exec_module(mod)
    clock = mod._resolve_action_clock(
        {
            "candle_timestamp": "2026-07-21T15:00:00Z",
            "context_event_detected_at": "2026-07-21T15:07:00Z",
            "decision_written_at_utc": "2026-07-21T15:16:00Z",
        },
        controller_cycle_at="2026-07-21T15:20:00Z",
    )
    assert clock["paper_action_ts"].startswith("2026-07-21T15:07:00")
    assert clock["source_context_ts"] == "2026-07-21T15:00:00Z"
    assert clock["controller_cycle_at"].startswith("2026-07-21T15:20:00")
