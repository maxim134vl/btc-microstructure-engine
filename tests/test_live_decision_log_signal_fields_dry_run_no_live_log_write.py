"""Tests for live decision log signal fields dry-run (no live log write)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "scripts"
    / "research"
    / "build_live_decision_log_signal_fields_dry_run_no_live_log_write.py"
)
SCHEMA_MOD_PATH = ROOT / "scripts" / "research" / "build_paper_simulator_schema_ledger.py"

spec = importlib.util.spec_from_file_location(
    "build_live_decision_log_signal_fields_dry_run_no_live_log_write", MODULE_PATH
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_live_decision_log_signal_fields_dry_run_no_live_log_write"] = mod
spec.loader.exec_module(mod)

schema_spec = importlib.util.spec_from_file_location(
    "build_paper_simulator_schema_ledger_for_signal_fields_test", SCHEMA_MOD_PATH
)
assert schema_spec and schema_spec.loader
schema_mod = importlib.util.module_from_spec(schema_spec)
sys.modules["build_paper_simulator_schema_ledger_for_signal_fields_test"] = schema_mod
schema_spec.loader.exec_module(schema_mod)

LATEST_TS = "2026-07-19T18:03:13.003997Z"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_empty_ledgers(ledger: Path) -> None:
    ledger.mkdir(parents=True, exist_ok=True)
    for _, ledger_spec in schema_mod.LEDGER_SPECS.items():
        df = schema_mod.empty_frame(ledger_spec["columns"])
        df.to_parquet(ledger / ledger_spec["parquet_name"], index=False)


def _append_n(path: Path, n: int, template: dict) -> None:
    existing = pd.read_parquet(path)
    rows = []
    for i in range(n):
        row = dict(template)
        for key in ("event_id", "paper_order_id", "paper_trade_id", "position_id"):
            if key in row:
                row[key] = f"{row[key]}_{i}"
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in existing.columns:
        try:
            df[col] = df[col].astype(existing[col].dtype)
        except Exception:
            pass
    pd.concat([existing, df], ignore_index=True).to_parquet(path, index=False)


def _seed_counts(ledger: Path) -> None:
    _append_n(
        ledger / "paper_events.parquet",
        3,
        {
            "event_id": "e",
            "event_type": "PAPER_SIGNAL",
            "timestamp": "2026-07-20T07:00:00Z",
            "decision_id": "d",
            "candle_timestamp": pd.NA,
            "active_market_context": "CTX",
            "raw_market_context": "CTX",
            "lifecycle_state": "ACTIVE",
            "candidate_model_version": "v3",
            "candidate_prediction_label": "ENTER_EARLIER",
            "signal_direction": "SHORT",
            "paper_action": "INTENT",
            "action_reason": "x",
            "paper_order_id": pd.NA,
            "position_id": pd.NA,
            "symbol": "BTCUSDT",
            "price": float("nan"),
            "quantity": float("nan"),
            "notional": float("nan"),
            "fee_bps": 5.0,
            "slippage_bps": 5.0,
            "risk_gate_status": "PASS",
            "risk_block_reason": "NONE",
            "execution_enabled": False,
            "paper_only": True,
            "metadata_json": "{}",
        },
    )
    _append_n(
        ledger / "paper_orders.parquet",
        2,
        {
            "paper_order_id": "o",
            "created_at": "2026-07-20T07:10:00Z",
            "decision_id": "d",
            "candle_timestamp": pd.NA,
            "symbol": "BTCUSDT",
            "side": "SELL",
            "order_type": "MARKET_SIMULATED",
            "quantity": 0.05,
            "requested_price": 100000.0,
            "notional": 5000.0,
            "status": "PAPER_ORDER_PREVIEW_RECORDED",
            "fill_price": 100000.0,
            "filled_quantity": 0.0,
            "fee_bps": 5.0,
            "slippage_bps": 5.0,
            "paper_only": True,
            "execution_enabled": False,
            "risk_gate_status": "PASS",
            "risk_block_reason": "NONE",
            "metadata_json": "{}",
        },
    )
    _append_n(
        ledger / "paper_trades.parquet",
        2,
        {
            "paper_trade_id": "t",
            "paper_order_id": "o",
            "position_id": "p",
            "timestamp": "2026-07-20T07:20:00Z",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "quantity": 0.05,
            "price": 100000.0,
            "notional": 5000.0,
            "fee": 2.5,
            "fee_bps": 5.0,
            "slippage": 2.5,
            "slippage_bps": 5.0,
            "realized_pnl": 0.0,
            "paper_only": True,
            "execution_enabled": False,
            "metadata_json": "{}",
        },
    )
    _append_n(
        ledger / "paper_positions.parquet",
        2,
        {
            "position_id": "p",
            "opened_at": "2026-07-20T08:00:00Z",
            "closed_at": pd.NA,
            "symbol": "BTCUSDT",
            "direction": "SHORT",
            "quantity": 0.05,
            "entry_price": 99950.0,
            "exit_price": float("nan"),
            "notional": 4997.5,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fees_paid": 2.5,
            "slippage_paid": 2.5,
            "status": "OPEN",
            "opening_decision_id": "d",
            "closing_decision_id": pd.NA,
            "paper_only": True,
            "execution_enabled": False,
            "metadata_json": "{}",
        },
    )
    _append_n(
        ledger / "paper_equity_curve.parquet",
        2,
        {
            "timestamp": "2026-07-20T11:00:00Z",
            "cash": 99992.5,
            "position_value": 4997.5,
            "equity": 99992.5,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fees_paid": 2.5,
            "slippage_paid": 2.5,
            "drawdown_pct": 0.0,
            "daily_pnl": -7.5,
            "paper_only": True,
            "execution_enabled": False,
            "metadata_json": "{}",
        },
    )


def _write_artifacts(ledger: Path) -> None:
    _write_json(
        ledger / "live_decision_signal_readiness_gap_final_decision.json",
        {
            "status": "LIVE_DECISION_SIGNAL_READINESS_GAP_AUDIT_PASS_WITH_LIMITATIONS",
            "qa_status": "PASS_WITH_LIMITATIONS",
        },
    )
    _write_json(
        ledger / "live_decision_signal_readiness_gap_schema_check.json",
        {
            "has_confidence": False,
            "has_expected_edge_bps": False,
            "schema_check_status": "PASS_WITH_LIMITATIONS",
        },
    )
    _write_json(
        ledger / "live_decision_signal_readiness_gap_required_fixes.json",
        {"required_fix_count": 10, "required_fixes_status": "PASS"},
    )
    _write_json(
        ledger / "live_decision_to_paper_signal_adapter_qa_mapping_check.json",
        {"mapping_check_status": "PASS"},
    )
    _write_json(
        ledger / "live_decision_to_paper_signal_adapter_qa_gap_check.json",
        {"adapter_fixture_contract_ready": True},
    )
    _write_json(
        ledger / "paper_ledger_status.json",
        {"execution_enabled": False, "paper_trading_started": False},
    )


def _setup(tmp_path: Path, *, with_decision_log: bool = True) -> dict[str, Path]:
    ledger = tmp_path / "paper_simulator"
    report = tmp_path / "LIVE_DECISION_LOG_SIGNAL_FIELDS_DRY_RUN_NO_LIVE_LOG_WRITE.md"
    decision_log = tmp_path / "context_decision_log.parquet"
    # Empty cognition dir so source inventory finds no fake confidence/edge
    (tmp_path / "data" / "cognition").mkdir(parents=True, exist_ok=True)
    _write_empty_ledgers(ledger)
    _seed_counts(ledger)
    _write_artifacts(ledger)
    if with_decision_log:
        pd.DataFrame(
            [
                {
                    "decision_id": f"d{i}",
                    "decision_written_at_utc": LATEST_TS,
                    "active_market_context": "OBSERVE",
                    "decision_stale": True,
                    "action_allowed": False,
                }
                for i in range(8)
            ]
        ).to_parquet(decision_log, index=False)
    return {
        "ledger_dir": ledger,
        "report_path": report,
        "decision_log": decision_log,
        "root": tmp_path,
    }


def test_missing_gap_audit_blocks(tmp_path: Path):
    paths = _setup(tmp_path)
    (
        paths["ledger_dir"] / "live_decision_signal_readiness_gap_final_decision.json"
    ).unlink()
    result = mod.run_dry_run(
        root=paths["root"],
        ledger_dir=paths["ledger_dir"],
        report_path=paths["report_path"],
        decision_log=paths["decision_log"],
    )
    assert result["blocked"] is True
    assert (
        result["decision"]["status"] == "BLOCKED_INVALID_SIGNAL_FIELDS_DRY_RUN_INPUTS"
    )


def test_missing_decision_log_classified_as_gap(tmp_path: Path):
    paths = _setup(tmp_path, with_decision_log=False)
    result = mod.run_dry_run(
        root=paths["root"],
        ledger_dir=paths["ledger_dir"],
        report_path=paths["report_path"],
        decision_log=paths["decision_log"],
    )
    assert result["blocked"] is False
    assert result["schema_inventory"]["decision_log_found"] is False
    assert (
        result["schema_inventory"]["current_schema_status"]
        == "MISSING_LIVE_DECISION_LOG"
    )
    assert result["schema_inventory"]["classified_as_gap_not_crash"] is True
    assert result["decision"]["live_decision_log_write_performed"] is False


def test_full_signal_fields_dry_run(tmp_path: Path):
    paths = _setup(tmp_path, with_decision_log=True)
    ledger = paths["ledger_dir"]
    hashes_before = {n: _sha(ledger / n) for n in mod.LEDGER_PARQUETS}
    dlog_before = _sha(paths["decision_log"])

    result = mod.run_dry_run(
        root=paths["root"],
        ledger_dir=ledger,
        report_path=paths["report_path"],
        decision_log=paths["decision_log"],
    )
    assert result["blocked"] is False
    assert result["validation"]["ledger_counts_valid"] is True

    inv = result["schema_inventory"]
    assert inv["decision_log_found"] is True
    assert inv["decision_log_rows"] == 8
    assert inv["has_timestamp"] is True
    assert inv["has_context"] is True
    assert inv["has_stale_flag"] is True
    assert inv["has_confidence"] is False
    assert inv["has_expected_edge_bps"] is False
    assert inv["has_total_roundtrip_model_cost_bps"] is False
    assert inv["has_edge_above_cost"] is False
    assert inv["current_schema_status"] == "PRESENT_SCHEMA_LIMITED"

    src = result["source_inventory"]
    assert src["confidence_source_available_now"] is False
    assert src["expected_edge_source_available_now"] is False
    assert src["deterministic_cost_source_available"] is True
    assert src["deterministic_total_roundtrip_model_cost_bps"] == 20.0
    assert src["source_inventory_status"] == "PASS_WITH_LIMITATIONS"

    spec_ = result["schema_spec"]
    assert spec_["required_schema_additive_only"] is True
    assert spec_["destructive_schema_change_required"] is False
    assert spec_["required_fields_count"] == len(mod.REQUIRED_ADDITIVE_FIELDS)
    assert spec_["schema_spec_status"] == "PASS"

    rules = result["rules"]
    assert rules["long_rule_status"] == "PASS"
    assert rules["short_rule_status"] == "PASS"
    assert rules["observe_rule_status"] == "PASS"
    assert rules["stale_rule_status"] == "PASS"
    assert rules["missing_confidence_rule_status"] == "PASS"
    assert rules["missing_expected_edge_rule_status"] == "PASS"
    assert rules["edge_below_cost_rule_status"] == "PASS"
    assert rules["enrichment_rules_status"] == "PASS"

    latest = result["latest"]
    assert latest["source_timestamp"] == LATEST_TS
    assert latest["source_context"] == "OBSERVE"
    assert latest["source_is_stale"] is True
    assert latest["confidence"] is None
    assert latest["expected_edge_bps"] is None
    assert latest["total_roundtrip_model_cost_bps"] == 20.0
    assert latest["signal_eligibility_status"] == "BLOCKED_STALE_CONTEXT"
    assert "STALE_CONTEXT" in latest["signal_block_reasons"]
    assert "OBSERVE_CONTEXT" in latest["signal_block_reasons"]
    assert "MISSING_CONFIDENCE" in latest["signal_block_reasons"]
    assert "MISSING_EXPECTED_EDGE" in latest["signal_block_reasons"]
    assert latest["paper_action_candidate"] == "NO_TRADE_STALE_CONTEXT"
    assert latest["intended_side"] == "NONE"
    assert latest["paper_signal_write_allowed"] is False
    assert latest["preview_status"] == "PASS_WITH_LIMITATIONS"

    long_p = result["long_preview"]
    assert long_p["signal_eligibility_status"] == "ELIGIBLE_DIRECTIONAL_SIGNAL"
    assert long_p["paper_action_candidate"] == "INTENT_OPEN_LONG"
    assert long_p["order_side"] == "BUY"
    assert long_p["position_intent"] == "OPEN_LONG"
    assert long_p["edge_above_cost"] is True
    assert long_p["paper_signal_write_allowed"] is False
    assert long_p["preview_status"] == "PASS"

    short_p = result["short_preview"]
    assert short_p["signal_eligibility_status"] == "ELIGIBLE_DIRECTIONAL_SIGNAL"
    assert short_p["paper_action_candidate"] == "INTENT_OPEN_SHORT"
    assert short_p["order_side"] == "SELL"
    assert short_p["position_intent"] == "OPEN_SHORT"
    assert short_p["edge_above_cost"] is True
    assert short_p["preview_status"] == "PASS"

    cases = result["observe_stale"]["cases"]
    assert cases["observe_fresh"]["paper_action_candidate"] == "NO_TRADE_OBSERVE"
    assert cases["long_context_stale"]["paper_action_candidate"] == "NO_TRADE_STALE_CONTEXT"
    assert (
        cases["long_context_edge_below_cost"]["paper_action_candidate"]
        == "NO_TRADE_EDGE_BELOW_COST"
    )

    # Direct enrichment checks
    miss_conf = mod.enrich_decision(
        source_context="LONG_CONTEXT",
        source_is_stale=False,
        confidence=None,
        expected_edge_bps=35.0,
        source_timestamp="t",
    )
    assert miss_conf["signal_eligibility_status"] == "BLOCKED_MISSING_CONFIDENCE"
    miss_edge = mod.enrich_decision(
        source_context="LONG_CONTEXT",
        source_is_stale=False,
        confidence=0.72,
        expected_edge_bps=None,
        source_timestamp="t",
    )
    assert miss_edge["signal_eligibility_status"] == "BLOCKED_MISSING_EXPECTED_EDGE"

    patch = result["patch"]
    assert patch["patch_required"] is True
    assert patch["confidence_source_plan"]["status"] == (
        "TBD_REQUIRED_IMPLEMENTATION_SOURCE"
    )
    assert patch["expected_edge_source_plan"]["status"] == (
        "TBD_REQUIRED_IMPLEMENTATION_SOURCE"
    )
    assert patch["deterministic_cost_source_plan"][
        "total_roundtrip_model_cost_bps"
    ] == 20.0
    assert patch["live_decision_log_write_allowed_now"] is False
    assert patch["paper_signal_write_allowed_now"] is False
    assert patch["paper_loop_allowed_now"] is False
    assert patch["patch_plan_status"] == "PASS_WITH_REQUIRED_PATCH"

    decision = result["decision"]
    assert (
        decision["status"]
        == "LIVE_DECISION_LOG_SIGNAL_FIELDS_DRY_RUN_PASS_WITH_REQUIRED_PATCH"
    )
    assert decision["qa_status"] == "PASS_WITH_LIMITATIONS"
    assert decision["signal_fields_schema_spec_ready"] is True
    assert decision["enrichment_rules_ready"] is True
    assert decision["latest_decision_enrichment_preview_ready"] is True
    assert decision["live_decision_log_write_performed"] is False
    assert decision["paper_signal_write_allowed_now"] is False
    assert decision["paper_loop_allowed_now"] is False
    assert decision["run_readiness_status"] == "NOT_READY_TO_RUN_PAPER_TRADING"
    assert (
        decision["next_recommended_step"]
        == "USER_APPROVAL_FOR_LIVE_DECISION_LOG_SIGNAL_FIELDS_PATCH"
    )

    assert result["snapshot"]["live_decision_log_mutated_by_dry_run"] is False
    assert result["snapshot"]["paper_ledgers_mutated_by_dry_run"] is False
    assert result["safety"]["live_refresh_used"] is False
    assert result["safety"]["exchange_api_order_or_fill_or_position_call_used"] is False
    assert result["safety"]["production_parquet_mutated"] is False
    assert result["safety"]["runtime_mutated"] is False
    assert result["safety"]["no_write_status"] == "PASS"

    for n in mod.LEDGER_PARQUETS:
        assert _sha(ledger / n) == hashes_before[n]
    assert _sha(paths["decision_log"]) == dlog_before
    assert mod.assert_no_forbidden_imports() is True
    assert mod.assert_no_loop_or_sleep() is True
    assert paths["report_path"].exists()
