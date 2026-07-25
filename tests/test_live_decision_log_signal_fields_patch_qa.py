"""Tests for live decision log signal fields patch QA audit (read-only)."""

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
MODULE_PATH = (
    ROOT / "scripts" / "research" / "audit_live_decision_log_signal_fields_patch_qa.py"
)
LOGGER_PATH = ROOT / "scripts" / "live" / "append_context_decision_log.py"
SCHEMA_MOD_PATH = ROOT / "scripts" / "research" / "build_paper_simulator_schema_ledger.py"

spec = importlib.util.spec_from_file_location(
    "audit_live_decision_log_signal_fields_patch_qa", MODULE_PATH
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["audit_live_decision_log_signal_fields_patch_qa"] = mod
spec.loader.exec_module(mod)

logger_spec = importlib.util.spec_from_file_location(
    "append_context_decision_log_for_signal_fields_patch_qa_test", LOGGER_PATH
)
assert logger_spec and logger_spec.loader
logger_mod = importlib.util.module_from_spec(logger_spec)
sys.modules["append_context_decision_log_for_signal_fields_patch_qa_test"] = logger_mod
logger_spec.loader.exec_module(logger_mod)

schema_spec = importlib.util.spec_from_file_location(
    "build_paper_simulator_schema_ledger_for_signal_fields_patch_qa_test",
    SCHEMA_MOD_PATH,
)
assert schema_spec and schema_spec.loader
schema_mod = importlib.util.module_from_spec(schema_spec)
sys.modules["build_paper_simulator_schema_ledger_for_signal_fields_patch_qa_test"] = (
    schema_mod
)
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


def _base_row(i: int, *, context: str, written_at: str) -> dict:
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


def _seed_backup_and_patched(live_dir: Path) -> tuple[Path, Path, Path]:
    backup_dir = live_dir / "context_decision_log_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = (
        backup_dir / "context_decision_log_before_signal_fields_patch_20260720_130200.parquet"
    )
    decision_log = live_dir / "context_decision_log.parquet"

    rows = []
    for i in range(7):
        rows.append(_base_row(i, context="LONG_CONTEXT", written_at=FRESH_TS))
    rows.append(_base_row(7, context="OBSERVE", written_at=LATEST_TS))
    backup_df = pd.DataFrame(rows)
    assert len(backup_df.columns) == 45
    backup_df.to_parquet(backup_path, index=False)

    now = datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc)
    patched_rows = []
    for _, series in backup_df.iterrows():
        row = series.to_dict()
        signal = logger_mod.derive_signal_fields(row, now_utc=now)
        out = dict(row)
        out.update(signal)
        patched_rows.append(out)
    patched = pd.DataFrame(patched_rows)
    patched.to_parquet(decision_log, index=False)

    digest = _sha(backup_path)
    manifest = {
        "generated_at_utc": "2026-07-20T13:02:00Z",
        "source_path": str(decision_log),
        "backup_path": str(backup_path),
        "original_sha256": digest,
        "original_rows": 8,
        "original_columns": list(backup_df.columns),
        "backup_sha256": digest,
        "backup_status": "CREATED",
    }
    manifest_path = backup_path.with_suffix(".manifest.json")
    _write_json(manifest_path, manifest)
    return decision_log, backup_path, manifest_path


def _write_patch_reports(ledger: Path) -> None:
    final = {
        "status": "LIVE_DECISION_LOG_SIGNAL_FIELDS_PATCH_APPLIED_WITH_LIMITATIONS",
        "qa_status": "PASS_WITH_LIMITATIONS",
        "additive_patch_applied": True,
        "destructive_schema_change_performed": False,
        "confidence_source_available": False,
        "expected_edge_source_available": False,
        "next_recommended_step": "LIVE_DECISION_LOG_SIGNAL_FIELDS_PATCH_QA_AUDIT",
    }
    for name in mod.PATCH_REPORT_NAMES:
        if name.endswith("final_decision.json"):
            _write_json(ledger / name, final)
        elif name.endswith("logger_contract.json"):
            _write_json(
                ledger / name,
                {
                    "logger_contract_patched": True,
                    "future_rows_include_signal_fields": True,
                    "confidence_invented": False,
                    "expected_edge_invented": False,
                    "deterministic_cost_source_added": True,
                    "paper_signal_event_write_added": False,
                    "paper_ledger_write_added": False,
                    "exchange_api_call_added": False,
                    "logger_contract_status": "PASS",
                },
            )
        elif name.endswith("safety.json"):
            _write_json(
                ledger / name,
                {
                    "backup_created": True,
                    "paper_ledgers_unchanged": True,
                    "committed": False,
                },
            )
        else:
            _write_json(ledger / name, {"ok": True})


def _setup(tmp: Path) -> dict[str, Path]:
    ledger = tmp / "paper_simulator"
    live = tmp / "live"
    report = tmp / "LIVE_DECISION_LOG_SIGNAL_FIELDS_PATCH_QA_AUDIT.md"
    _write_empty_ledgers(ledger)
    _seed_counts(ledger)
    decision_log, backup_path, manifest_path = _seed_backup_and_patched(live)
    _write_patch_reports(ledger)
    return {
        "ledger": ledger,
        "decision_log": decision_log,
        "backup_path": backup_path,
        "manifest_path": manifest_path,
        "report": report,
    }


