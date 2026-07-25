#!/usr/bin/env python3
"""Visual overlay must plot paper_action_ts, not source_context_ts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts/live/visual_paper_trade_overlay_builder.py"
    spec = importlib.util.spec_from_file_location("visual_paper_trade_overlay_builder", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["visual_paper_trade_overlay_builder"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_restated_shape_uses_paper_action_ts_not_source():
    mod = _load()
    shape = mod._shape_from_restated(
        {
            "side": "LONG",
            "restated_trade_id": "RESTATED_1",
            "original_trade_id": "ORIG_1",
            "restated_entry_price": 100.0,
            "restated_exit_price": 101.0,
            "restated_entry_ts": "2026-07-21T15:07:00Z",
            "restated_exit_ts": "2026-07-21T15:09:00Z",
            "paper_action_ts_entry": "2026-07-21T15:07:00Z",
            "paper_action_ts_exit": "2026-07-21T15:09:00Z",
            "source_context_ts_entry": "2026-07-21T15:00:00Z",
            "source_context_ts_exit": "2026-07-21T15:00:00Z",
            "context_event_detected_at_entry": "2026-07-21T15:07:00Z",
            "clock_source_used_entry": "intrabar_event_detected_at",
            "clock_warnings_entry": ["ACTION_USED_INTRABAR_EVENT_DETECTED_AT"],
            "intrabar_event_id": "ICE_abc",
            "net_pnl_usd": 1.0,
            "pnl_bps": 10.0,
            "qty": 0.1,
            "notional_usd": 10000.0,
            "entry_fee": 1.0,
            "exit_fee": 1.0,
            "entry_context": "LONG_CONTEXT",
            "exit_context": "OBSERVE",
            "entry_lifecycle_state": "ACTIVE",
            "exit_lifecycle_state": "NO_ACTIVE_CONTEXT",
            "stop_loss_price": 99.0,
            "take_profit_price": 102.0,
        }
    )
    assert shape["entry_ts"].startswith("2026-07-21T15:07:00")
    assert shape["exit_ts"].startswith("2026-07-21T15:09:00")
    assert shape["source_context_ts"] == "2026-07-21T15:00:00Z"
    assert shape["entry_ts"] != shape["source_context_ts"]
    assert shape["action_clock_source"] == "intrabar_event_detected_at"
    assert shape["intrabar_event_id"] == "ICE_abc"
    assert shape.get("clock_warning")
    assert "15:15:00" not in (shape["entry_ts"] or "")


def test_builder_source_mentions_paper_action_ts():
    text = (ROOT / "scripts/live/visual_paper_trade_overlay_builder.py").read_text(encoding="utf-8")
    assert "paper_action_ts" in text
    assert "source_context_ts_entry" in text
    assert "action_clock_source" in text
    assert "intrabar_event_id" in text
    assert "clock_warning" in text
