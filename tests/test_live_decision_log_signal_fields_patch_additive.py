"""Tests for additive-only live decision log signal fields patch."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = (
    ROOT / "scripts" / "research" / "patch_live_decision_log_signal_fields_additive.py"
)
LOGGER_PATH = ROOT / "scripts" / "live" / "append_context_decision_log.py"
SCHEMA_MOD_PATH = ROOT / "scripts" / "research" / "build_paper_simulator_schema_ledger.py"

spec = importlib.util.spec_from_file_location(
    "patch_live_decision_log_signal_fields_additive", PATCH_PATH
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["patch_live_decision_log_signal_fields_additive"] = mod
spec.loader.exec_module(mod)

logger_spec = importlib.util.spec_from_file_location(
    "append_context_decision_log_for_signal_fields_patch_test", LOGGER_PATH
)
assert logger_spec and logger_spec.loader
logger_mod = importlib.util.module_from_spec(logger_spec)
sys.modules["append_context_decision_log_for_signal_fields_patch_test"] = logger_mod
logger_spec.loader.exec_module(logger_mod)

schema_spec = importlib.util.spec_from_file_location(
    "build_paper_simulator_schema_ledger_for_signal_fields_patch_test", SCHEMA_MOD_PATH
)
assert schema_spec and schema_spec.loader
schema_mod = importlib.util.module_from_spec(schema_spec)
sys.modules["build_paper_simulator_schema_ledger_for_signal_fields_patch_test"] = schema_mod
schema_spec.loader.exec_module(schema_mod)

LATEST_TS = "2026-07-19T18:03:13.003997Z"
FRESH_TS = "2026-07-20T12:00:00.000000Z"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _base_decision_row(i: int, *, context: str = "OBSERVE", written_at: str = LATEST_TS) -> dict:
    return {
        "decision_id": f"d{i}",
        "decision_written_at_utc": written_at,
        "candle_timestamp": written_at,
        "candle_close_time_utc": written_at,
        "source_timeframe": "15m",
        "runtime_pid": 1,
        "pipeline_cycle": i,
        "runtime_segments": 1,
        "total_runtime_log_cycles": i,
        "live_feed_latest_timestamp": written_at,
        "auction_latest_timestamp": written_at,
        "cognitive_latest_timestamp": written_at,
        "final_context_latest_timestamp": written_at,
        "lifecycle_latest_timestamp": written_at,
        "live_to_auction_lag_seconds": 0,
        "live_to_cognitive_lag_seconds": 0,
        "live_to_final_context_lag_seconds": 0,
        "live_to_lifecycle_lag_seconds": 0,
        "decision_lag_vs_live_seconds": 0,
        "decision_lag_vs_lifecycle_seconds": 0,
        "auction_episode": "E",
        "auction_episode_status": "UNKNOWN",
        "cognitive_market_state": "S",
        "cognitive_state_status": "UNKNOWN",
        "cognitive_state_direction": "UNKNOWN",
        "raw_market_context": context,
        "raw_context_status": "UNKNOWN",
        "active_market_context": context,
        "lifecycle_state": "ACTIVE",
        "active_context_age_bars": 1,
        "active_context_started_at": written_at,
        "invalidation_type": "NONE",
        "action_allowed": False,
        "shadow_only": True,
        "execution_enabled": False,
        "visual_json_used_for_execution": False,
        "orders_created": False,
        "paper_orders_created": False,
        "technical_refresh_lag_present": False,
        "decision_stale": False,
        "execution_readiness_blocked": True,
        "source_files_hash": "abc",
        "decision_payload_hash": f"hash{i}",
        "schema_version": "context_decision_log_v1",
        "logger_version": "append_context_decision_log_v1",
    }


def _seed_decision_log(path: Path, rows: int = 8) -> pd.DataFrame:
    data = []
    for i in range(rows - 1):
        data.append(_base_decision_row(i, context="LONG_CONTEXT", written_at=FRESH_TS))
    data.append(_base_decision_row(rows - 1, context="OBSERVE", written_at=LATEST_TS))
    df = pd.DataFrame(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def _seed_inputs(tmp: Path) -> tuple[Path, Path, Path, Path]:
    ledger = tmp / "paper_simulator"
    live = tmp / "live"
    backups = live / "context_decision_log_backups"
    decision_log = live / "context_decision_log.parquet"
    report = tmp / "LIVE_DECISION_LOG_SIGNAL_FIELDS_PATCH_ADDITIVE.md"
    _write_empty_ledgers(ledger)
    _seed_counts(ledger)
    _seed_decision_log(decision_log, 8)
    _write_json(
        ledger / "live_decision_log_signal_fields_dry_run_final_decision.json",
        {
            "status": "LIVE_DECISION_LOG_SIGNAL_FIELDS_DRY_RUN_PASS_WITH_REQUIRED_PATCH",
            "qa_status": "PASS_WITH_LIMITATIONS",
        },
    )
    _write_json(
        ledger / "live_decision_log_signal_fields_required_schema_spec.json",
        {"schema_spec_status": "PASS"},
    )
    _write_json(
        ledger / "live_decision_log_signal_fields_enrichment_rules.json",
        {"enrichment_rules_status": "PASS"},
    )
    _write_json(
        ledger / "live_decision_log_signal_fields_patch_plan.json",
        {"patch_plan_status": "PASS_WITH_REQUIRED_PATCH"},
    )
    _write_json(
        ledger / "paper_ledger_status.json",
        {"execution_enabled": False, "paper_trading_started": False},
    )
    return ledger, decision_log, backups, report


def test_missing_approval_flag_blocks_patch(tmp_path: Path, monkeypatch) -> None:
    ledger, decision_log, backups, report = _seed_inputs(tmp_path)
    monkeypatch.setattr(mod, "LEDGER_DIR", ledger)
    monkeypatch.setattr(mod, "DRY_RUN_FINAL", ledger / "live_decision_log_signal_fields_dry_run_final_decision.json")
    monkeypatch.setattr(mod, "REQUIRED_SCHEMA", ledger / "live_decision_log_signal_fields_required_schema_spec.json")
    monkeypatch.setattr(mod, "ENRICHMENT_RULES", ledger / "live_decision_log_signal_fields_enrichment_rules.json")
    monkeypatch.setattr(mod, "PATCH_PLAN", ledger / "live_decision_log_signal_fields_patch_plan.json")
    monkeypatch.setattr(mod, "LEDGER_STATUS", ledger / "paper_ledger_status.json")
    before = _sha(decision_log)
    result = mod.run_patch(
        approved=False,
        research_only=True,
        ledger_dir=ledger,
        decision_log=decision_log,
        backup_dir=backups,
        report_path=report,
        write_reports=True,
    )
    assert result["final"]["status"] == "BLOCKED_APPROVAL_FLAG_REQUIRED"
    assert result["precheck"]["input_validation_status"] == "BLOCKED_APPROVAL_FLAG_REQUIRED"
    assert _sha(decision_log) == before


def test_missing_dry_run_artifacts_blocks_patch(tmp_path: Path, monkeypatch) -> None:
    ledger, decision_log, backups, report = _seed_inputs(tmp_path)
    (ledger / "live_decision_log_signal_fields_dry_run_final_decision.json").unlink()
    monkeypatch.setattr(mod, "LEDGER_DIR", ledger)
    monkeypatch.setattr(mod, "DRY_RUN_FINAL", ledger / "live_decision_log_signal_fields_dry_run_final_decision.json")
    monkeypatch.setattr(mod, "REQUIRED_SCHEMA", ledger / "live_decision_log_signal_fields_required_schema_spec.json")
    monkeypatch.setattr(mod, "ENRICHMENT_RULES", ledger / "live_decision_log_signal_fields_enrichment_rules.json")
    monkeypatch.setattr(mod, "PATCH_PLAN", ledger / "live_decision_log_signal_fields_patch_plan.json")
    monkeypatch.setattr(mod, "LEDGER_STATUS", ledger / "paper_ledger_status.json")
    before = _sha(decision_log)
    result = mod.run_patch(
        approved=True,
        research_only=True,
        ledger_dir=ledger,
        decision_log=decision_log,
        backup_dir=backups,
        report_path=report,
        write_reports=True,
    )
    assert result["final"]["status"] == "BLOCKED_INVALID_SIGNAL_FIELDS_PATCH_INPUTS"
    assert _sha(decision_log) == before


def test_patch_additive_only_and_preserves_existing(tmp_path: Path, monkeypatch) -> None:
    ledger, decision_log, backups, report = _seed_inputs(tmp_path)
    monkeypatch.setattr(mod, "LEDGER_DIR", ledger)
    monkeypatch.setattr(mod, "DRY_RUN_FINAL", ledger / "live_decision_log_signal_fields_dry_run_final_decision.json")
    monkeypatch.setattr(mod, "REQUIRED_SCHEMA", ledger / "live_decision_log_signal_fields_required_schema_spec.json")
    monkeypatch.setattr(mod, "ENRICHMENT_RULES", ledger / "live_decision_log_signal_fields_enrichment_rules.json")
    monkeypatch.setattr(mod, "PATCH_PLAN", ledger / "live_decision_log_signal_fields_patch_plan.json")
    monkeypatch.setattr(mod, "LEDGER_STATUS", ledger / "paper_ledger_status.json")

    before_df = pd.read_parquet(decision_log)
    before_cols = list(before_df.columns)
    before_values = before_df.copy()
    ledger_hashes = {name: _sha(ledger / name) for name in mod.LEDGER_PARQUETS}

    result = mod.run_patch(
        approved=True,
        research_only=True,
        ledger_dir=ledger,
        decision_log=decision_log,
        backup_dir=backups,
        report_path=report,
        write_reports=True,
    )

    after_df = pd.read_parquet(decision_log)
    assert result["final"]["status"] == "LIVE_DECISION_LOG_SIGNAL_FIELDS_PATCH_APPLIED_WITH_LIMITATIONS"
    assert result["final"]["qa_status"] == "PASS_WITH_LIMITATIONS"
    assert result["final"]["next_recommended_step"] == "LIVE_DECISION_LOG_SIGNAL_FIELDS_PATCH_QA_AUDIT"
    assert result["schema_delta"]["destructive_schema_change_performed"] is False
    assert len(after_df) == len(before_df) == 8
    for col in before_cols:
        assert col in after_df.columns
        left = before_values[col].astype(object).where(pd.notna(before_values[col]), None)
        right = after_df[col].astype(object).where(pd.notna(after_df[col]), None)
        assert list(left) == list(right)
    for col in logger_mod.SIGNAL_FIELD_COLUMNS:
        assert col in after_df.columns
    assert result["backup"]["backup_created"] is True
    assert Path(result["backup"]["backup_path"]).exists()

    # confidence / edge not invented
    assert after_df["confidence"].isna().all() or all(
        v is None or (isinstance(v, float) and pd.isna(v)) for v in after_df["confidence"]
    )
    assert after_df["expected_edge_bps"].isna().all() or all(
        v is None or (isinstance(v, float) and pd.isna(v)) for v in after_df["expected_edge_bps"]
    )
    assert (after_df["confidence_available"] == False).all()  # noqa: E712
    assert (after_df["expected_edge_available"] == False).all()  # noqa: E712
    assert (after_df["total_roundtrip_model_cost_bps"] == 20.0).all()
    assert (after_df["paper_signal_write_allowed"] == False).all()  # noqa: E712
    assert (after_df["paper_loop_allowed"] == False).all()  # noqa: E712

    latest = after_df.iloc[-1]
    assert latest["active_market_context"] == "OBSERVE"
    assert latest["signal_eligibility_status"] == "BLOCKED_STALE_CONTEXT"
    reasons = mod.parse_block_reasons(latest["signal_block_reasons"])
    assert "STALE_CONTEXT" in reasons
    assert "OBSERVE_CONTEXT" in reasons
    assert "MISSING_CONFIDENCE" in reasons
    assert "MISSING_EXPECTED_EDGE" in reasons
    assert latest["paper_action_candidate"] == "NO_TRADE_STALE_CONTEXT"

    for name, digest in ledger_hashes.items():
        assert _sha(ledger / name) == digest
    assert result["safety"]["paper_signal_event_created"] is False
    assert result["safety"]["live_refresh_used"] is False
    assert result["safety"]["production_parquet_mutated"] is False
    assert result["contract"]["logger_contract_patched"] is True


def test_destructive_schema_change_rejected_by_design() -> None:
    # Patch API only adds SIGNAL_FIELD_COLUMNS; never drops base columns.
    assert set(logger_mod.DECISION_COLUMNS_BASE).isdisjoint(set(logger_mod.SIGNAL_FIELD_COLUMNS))
    assert logger_mod.DECISION_COLUMNS[: len(logger_mod.DECISION_COLUMNS_BASE)] == (
        logger_mod.DECISION_COLUMNS_BASE
    )


def test_fresh_long_short_missing_confidence_blocks() -> None:
    now = datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)
    long_row = {
        "active_market_context": "LONG_CONTEXT",
        "decision_written_at_utc": FRESH_TS,
        "decision_stale": False,
    }
    short_row = {
        "active_market_context": "SHORT_CONTEXT",
        "decision_written_at_utc": FRESH_TS,
        "decision_stale": False,
    }
    long_sig = logger_mod.derive_signal_fields(long_row, now_utc=now)
    short_sig = logger_mod.derive_signal_fields(short_row, now_utc=now)
    assert long_sig["signal_eligibility_status"] == "BLOCKED_MISSING_CONFIDENCE"
    assert short_sig["signal_eligibility_status"] == "BLOCKED_MISSING_CONFIDENCE"
    assert long_sig["confidence_available"] is False
    assert short_sig["expected_edge_available"] is False
    assert long_sig["paper_action_candidate"] == "NO_TRADE_MISSING_FIELDS"


def test_fresh_long_short_eligible_fixtures() -> None:
    now = datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)
    long_sig = logger_mod.derive_signal_fields(
        {
            "active_market_context": "LONG_CONTEXT",
            "decision_written_at_utc": FRESH_TS,
            "decision_stale": False,
        },
        now_utc=now,
        confidence=0.72,
        expected_edge_bps=35.0,
    )
    short_sig = logger_mod.derive_signal_fields(
        {
            "active_market_context": "SHORT_CONTEXT",
            "decision_written_at_utc": FRESH_TS,
            "decision_stale": False,
        },
        now_utc=now,
        confidence=0.72,
        expected_edge_bps=35.0,
    )
    assert long_sig["signal_eligibility_status"] == "ELIGIBLE_DIRECTIONAL_SIGNAL"
    assert long_sig["paper_action_candidate"] == "INTENT_OPEN_LONG"
    assert long_sig["intended_side"] == "LONG"
    assert long_sig["order_side"] == "BUY"
    assert long_sig["position_intent"] == "OPEN_LONG"
    assert short_sig["paper_action_candidate"] == "INTENT_OPEN_SHORT"
    assert short_sig["intended_side"] == "SHORT"
    assert short_sig["order_side"] == "SELL"
    assert short_sig["position_intent"] == "OPEN_SHORT"
    assert long_sig["paper_signal_write_allowed"] is False
    assert short_sig["paper_loop_allowed"] is False


def test_edge_le_cost_blocks() -> None:
    now = datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)
    sig = logger_mod.derive_signal_fields(
        {
            "active_market_context": "LONG_CONTEXT",
            "decision_written_at_utc": FRESH_TS,
            "decision_stale": False,
        },
        now_utc=now,
        confidence=0.72,
        expected_edge_bps=20.0,
    )
    assert sig["signal_eligibility_status"] == "BLOCKED_EDGE_BELOW_COST"
    assert sig["paper_action_candidate"] == "NO_TRADE_EDGE_BELOW_COST"


def test_no_exchange_api_import_in_patch_or_logger() -> None:
    assert mod.assert_no_forbidden_imports(PATCH_PATH)
    assert mod.assert_no_forbidden_imports(LOGGER_PATH)


def test_logger_contract_appends_new_fields() -> None:
    row = logger_mod.apply_signal_fields(
        {
            "active_market_context": "OBSERVE",
            "decision_written_at_utc": LATEST_TS,
            "decision_stale": False,
        },
        now_utc=datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc),
    )
    for col in logger_mod.SIGNAL_FIELD_COLUMNS:
        assert col in row
    assert row["total_roundtrip_model_cost_bps"] == 20.0
    assert row["cost_source"] == "DETERMINISTIC_PAPER_SIMULATOR_SPEC"
    assert row["confidence"] is None
    assert row["expected_edge_bps"] is None


def test_production_paths_not_used_by_tmp_patch(tmp_path: Path, monkeypatch) -> None:
    ledger, decision_log, backups, report = _seed_inputs(tmp_path)
    monkeypatch.setattr(mod, "LEDGER_DIR", ledger)
    monkeypatch.setattr(mod, "DRY_RUN_FINAL", ledger / "live_decision_log_signal_fields_dry_run_final_decision.json")
    monkeypatch.setattr(mod, "REQUIRED_SCHEMA", ledger / "live_decision_log_signal_fields_required_schema_spec.json")
    monkeypatch.setattr(mod, "ENRICHMENT_RULES", ledger / "live_decision_log_signal_fields_enrichment_rules.json")
    monkeypatch.setattr(mod, "PATCH_PLAN", ledger / "live_decision_log_signal_fields_patch_plan.json")
    monkeypatch.setattr(mod, "LEDGER_STATUS", ledger / "paper_ledger_status.json")
    # Ensure we do not touch production decision log in this unit test.
    prod = ROOT / "data" / "live" / "context_decision_log.parquet"
    prod_hash = _sha(prod) if prod.exists() else None
    mod.run_patch(
        approved=True,
        research_only=True,
        ledger_dir=ledger,
        decision_log=decision_log,
        backup_dir=backups,
        report_path=report,
        write_reports=False,
    )
    if prod_hash is not None:
        assert _sha(prod) == prod_hash