def test_missing_patch_reports_blocks_qa(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    (paths["ledger"] / "live_decision_log_signal_fields_patch_final_decision.json").unlink()
    result = mod.run_audit(
        ledger_dir=paths["ledger"],
        decision_log=paths["decision_log"],
        backup_path=paths["backup_path"],
        backup_manifest=paths["manifest_path"],
        report_path=paths["report"],
        write_reports=True,
    )
    assert result["final"]["qa_decision"] == "BLOCKED_INVALID_SIGNAL_FIELDS_PATCH_QA_INPUTS"


def test_missing_backup_blocks_qa(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    paths["backup_path"].unlink()
    result = mod.run_audit(
        ledger_dir=paths["ledger"],
        decision_log=paths["decision_log"],
        backup_path=paths["backup_path"],
        backup_manifest=paths["manifest_path"],
        report_path=paths["report"],
        write_reports=True,
    )
    assert result["final"]["qa_decision"] == "BLOCKED_INVALID_SIGNAL_FIELDS_PATCH_QA_INPUTS"


def test_full_qa_pass_with_limitations(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    log_hash = _sha(paths["decision_log"])
    backup_hash = _sha(paths["backup_path"])
    ledger_hashes = {name: _sha(paths["ledger"] / name) for name in mod.LEDGER_PARQUETS}

    result = mod.run_audit(
        ledger_dir=paths["ledger"],
        decision_log=paths["decision_log"],
        backup_path=paths["backup_path"],
        backup_manifest=paths["manifest_path"],
        report_path=paths["report"],
        write_reports=True,
    )

    assert result["input"]["input_validation_status"] == "VALID"
    assert result["backup"]["backup_check_status"] == "PASS"
    assert result["backup"]["backup_rows"] == 8
    assert result["backup"]["backup_columns"] == 45
    assert result["backup"]["backup_hash_matches_manifest"] is True

    assert result["schema"]["schema_check_status"] == "PASS"
    assert result["schema"]["live_decision_log_rows_after"] == 8
    assert result["schema"]["additive_columns_count"] == 23
    assert result["schema"]["destructive_schema_change_performed"] is False
    assert result["schema"]["old_columns_preserved"] is True
    assert result["schema"]["old_values_preserved"] is True
    assert result["schema"]["only_additive_columns_added"] is True
    assert result["schema"]["required_signal_columns_exist"] is True

    backfill = result["backfill"]
    assert backfill["backfill_check_status"] == "PASS"
    assert backfill["latest_context"] == "OBSERVE"
    assert backfill["latest_is_stale"] is True
    assert backfill["confidence"] is None
    assert backfill["confidence_available"] is False
    assert backfill["expected_edge_bps"] is None
    assert backfill["expected_edge_available"] is False
    assert backfill["total_roundtrip_model_cost_bps"] == 20.0
    assert backfill["signal_eligibility_status"] == "BLOCKED_STALE_CONTEXT"
    for reason in (
        "STALE_CONTEXT",
        "OBSERVE_CONTEXT",
        "MISSING_CONFIDENCE",
        "MISSING_EXPECTED_EDGE",
    ):
        assert reason in backfill["signal_block_reasons"]
    assert backfill["paper_signal_write_allowed"] is False
    assert backfill["paper_loop_allowed"] is False

    contract = result["contract"]
    assert contract["logger_contract_status"] == "PASS"
    assert contract["future_rows_include_signal_fields"] is True
    assert contract["paper_signal_event_write_added"] is False
    assert contract["exchange_api_call_added"] is False
    assert contract["confidence_invented"] is False
    assert contract["expected_edge_invented"] is False
    assert contract["deterministic_cost_source_added"] is True

    der = result["derivation"]
    assert der["signal_derivation_status"] == "PASS"
    assert der["stale_observe_derivation"]["pass"] is True
    assert der["fresh_observe_derivation"]["pass"] is True
    assert der["fresh_long_missing_confidence_derivation"]["pass"] is True
    assert der["fresh_short_missing_confidence_derivation"]["pass"] is True
    assert der["fresh_long_missing_edge_derivation"]["pass"] is True
    assert der["edge_below_cost_derivation"]["pass"] is True
    assert der["eligible_long_derivation"]["pass"] is True
    assert der["eligible_short_derivation"]["pass"] is True

    safety = result["safety"]
    assert safety["live_decision_log_mutated_by_qa"] is False
    assert safety["backup_mutated_by_qa"] is False
    assert safety["paper_ledgers_mutated_by_qa"] is False
    assert safety["live_refresh_used"] is False
    assert safety["production_parquet_mutated"] is False
    assert safety["no_write_safety_status"] == "PASS"

    final = result["final"]
    assert final["qa_decision"] == (
        "LIVE_DECISION_LOG_SIGNAL_FIELDS_PATCH_QA_PASS_WITH_LIMITATIONS"
    )
    assert final["qa_status"] == "PASS_WITH_LIMITATIONS"
    assert final["next_recommended_step"] == (
        "BUILD_CONFIDENCE_AND_EXPECTED_EDGE_SOURCE_READINESS_AUDIT"
    )

    assert _sha(paths["decision_log"]) == log_hash
    assert _sha(paths["backup_path"]) == backup_hash
    for name, digest in ledger_hashes.items():
        assert _sha(paths["ledger"] / name) == digest


def test_production_paths_untouched_by_tmp_qa(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    prod = ROOT / "data" / "live" / "context_decision_log.parquet"
    prod_hash = _sha(prod) if prod.exists() else None
    mod.run_audit(
        ledger_dir=paths["ledger"],
        decision_log=paths["decision_log"],
        backup_path=paths["backup_path"],
        backup_manifest=paths["manifest_path"],
        report_path=paths["report"],
        write_reports=False,
    )
    if prod_hash is not None:
        assert _sha(prod) == prod_hash
