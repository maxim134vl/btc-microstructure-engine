from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOGGER_PATH = ROOT / "scripts" / "live" / "append_context_decision_log.py"
CONTROLLER_PATH = (
    ROOT
    / "scripts"
    / "live"
    / "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
)
SCRIPTS_LIVE = ROOT / "scripts" / "live"


def _load_module(name: str, path: Path):
    if str(SCRIPTS_LIVE) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_LIVE))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _candidate_row(candidate_context: str = "LONG_CONTEXT") -> dict:
    return {
        "decision_id": "candidate-1330",
        "decision_written_at_utc": "2026-07-22T13:51:04.944953Z",
        "candle_timestamp": "2026-07-22T13:30:00Z",
        "candle_close_time_utc": "2026-07-22T13:45:00Z",
        "active_market_context": "OBSERVE",
        "previous_active_market_context": "SHORT_CONTEXT",
        "lifecycle_state": "CANDIDATE",
        "candidate_context": candidate_context,
        "candidate_started_at": "2026-07-22T13:30:00Z",
        "context_start_event": True,
        "context_start_event_source": "candidate_started_at",
        "directional_flip_detected": True,
        "decision_stale": False,
        "confidence": None,
        "expected_edge_bps": None,
        "raw_context_status": "DEVELOPING",
    }


def test_directional_candidate_long_propagates_to_paper_action_without_lookup():
    logger = _load_module("append_context_decision_log_candidate_test", LOGGER_PATH)
    row = _candidate_row("LONG_CONTEXT")

    signal = logger.derive_signal_fields(
        row,
        now_utc=datetime(2026, 7, 22, 13, 51, tzinfo=timezone.utc),
        lookup_df=pd.DataFrame(),
        use_lookup=True,
    )

    assert signal["signal_eligibility_status"] == "ELIGIBLE_DIRECTIONAL_SIGNAL"
    assert json.loads(signal["signal_block_reasons"]) == []
    assert signal["paper_action_candidate"] == "INTENT_OPEN_LONG"
    assert signal["intended_side"] == "LONG"
    assert signal["order_side"] == "BUY"
    assert signal["position_intent"] == "OPEN_LONG"
    assert signal["confidence_available"] is False
    assert signal["expected_edge_available"] is False
    assert signal["paper_signal_write_allowed"] is False
    assert signal["paper_loop_allowed"] is False


def test_directional_candidate_short_propagates_to_paper_action_without_lookup():
    logger = _load_module("append_context_decision_log_candidate_test_short", LOGGER_PATH)
    row = _candidate_row("SHORT_CONTEXT")

    signal = logger.derive_signal_fields(
        row,
        now_utc=datetime(2026, 7, 22, 13, 51, tzinfo=timezone.utc),
        lookup_df=pd.DataFrame(),
        use_lookup=True,
    )

    assert signal["signal_eligibility_status"] == "ELIGIBLE_DIRECTIONAL_SIGNAL"
    assert json.loads(signal["signal_block_reasons"]) == []
    assert signal["paper_action_candidate"] == "INTENT_OPEN_SHORT"
    assert signal["intended_side"] == "SHORT"
    assert signal["order_side"] == "SELL"
    assert signal["position_intent"] == "OPEN_SHORT"


def test_observe_without_directional_candidate_remains_no_trade():
    logger = _load_module("append_context_decision_log_candidate_test_observe", LOGGER_PATH)
    row = _candidate_row(None)

    signal = logger.derive_signal_fields(
        row,
        now_utc=datetime(2026, 7, 22, 13, 51, tzinfo=timezone.utc),
        lookup_df=pd.DataFrame(),
        use_lookup=True,
    )

    assert signal["signal_eligibility_status"] == "BLOCKED_OBSERVE_CONTEXT"
    assert "OBSERVE_CONTEXT" in json.loads(signal["signal_block_reasons"])
    assert signal["paper_action_candidate"] == "NO_TRADE_OBSERVE"
    assert signal["intended_side"] == "NONE"
    assert signal["position_intent"] == "NONE"


def test_controller_gate_can_consume_directional_candidate_start():
    controller = _load_module("bounded_controller_candidate_test", CONTROLLER_PATH)
    row = _candidate_row("LONG_CONTEXT")
    previous = {
        "candle_timestamp": "2026-07-22T13:15:00Z",
        "active_market_context": "SHORT_CONTEXT",
        "lifecycle_state": "CHALLENGED",
    }

    gate = controller.evaluate_flat_entry_gate(
        row,
        previous_decision=previous,
        traded_episode_memory={},
        position_already_open=False,
    )

    assert gate["allowed"] is True
    assert gate["policy_action"] == "OPEN_LONG"
    assert gate["paper_action"] == "INTENT_OPEN_LONG"
    assert gate["side"] == "LONG"
    assert gate["entry_used_context_layer"] == "CANDIDATE"


def test_controller_metadata_json_sanitizes_nat_values():
    controller = _load_module("bounded_controller_metadata_test", CONTROLLER_PATH)

    payload = json.loads(
        controller._metadata_json(
            {
                "ok": "yes",
                "missing_ts": pd.NaT,
                "nested": {"also_missing": float("nan")},
            }
        )
    )

    assert payload == {"ok": "yes", "missing_ts": None, "nested": {"also_missing": None}}
