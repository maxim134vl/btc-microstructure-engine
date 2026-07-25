"""Tests for Live Decision Log Freshness / Cadence Readiness audit (read-only)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "scripts"
    / "research"
    / "audit_live_decision_log_freshness_cadence_readiness.py"
)
SCHEMA_MOD_PATH = ROOT / "scripts" / "research" / "build_paper_simulator_schema_ledger.py"
LOGGER_PATH = ROOT / "scripts" / "live" / "append_context_decision_log.py"

spec = importlib.util.spec_from_file_location(
    "audit_live_decision_log_freshness_cadence_readiness", MODULE_PATH
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["audit_live_decision_log_freshness_cadence_readiness"] = mod
spec.loader.exec_module(mod)

schema_spec = importlib.util.spec_from_file_location(
    "build_paper_simulator_schema_ledger_for_freshness_cadence_test",
    SCHEMA_MOD_PATH,
)
assert schema_spec and schema_spec.loader
schema_mod = importlib.util.module_from_spec(schema_spec)
sys.modules["build_paper_simulator_schema_ledger_for_freshness_cadence_test"] = (
    schema_mod
)
schema_spec.loader.exec_module(schema_mod)

EXPECTED_SNAP_ID = "corrected_lagged_edge_lookup_02062bba5f9c767f"
FIXTURE_NOW = datetime(2026, 7, 20, 17, 0, tzinfo=timezone.utc)


def _sha(path: Path) -> str | None:
    if not path.exists():
        return None
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


def _lookup_row(
    *,
    context_type: str,
    lifecycle_state: str,
    confidence: float,
    expected_edge: float,
    edge_pass: bool | None = None,
) -> dict:
    action = (
        "INTENT_OPEN_LONG" if context_type == "LONG_CONTEXT" else "INTENT_OPEN_SHORT"
    )
    if edge_pass is None:
        edge_pass = expected_edge > 0.0
    return {
        "corrected_lookup_snapshot_id": EXPECTED_SNAP_ID,
        "lookup_bucket_id": f"BTCUSDT|{context_type}|{lifecycle_state}|{action}|abcd",
        "instrument": "BTCUSDT",
        "context_type": context_type,
        "lifecycle_state": lifecycle_state,
        "action_candidate": action,
        "closed_episode_count": 100 if lifecycle_state == "ACTIVE" else 40,
        "win_rate_after_cost": confidence,
        "confidence": confidence,
        "confidence_probability": confidence,
        "confidence_source": "LAGGED_CONTEXT_OUTCOME_STATISTICS",
        "confidence_available": True,
        "expected_edge_bps": expected_edge,
        "conservative_expected_edge_bps": expected_edge,
        "expected_edge_source": "LAGGED_CONTEXT_EDGE_LOOKUP_NET_AFTER_COST",
        "expected_edge_available": True,
        "expected_edge_basis": "NET_AFTER_COST",
        "signal_threshold_bps": 0.0,
        "signal_threshold_basis": "NET_AFTER_COST_ZERO_THRESHOLD",
        "edge_signal_rule": "NET_EXPECTED_EDGE_GT_ZERO",
        "edge_signal_pass": edge_pass,
        "total_roundtrip_model_cost_bps": 20.0,
        "cost_source": "DETERMINISTIC_PAPER_SIMULATOR_SPEC",
        "cost_handling": "AUDIT_REFERENCE_ONLY_ALREADY_INCLUDED_IN_NET_EDGE",
        "sample_status": (
            "SAMPLE_PREFERRED_READY" if lifecycle_state == "ACTIVE" else "SAMPLE_READY"
        ),
        "lookup_cutoff_ts_utc": "2026-07-20T12:45:00Z",
        "lookup_valid_for_decisions_after_ts_utc": "2026-07-20T12:45:00Z",
        "edge_cost_double_counting_risk_after_correction": False,
        "model_fit_used": False,
        "retraining_used": False,
    }


def _decision_row(i: int, *, latest: bool = False) -> dict:
    if latest:
        return {
            "decision_id": f"d{i}",
            "candle_timestamp": "2026-07-19T17:45:00Z",
            "candle_close_time_utc": "2026-07-19T18:00:00Z",
            "decision_written_at_utc": "2026-07-19T18:03:13.003997Z",
            "decision_timestamp_utc": "2026-07-19T18:00:00Z",
            "active_market_context": "OBSERVE",
            "lifecycle_state": "CANDIDATE",
            "decision_stale": False,
            "freshness_status": "STALE",
            "is_stale": True,
            "confidence": None,
            "confidence_available": False,
            "expected_edge_bps": None,
            "expected_edge_available": False,
            "signal_eligibility_status": "BLOCKED_STALE_CONTEXT",
            "signal_block_reasons": '["STALE_CONTEXT","OBSERVE_CONTEXT"]',
            "paper_action_candidate": "NO_TRADE_STALE_CONTEXT",
            "paper_signal_write_allowed": False,
            "paper_loop_allowed": False,
        }
    # Mostly 15m cadence with one larger gap (matches live pattern).
    stamps = [
        "2026-07-19T13:15:00Z",
        "2026-07-19T14:15:00Z",
        "2026-07-19T14:30:00Z",
        "2026-07-19T17:00:00Z",
        "2026-07-19T17:15:00Z",
        "2026-07-19T17:30:00Z",
        "2026-07-19T17:45:00Z",
    ]
    ts = stamps[i]
    return {
        "decision_id": f"d{i}",
        "candle_timestamp": ts,
        "candle_close_time_utc": ts,
        "decision_written_at_utc": ts,
        "decision_timestamp_utc": ts,
        "active_market_context": "OBSERVE" if i != 1 else "LONG_CONTEXT",
        "lifecycle_state": "CANDIDATE",
        "decision_stale": True,
        "freshness_status": "STALE",
        "is_stale": True,
        "confidence": None,
        "confidence_available": False,
        "expected_edge_bps": None,
        "expected_edge_available": False,
        "signal_eligibility_status": "BLOCKED_STALE_CONTEXT",
        "signal_block_reasons": '["STALE_CONTEXT","OBSERVE_CONTEXT"]',
        "paper_action_candidate": "NO_TRADE_STALE_CONTEXT",
        "paper_signal_write_allowed": False,
        "paper_loop_allowed": False,
    }


def _prepare_fixture(tmp_path: Path) -> dict[str, Path]:
    ledger = tmp_path / "paper_simulator"
    live = tmp_path / "live"
    cognition = tmp_path / "cognition"
    docs = tmp_path / "docs"
    scripts_live = tmp_path / "scripts" / "live"
    ledger.mkdir(parents=True)
    live.mkdir(parents=True)
    cognition.mkdir(parents=True)
    docs.mkdir(parents=True)
    scripts_live.mkdir(parents=True)

    _write_empty_ledgers(ledger)
    _seed_counts(ledger)

    rows = [
        _lookup_row(
            context_type="LONG_CONTEXT",
            lifecycle_state="ACTIVE",
            confidence=0.54,
            expected_edge=8.3,
        ),
        _lookup_row(
            context_type="LONG_CONTEXT",
            lifecycle_state="CHALLENGED",
            confidence=0.60,
            expected_edge=4.7,
        ),
        _lookup_row(
            context_type="SHORT_CONTEXT",
            lifecycle_state="ACTIVE",
            confidence=0.64,
            expected_edge=16.6,
        ),
        _lookup_row(
            context_type="SHORT_CONTEXT",
            lifecycle_state="CHALLENGED",
            confidence=0.71,
            expected_edge=10.8,
        ),
    ]
    snapshot = ledger / "corrected_lagged_context_edge_lookup_snapshot.parquet"
    pd.DataFrame(rows).to_parquet(snapshot, index=False)
    _write_json(
        ledger / "corrected_lagged_context_edge_lookup_snapshot_manifest.json",
        {
            "corrected_lookup_snapshot_id": EXPECTED_SNAP_ID,
            "lookup_cutoff_ts_utc": "2026-07-20T12:45:00Z",
            "lookup_valid_for_decisions_after_ts_utc": "2026-07-20T12:45:00Z",
            "total_lookup_buckets": 4,
        },
    )

    decision_log = live / "context_decision_log.parquet"
    decision_rows = [_decision_row(i) for i in range(7)]
    decision_rows.append(_decision_row(7, latest=True))
    pd.DataFrame(decision_rows).to_parquet(decision_log, index=False)

    feed = live / "live_market_feed.parquet"
    pd.DataFrame(
        {
            "timestamp": [
                "2026-07-20T16:30:00Z",
                "2026-07-20T16:45:00Z",
            ],
            "close": [100000.0, 100010.0],
        }
    ).to_parquet(feed, index=False)

    logger_copy = scripts_live / "append_context_decision_log.py"
    logger_copy.write_text(LOGGER_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    _write_json(
        ledger / "rerun_live_decision_adapter_qa_final_decision.json",
        {
            "qa_decision": (
                "RERUN_LIVE_DECISION_TO_PAPER_SIGNAL_ADAPTER_QA_PASS_WITH_LIMITATIONS"
            ),
            "qa_status": "PASS_WITH_LIMITATIONS",
            "next_recommended_step": (
                "LIVE_DECISION_LOG_FRESHNESS_CADENCE_READINESS_AUDIT"
            ),
        },
    )
    _write_json(
        ledger / "logger_lookup_integration_patch_qa_final_decision.json",
        {
            "qa_decision": "LOGGER_LOOKUP_INTEGRATION_PATCH_QA_PASS_WITH_LIMITATIONS",
            "qa_status": "PASS_WITH_LIMITATIONS",
            "logger_patch_verified": True,
        },
    )

    return {
        "ledger": ledger,
        "snapshot": snapshot,
        "manifest": ledger
        / "corrected_lagged_context_edge_lookup_snapshot_manifest.json",
        "adapter_qa": ledger / "rerun_live_decision_adapter_qa_final_decision.json",
        "patch_qa": ledger / "logger_lookup_integration_patch_qa_final_decision.json",
        "decision_log": decision_log,
        "live_feed": feed,
        "logger_script": logger_copy,
        "final_ctx": cognition / "final_market_context_memory.parquet",
        "lifecycle": cognition / "market_context_lifecycle_memory.parquet",
        "episodes": cognition / "market_context_lifecycle_episodes.parquet",
        "report": docs / "LIVE_DECISION_LOG_FRESHNESS_CADENCE_READINESS_AUDIT.md",
    }


def _run_audit(paths: dict[str, Path]):
    return mod.run_audit(
        ledger_dir=paths["ledger"],
        decision_log_path=paths["decision_log"],
        corrected_snapshot=paths["snapshot"],
        corrected_manifest=paths["manifest"],
        logger_script=paths["logger_script"],
        adapter_qa_final=paths["adapter_qa"],
        logger_patch_qa_final=paths["patch_qa"],
        live_feed=paths["live_feed"],
        final_ctx=paths["final_ctx"],
        lifecycle=paths["lifecycle"],
        episodes=paths["episodes"],
        report_path=paths["report"],
        write_reports=True,
        expected_logger_hash=_sha(paths["logger_script"]),
        expected_live_log_hash=_sha(paths["decision_log"]),
        expected_lookup_hash=_sha(paths["snapshot"]),
        now_utc=FIXTURE_NOW,
    )


def test_missing_inputs_block_audit(tmp_path: Path) -> None:
    # 1) missing adapter QA blocks
    paths = _prepare_fixture(tmp_path / "missing_adapter")
    paths["adapter_qa"].unlink()
    log_before = _sha(paths["decision_log"])
    logger_before = _sha(paths["logger_script"])
    lookup_before = _sha(paths["snapshot"])
    result = _run_audit(paths)
    assert result["final"]["qa_status"] == "BLOCKED"
    assert result["final"]["status"] == mod.BLOCKED_INVALID
    assert _sha(paths["decision_log"]) == log_before
    assert _sha(paths["logger_script"]) == logger_before
    assert _sha(paths["snapshot"]) == lookup_before

    # 2) missing live decision log blocks
    paths2 = _prepare_fixture(tmp_path / "missing_live")
    paths2["decision_log"].unlink()
    result2 = _run_audit(paths2)
    assert result2["final"]["qa_status"] == "BLOCKED"
    assert result2["final"]["status"] == mod.BLOCKED_INVALID
    assert "live_decision_log" in result2["input"]["missing"]

    # 3) missing corrected lookup blocks
    paths3 = _prepare_fixture(tmp_path / "missing_lookup")
    paths3["snapshot"].unlink()
    result3 = _run_audit(paths3)
    assert result3["final"]["qa_status"] == "BLOCKED"
    assert result3["final"]["status"] == mod.BLOCKED_INVALID
    assert "corrected_lookup_snapshot" in result3["input"]["missing"]

    # 4) missing required logger funcs blocks
    paths4 = _prepare_fixture(tmp_path / "missing_funcs")
    src = paths4["logger_script"].read_text(encoding="utf-8")
    for name in mod.REQUIRED_LOGGER_FUNCS:
        src = src.replace(f"def {name}(", f"def _{name}_removed(")
    paths4["logger_script"].write_text(src, encoding="utf-8")
    result4 = _run_audit(paths4)
    assert result4["final"]["qa_status"] == "BLOCKED"
    assert "required_logger_functions_missing" in result4["input"]["missing"]


def test_freshness_cadence_readiness_full_30_points(tmp_path: Path) -> None:
    paths = _prepare_fixture(tmp_path)
    log_before = _sha(paths["decision_log"])
    logger_before = _sha(paths["logger_script"])
    lookup_before = _sha(paths["snapshot"])
    ledger_before = {
        name: _sha(paths["ledger"] / name) for name in mod.LEDGER_PARQUETS
    }

    result = _run_audit(paths)
    final = result["final"]
    inventory = result["inventory"]
    cutoff = result["lookup_cutoff"]
    latest = result["latest"]
    gap = result["gap"]
    signal_fields = result["signal_fields"]
    adapter = result["adapter_readiness"]
    refresh = result["refresh_plan"]
    safety = result["safety"]

    # 5/6 inventory
    assert inventory["decision_log_rows"] == 8
    assert inventory["latest_decision_ts_utc"] == "2026-07-19T18:00:00Z"
    assert inventory["latest_context"] == "OBSERVE"
    assert inventory["latest_is_stale"] is True
    assert inventory["corrected_lookup_snapshot_id"] == EXPECTED_SNAP_ID
    assert inventory["lookup_cutoff_ts_utc"] == "2026-07-20T12:45:00Z"
    assert inventory["inventory_status"] == "PASS_WITH_LIMITATIONS"

    # 7/8 lookup cutoff
    assert cutoff["decisions_after_lookup_cutoff_count"] == 0
    assert cutoff["live_lookup_cadence_ready"] is False
    assert cutoff["lookup_cutoff_check_status"] == "PASS_WITH_LIMITATIONS"

    # 9-14 latest decision
    assert latest["latest_before_lookup_cutoff"] is True
    assert latest["latest_is_directional"] is False
    assert latest["latest_has_confidence"] is False
    assert latest["latest_has_expected_edge_bps"] is False
    assert latest["latest_adapter_eligible_now"] is False
    reasons = set(latest["signal_block_reasons"])
    assert "STALE_CONTEXT" in reasons
    assert "OBSERVE_CONTEXT" in reasons
    assert "LOOKUP_NOT_VALID_FOR_DECISION_TIME" in reasons
    assert latest["latest_decision_check_status"] == "PASS_WITH_LIMITATIONS"

    # 15-17 gap / cadence
    assert gap["median_interval_minutes"] == 15.0
    assert gap["max_interval_minutes"] == 150.0
    assert gap["gap_count_over_expected_interval"] >= 1
    assert gap["cadence_after_patch_available"] is False
    assert gap["cadence_ready_for_paper_signal"] is False
    assert gap["last_gap_minutes_to_now_utc"] > 30
    assert gap["gap_check_status"] == "PASS_WITH_LIMITATIONS"

    # 18-20 signal fields
    assert "confidence" in signal_fields["signal_fields_present"]
    assert "expected_edge_bps" in signal_fields["signal_fields_present"]
    assert "paper_signal_write_allowed" in signal_fields["signal_fields_present"]
    assert signal_fields["rows_with_paper_signal_write_allowed_true"] == 0
    assert signal_fields["rows_with_paper_loop_allowed_true"] == 0
    assert signal_fields["signal_fields_check_status"] in {
        "PASS",
        "PASS_WITH_LIMITATIONS",
    }

    # 21-23 adapter readiness
    assert adapter["corrected_lookup_ready"] is True
    assert adapter["logger_patch_qa_passed"] is True
    assert adapter["adapter_qa_passed"] is True
    assert adapter["adapter_readiness_now"] is False
    reason_set = set(adapter["adapter_not_ready_reasons"])
    assert "NO_DECISIONS_AFTER_LOOKUP_CUTOFF" in reason_set
    assert "LATEST_DECISION_STALE" in reason_set
    assert "LATEST_DECISION_OBSERVE" in reason_set
    assert "LIVE_DECISION_CADENCE_NOT_PROVEN_AFTER_PATCH" in reason_set
    assert adapter["adapter_readiness_check_status"] == "PASS_WITH_LIMITATIONS"

    # 24 refresh plan
    assert refresh["refresh_required"] is True
    assert refresh["required_next_operation"] == (
        "SINGLE_LIVE_CONTEXT_REFRESH_AND_DECISION_LOG_APPEND_DRY_RUN_OR_APPROVED_ONE_SHOT"
    )
    assert refresh["no_loop"] is True
    assert refresh["no_sleep"] is True
    assert refresh["user_approval_required_for_live_decision_log_write"] is True
    assert refresh["live_decision_log_write_allowed_now"] is False
    assert refresh["paper_signal_write_allowed_now"] is False
    assert refresh["paper_loop_allowed_now"] is False
    assert refresh["required_refresh_plan_status"] == "PASS"

    # 25-26 no-write safety / hashes unchanged
    assert _sha(paths["decision_log"]) == log_before
    assert _sha(paths["logger_script"]) == logger_before
    assert _sha(paths["snapshot"]) == lookup_before
    for name, before in ledger_before.items():
        assert _sha(paths["ledger"] / name) == before
    assert safety["logger_script_mutated_by_audit"] is False
    assert safety["live_decision_log_mutated_by_audit"] is False
    assert safety["corrected_lookup_mutated_by_audit"] is False
    assert safety["paper_ledgers_mutated_by_audit"] is False
    assert safety["live_refresh_used"] is False
    assert safety["exchange_api_call_used"] is False
    assert safety["model_fit_performed"] is False
    assert safety["committed"] is False
    assert safety["no_write_safety_status"] == "PASS"

    # 27-29 final decision
    assert (
        final["status"]
        == "LIVE_DECISION_LOG_FRESHNESS_CADENCE_READINESS_BLOCKED_WITH_LIMITATIONS"
    )
    assert final["qa_status"] == "PASS_WITH_LIMITATIONS"
    assert final["logger_lookup_patch_ready"] is True
    assert final["adapter_contract_ready"] is True
    assert final["corrected_lookup_ready"] is True
    assert final["live_decision_log_rows"] == 8
    assert final["decisions_after_lookup_cutoff_count"] == 0
    assert final["latest_decision_fresh"] is False
    assert final["latest_decision_adapter_eligible_now"] is False
    assert final["live_decision_cadence_ready"] is False
    assert final["live_decision_log_write_allowed_now"] is False
    assert final["paper_signal_write_allowed_now"] is False
    assert final["paper_loop_allowed_now"] is False
    assert final["run_readiness_status"] == "NOT_READY_TO_RUN_PAPER_TRADING"
    assert final["next_recommended_step"] == (
        "USER_APPROVAL_FOR_SINGLE_LIVE_CONTEXT_REFRESH_AND_DECISION_LOG_APPEND_NO_PAPER_SIGNAL"
    )

    # 30 forbidden imports / no sleep / required statement
    assert mod.assert_no_forbidden_imports(MODULE_PATH) is True
    assert mod.assert_no_loop_or_sleep(MODULE_PATH) is True
    assert paths["report"].exists()
    assert mod.REQUIRED_STATEMENT in paths["report"].read_text(encoding="utf-8")
    for name in mod.OUTPUT_NAMES.values():
        assert (paths["ledger"] / name).exists()
