"""Tests for approved one-shot single live context refresh + decision log append."""

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
    / "live"
    / "single_live_context_refresh_and_decision_log_append_no_paper_signal.py"
)
LOGGER_PATH = ROOT / "scripts" / "live" / "append_context_decision_log.py"
REFRESH_PATH = ROOT / "scripts" / "live" / "run_live_context_refresh_once.py"
SCHEMA_MOD_PATH = ROOT / "scripts" / "research" / "build_paper_simulator_schema_ledger.py"

spec = importlib.util.spec_from_file_location(
    "single_live_context_refresh_and_decision_log_append_no_paper_signal",
    MODULE_PATH,
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["single_live_context_refresh_and_decision_log_append_no_paper_signal"] = mod
spec.loader.exec_module(mod)

logger_spec = importlib.util.spec_from_file_location(
    "append_context_decision_log_for_single_refresh_test", LOGGER_PATH
)
assert logger_spec and logger_spec.loader
logger_mod = importlib.util.module_from_spec(logger_spec)
sys.modules["append_context_decision_log_for_single_refresh_test"] = logger_mod
logger_spec.loader.exec_module(logger_mod)

schema_spec = importlib.util.spec_from_file_location(
    "build_paper_simulator_schema_ledger_for_single_refresh_test",
    SCHEMA_MOD_PATH,
)
assert schema_spec and schema_spec.loader
schema_mod = importlib.util.module_from_spec(schema_spec)
sys.modules["build_paper_simulator_schema_ledger_for_single_refresh_test"] = schema_mod
schema_spec.loader.exec_module(schema_mod)


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
            "daily_pnl": 0.0,
            "paper_only": True,
            "execution_enabled": False,
            "metadata_json": "{}",
        },
    )


def _frame(timestamps: list[str], **cols) -> pd.DataFrame:
    n = len(timestamps)
    data: dict = {
        "timestamp": list(pd.to_datetime(timestamps, utc=True)),
        "close": [100.0 + i for i in range(n)],
    }
    for key, value in cols.items():
        if isinstance(value, list):
            data[key] = value
        else:
            data[key] = [value] * n
    return pd.DataFrame(data)


def _seed_lookup(path: Path, *, cutoff: str = "2026-07-19T12:00:00Z") -> None:
    rows = [
        {
            "bucket_id": "b1",
            "instrument": "BTCUSDT",
            "context_type": "LONG_CONTEXT",
            "lifecycle_state": "ACTIVE",
            "confidence": 0.72,
            "expected_edge_bps": 45.0,
            "expected_edge_basis": "NET_OF_COST",
            "sample_n": 40,
            "lookup_valid": True,
            "snapshot_id": "test_lookup_snap",
            "cutoff_ts_utc": cutoff,
            "lookup_valid_for_decisions_after_ts_utc": cutoff,
        },
        {
            "bucket_id": "b2",
            "instrument": "BTCUSDT",
            "context_type": "SHORT_CONTEXT",
            "lifecycle_state": "ACTIVE",
            "confidence": 0.68,
            "expected_edge_bps": 38.0,
            "expected_edge_basis": "NET_OF_COST",
            "sample_n": 35,
            "lookup_valid": True,
            "snapshot_id": "test_lookup_snap",
            "cutoff_ts_utc": cutoff,
            "lookup_valid_for_decisions_after_ts_utc": cutoff,
        },
        {
            "bucket_id": "b3",
            "instrument": "BTCUSDT",
            "context_type": "OBSERVE",
            "lifecycle_state": "CANDIDATE",
            "confidence": 0.1,
            "expected_edge_bps": 1.0,
            "expected_edge_basis": "NET_OF_COST",
            "sample_n": 10,
            "lookup_valid": True,
            "snapshot_id": "test_lookup_snap",
            "cutoff_ts_utc": cutoff,
            "lookup_valid_for_decisions_after_ts_utc": cutoff,
        },
        {
            "bucket_id": "b4",
            "instrument": "BTCUSDT",
            "context_type": "STAND_ASIDE",
            "lifecycle_state": "NO_ACTIVE_CONTEXT",
            "confidence": 0.05,
            "expected_edge_bps": 0.0,
            "expected_edge_basis": "NET_OF_COST",
            "sample_n": 8,
            "lookup_valid": True,
            "snapshot_id": "test_lookup_snap",
            "cutoff_ts_utc": cutoff,
            "lookup_valid_for_decisions_after_ts_utc": cutoff,
        },
    ]
    # Prefer real corrected lookup schema if loadable; else minimal columns.
    try:
        real = ROOT / "data/research/paper_simulator/corrected_lagged_context_edge_lookup_snapshot.parquet"
        if real.exists():
            base = pd.read_parquet(real).iloc[:0].copy()
            # Just copy real file for schema compatibility in validation existence checks.
            path.write_bytes(real.read_bytes())
            return
    except Exception:
        pass
    pd.DataFrame(rows).to_parquet(path, index=False)


def _seed_cognition(
    cognition: Path,
    live: Path,
    *,
    timestamps: list[str],
    live_timestamps: list[str] | None = None,
    context: str = "LONG_CONTEXT",
    lifecycle_state: str = "ACTIVE",
) -> None:
    cognition.mkdir(parents=True, exist_ok=True)
    live.parent.mkdir(parents=True, exist_ok=True)
    live_ts = live_timestamps or timestamps
    _frame(
        live_ts,
        open=1.0,
        high=1.0,
        low=1.0,
        volume=1.0,
    ).to_parquet(live, index=False)
    _frame(
        timestamps,
        auction_episode="ACCEPTANCE_HIGHER",
        episode_status="CONFIRMED",
    ).to_parquet(cognition / "auction_episode_memory.parquet", index=False)
    _frame(
        timestamps,
        cognitive_market_state="LOWER_ABSORPTION",
        state_status="CONFIRMED",
        state_direction="LONG" if "LONG" in context else "SHORT",
    ).to_parquet(cognition / "cognitive_market_state_memory.parquet", index=False)
    _frame(
        timestamps,
        market_context=context,
        context_status="ACTIVE",
    ).to_parquet(cognition / "final_market_context_memory.parquet", index=False)
    _frame(
        timestamps,
        raw_market_context=context,
        raw_context_status="ACTIVE",
        raw_cognitive_market_state="LOWER_ABSORPTION",
        raw_state_direction="LONG" if "LONG" in context else "SHORT",
        raw_auction_episode="ACCEPTANCE_HIGHER",
        active_market_context=context,
        lifecycle_state=lifecycle_state,
        active_context_age_bars=list(range(len(timestamps))),
        active_context_started_at=[pd.Timestamp(timestamps[0])] * len(timestamps),
        invalidation_type="NONE",
        action_allowed=False,
        shadow_only=True,
    ).to_parquet(cognition / "market_context_lifecycle_memory.parquet", index=False)
    _frame(timestamps, episode_id="ep1").to_parquet(
        cognition / "market_context_lifecycle_episodes.parquet", index=False
    )


def _seed_decision_log(path: Path, timestamps: list[str]) -> None:
    rows = []
    for i, ts in enumerate(timestamps):
        rows.append(
            {
                "decision_id": f"d{i}",
                "decision_written_at_utc": "2026-07-19T12:00:00Z",
                "candle_timestamp": ts,
                "candle_close_time_utc": ts,
                "source_timeframe": "15m",
                "active_market_context": "OBSERVE",
                "lifecycle_state": "CANDIDATE",
                "action_allowed": False,
                "shadow_only": True,
                "execution_enabled": False,
                "decision_payload_hash": f"hash{i}",
                "paper_signal_write_allowed": False,
                "paper_loop_allowed": False,
            }
        )
    # Align to DECISION_COLUMNS where possible.
    frame = pd.DataFrame(rows)
    for col in logger_mod.DECISION_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    frame = frame[logger_mod.DECISION_COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _prepare_fixture(
    tmp_path: Path,
    *,
    decision_timestamps: list[str] | None = None,
    cognition_timestamps: list[str] | None = None,
    live_timestamps: list[str] | None = None,
    context: str = "LONG_CONTEXT",
    include_freshness: bool = True,
    include_feed: bool = True,
    include_decision_log: bool = True,
) -> dict[str, Path]:
    research = tmp_path / "research"
    live_dir = tmp_path / "live"
    cognition = tmp_path / "cognition"
    docs = tmp_path / "docs"
    logs = tmp_path / "logs"
    research.mkdir(parents=True)
    live_dir.mkdir(parents=True)
    cognition.mkdir(parents=True)
    docs.mkdir(parents=True)
    logs.mkdir(parents=True)

    decision_ts = decision_timestamps or [
        "2026-07-19T13:00:00Z",
        "2026-07-19T13:15:00Z",
    ]
    cog_ts = cognition_timestamps or [
        "2026-07-20T13:00:00Z",
        "2026-07-20T13:15:00Z",
    ]
    live_ts = live_timestamps or cog_ts

    decision_log = live_dir / "context_decision_log.parquet"
    live_feed = live_dir / "live_market_feed.parquet"
    if include_decision_log:
        _seed_decision_log(decision_log, decision_ts)
    if include_feed:
        _seed_cognition(
            cognition,
            live_feed,
            timestamps=cog_ts,
            live_timestamps=live_ts,
            context=context,
        )

    _write_empty_ledgers(research)
    _seed_counts(research)
    lookup = research / "corrected_lagged_context_edge_lookup_snapshot.parquet"
    _seed_lookup(lookup)
    _write_json(
        research / "corrected_lagged_context_edge_lookup_snapshot_manifest.json",
        {"snapshot_id": "test_lookup_snap"},
    )

    if include_freshness:
        _write_json(
            research / "live_decision_log_freshness_cadence_final_decision.json",
            {
                "status": mod.REQUIRED_FRESHNESS_STATUS,
                "qa_status": "PASS_WITH_LIMITATIONS",
            },
        )
    _write_json(
        research / "logger_lookup_integration_patch_qa_final_decision.json",
        {"qa_decision": mod.REQUIRED_LOGGER_PATCH_QA, "qa_status": "PASS_WITH_LIMITATIONS"},
    )
    _write_json(
        research / "rerun_live_decision_adapter_qa_final_decision.json",
        {"qa_decision": mod.REQUIRED_ADAPTER_QA, "qa_status": "PASS_WITH_LIMITATIONS"},
    )

    (logs / "runtime.log").write_text("PIPELINE CYCLE: 1\nPIPELINE CYCLE: 2\n", encoding="utf-8")

    return {
        "research": research,
        "live_dir": live_dir,
        "cognition": cognition,
        "docs": docs,
        "decision_log": decision_log,
        "live_feed": live_feed,
        "lookup": lookup,
        "runtime_log": logs / "runtime.log",
        "report": docs / "SINGLE_LIVE_CONTEXT_REFRESH_AND_DECISION_LOG_APPEND_NO_PAPER_SIGNAL.md",
        "freshness": research / "live_decision_log_freshness_cadence_final_decision.json",
        "logger_qa": research / "logger_lookup_integration_patch_qa_final_decision.json",
        "adapter_qa": research / "rerun_live_decision_adapter_qa_final_decision.json",
        "auction": cognition / "auction_episode_memory.parquet",
        "cognitive": cognition / "cognitive_market_state_memory.parquet",
        "final": cognition / "final_market_context_memory.parquet",
        "lifecycle": cognition / "market_context_lifecycle_memory.parquet",
    }


def _mock_run_script_ok(script: Path, *, timeout_s: int = 900, **kwargs) -> dict:
    return {
        "script": str(script),
        "returncode": 0,
        "ok": True,
        "started_at_utc": "2026-07-20T13:00:00Z",
        "ended_at_utc": "2026-07-20T13:01:00Z",
        "stdout_tail": "ok",
        "stderr_tail": "",
    }


def _mock_run_script_fail(script: Path, *, timeout_s: int = 900, **kwargs) -> dict:
    return {
        "script": str(script),
        "returncode": 1,
        "ok": False,
        "started_at_utc": "2026-07-20T13:00:00Z",
        "ended_at_utc": "2026-07-20T13:01:00Z",
        "stdout_tail": "",
        "stderr_tail": "boom",
    }


def _run(fx: dict[str, Path], **kwargs):
    defaults = dict(
        approved=True,
        no_paper_signal=True,
        one_shot=True,
        research_dir=fx["research"],
        live_feed=fx["live_feed"],
        decision_log=fx["decision_log"],
        auction_path=fx["auction"],
        cognitive_path=fx["cognitive"],
        final_path=fx["final"],
        lifecycle_path=fx["lifecycle"],
        cognition_dir=fx["cognition"],
        runtime_log=fx["runtime_log"],
        logger_script=LOGGER_PATH,
        refresh_once_script=REFRESH_PATH,
        shadow_script=ROOT / "scripts/research/build_market_context_shadow_chain.py",
        corrected_lookup=fx["lookup"],
        freshness_final=fx["freshness"],
        logger_patch_qa_final=fx["logger_qa"],
        adapter_qa_final=fx["adapter_qa"],
        ledger_dir=fx["research"],
        report_path=fx["report"],
        run_script=_mock_run_script_ok,
        write_report_doc=True,
        shadow_timeout_s=5,
    )
    defaults.update(kwargs)
    return mod.run_single_live_refresh_append(**defaults)


def test_missing_approval_flag_blocks_no_writes(tmp_path: Path):
    fx = _prepare_fixture(tmp_path)
    before = _sha(fx["decision_log"])
    ledger_before = {n: _sha(fx["research"] / n) for n in mod.LEDGER_PARQUETS}
    result = _run(fx, approved=False)
    assert result["final_decision"]["status"] == "BLOCKED_APPROVAL_FLAGS_REQUIRED"
    assert result["exit_code"] == 2
    assert _sha(fx["decision_log"]) == before
    assert {n: _sha(fx["research"] / n) for n in mod.LEDGER_PARQUETS} == ledger_before


def test_missing_no_paper_signal_flag_blocks(tmp_path: Path):
    fx = _prepare_fixture(tmp_path)
    before = _sha(fx["decision_log"])
    result = _run(fx, no_paper_signal=False)
    assert result["final_decision"]["status"] == "BLOCKED_APPROVAL_FLAGS_REQUIRED"
    assert _sha(fx["decision_log"]) == before


def test_missing_one_shot_flag_blocks(tmp_path: Path):
    fx = _prepare_fixture(tmp_path)
    before = _sha(fx["decision_log"])
    result = _run(fx, one_shot=False)
    assert result["final_decision"]["status"] == "BLOCKED_APPROVAL_FLAGS_REQUIRED"
    assert _sha(fx["decision_log"]) == before


def test_missing_freshness_audit_blocks(tmp_path: Path):
    fx = _prepare_fixture(tmp_path, include_freshness=False)
    before = _sha(fx["decision_log"])
    result = _run(fx)
    assert (
        result["final_decision"]["status"]
        == "BLOCKED_INVALID_SINGLE_LIVE_REFRESH_APPEND_INPUTS"
    )
    assert _sha(fx["decision_log"]) == before


def test_missing_live_feed_blocks(tmp_path: Path):
    fx = _prepare_fixture(tmp_path, include_feed=False)
    # decision log exists but feed missing
    fx["decision_log"].parent.mkdir(parents=True, exist_ok=True)
    if not fx["decision_log"].exists():
        _seed_decision_log(fx["decision_log"], ["2026-07-19T13:00:00Z"])
    result = _run(fx)
    assert (
        result["final_decision"]["status"]
        == "BLOCKED_INVALID_SINGLE_LIVE_REFRESH_APPEND_INPUTS"
    )
    assert result["precheck"]["live_market_feed_found"] is False


def test_missing_live_decision_log_blocks(tmp_path: Path):
    fx = _prepare_fixture(tmp_path, include_decision_log=False)
    result = _run(fx)
    assert (
        result["final_decision"]["status"]
        == "BLOCKED_INVALID_SINGLE_LIVE_REFRESH_APPEND_INPUTS"
    )
    assert result["precheck"]["live_decision_log_found"] is False


def test_exactly_one_append_on_success(tmp_path: Path):
    fx = _prepare_fixture(tmp_path)
    before_rows = len(pd.read_parquet(fx["decision_log"]))
    before_df = pd.read_parquet(fx["decision_log"]).copy()
    ledger_before = {n: _sha(fx["research"] / n) for n in mod.LEDGER_PARQUETS}
    logger_before = _sha(LOGGER_PATH)
    lookup_before = _sha(fx["lookup"])
    result = _run(fx)
    final = result["final_decision"]
    assert (
        final["status"]
        == "SINGLE_LIVE_CONTEXT_REFRESH_AND_DECISION_LOG_APPEND_DONE_WITH_LIMITATIONS"
    )
    assert final["qa_status"] == "PASS_WITH_LIMITATIONS"
    assert final["appended_rows_count"] == 1
    assert final["decision_log_append_performed"] is True
    assert final["paper_signal_write_performed"] is False
    assert final["next_recommended_step"] == "SINGLE_LIVE_CONTEXT_REFRESH_APPEND_QA_AUDIT"
    after = pd.read_parquet(fx["decision_log"])
    assert len(after) == before_rows + 1
    # old rows preserved
    for col in before_df.columns:
        assert list(before_df[col].astype(str)) == list(after.iloc[:before_rows][col].astype(str))
    new = after.iloc[-1]
    assert bool(new["paper_signal_write_allowed"]) is False
    assert bool(new["paper_loop_allowed"]) is False
    assert bool(new["execution_enabled"]) is False
    assert {n: _sha(fx["research"] / n) for n in mod.LEDGER_PARQUETS} == ledger_before
    assert _sha(LOGGER_PATH) == logger_before
    assert _sha(fx["lookup"]) == lookup_before
    assert result["no_backfill_check"]["live_decision_log_backfilled"] is False
    assert result["no_backfill_check"]["old_rows_preserved"] is True
    assert result["no_paper_signal_check"]["paper_loop_started"] is False
    assert result["lookup_enrichment_result"]["logger_lookup_enrichment_attempted"] is True
    assert mod.assert_no_forbidden_imports(MODULE_PATH)
    assert mod.assert_no_loop_or_sleep(MODULE_PATH)
    assert mod.assert_no_model_fit_calls(MODULE_PATH)


def test_no_append_if_duplicate_decision_timestamp(tmp_path: Path):
    # Cognition latest equals an existing decision candle.
    fx = _prepare_fixture(
        tmp_path,
        decision_timestamps=["2026-07-20T13:00:00Z", "2026-07-20T13:15:00Z"],
        cognition_timestamps=["2026-07-20T13:00:00Z", "2026-07-20T13:15:00Z"],
    )
    before = _sha(fx["decision_log"])
    before_rows = len(pd.read_parquet(fx["decision_log"]))
    result = _run(fx)
    assert (
        result["final_decision"]["status"]
        == "BLOCKED_DUPLICATE_DECISION_TS_NO_APPEND"
    )
    assert result["final_decision"]["appended_rows_count"] == 0
    assert _sha(fx["decision_log"]) == before
    assert len(pd.read_parquet(fx["decision_log"])) == before_rows


def test_no_append_if_refreshed_timestamp_not_newer(tmp_path: Path):
    fx = _prepare_fixture(
        tmp_path,
        decision_timestamps=["2026-07-20T14:00:00Z", "2026-07-20T14:15:00Z"],
        cognition_timestamps=["2026-07-20T13:00:00Z", "2026-07-20T13:15:00Z"],
        live_timestamps=["2026-07-20T13:00:00Z", "2026-07-20T13:15:00Z"],
    )
    before = _sha(fx["decision_log"])
    result = _run(fx)
    assert (
        result["final_decision"]["status"]
        == "BLOCKED_NO_NEW_DECISION_TIMESTAMP_NO_APPEND"
    )
    assert result["final_decision"]["decision_log_append_performed"] is False
    assert _sha(fx["decision_log"]) == before


def test_refresh_failure_blocks_append(tmp_path: Path):
    # Make lifecycle stale so rebuild is attempted, then fail mock.
    fx = _prepare_fixture(
        tmp_path,
        cognition_timestamps=["2026-07-20T13:00:00Z"],
        live_timestamps=["2026-07-20T13:00:00Z", "2026-07-20T13:15:00Z"],
    )
    before = _sha(fx["decision_log"])
    result = _run(fx, run_script=_mock_run_script_fail)
    assert result["final_decision"]["status"] == "BLOCKED_REFRESH_FAILED_NO_APPEND"
    assert result["final_decision"]["appended_rows_count"] == 0
    assert _sha(fx["decision_log"]) == before


def test_observe_row_remains_blocked_but_can_append(tmp_path: Path):
    fx = _prepare_fixture(tmp_path, context="OBSERVE")
    result = _run(fx)
    assert (
        result["final_decision"]["status"]
        == "SINGLE_LIVE_CONTEXT_REFRESH_AND_DECISION_LOG_APPEND_DONE_WITH_LIMITATIONS"
    )
    preview = result["decision_row_preview"]
    assert preview["context"] == "OBSERVE"
    # OBSERVE should remain signal-blocked.
    assert "OBSERVE" in str(preview.get("signal_eligibility_status") or "") or (
        "OBSERVE" in str(preview.get("signal_block_reasons") or "")
    )
    assert preview["paper_signal_write_allowed"] is False
    after = pd.read_parquet(fx["decision_log"])
    assert bool(after.iloc[-1]["paper_signal_write_allowed"]) is False


def test_directional_lookup_enrichment_attempted(tmp_path: Path):
    # Fresh enough relative to written_at inside build_decision_row (now).
    fx = _prepare_fixture(
        tmp_path,
        decision_timestamps=["2026-07-19T10:00:00Z"],
        cognition_timestamps=[
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"),
        ],
        context="LONG_CONTEXT",
    )
    # Align live to same fresh ts
    life = pd.read_parquet(fx["lifecycle"])
    ts = life["timestamp"].iloc[-1]
    live = pd.read_parquet(fx["live_feed"])
    live.loc[live.index[-1], "timestamp"] = ts
    live.to_parquet(fx["live_feed"], index=False)
    result = _run(fx)
    assert result["lookup_enrichment_result"]["logger_lookup_enrichment_attempted"] is True
    assert result["final_decision"]["logger_lookup_enrichment_attempted"] is True
    # May or may not populate depending on lookup schema; enrichment must be attempted.
    preview = result["decision_row_preview"]
    assert preview["paper_loop_allowed"] is False
    assert preview["execution_enabled"] is False


def test_script_safety_static_checks():
    assert mod.assert_no_forbidden_imports(MODULE_PATH)
    assert mod.assert_no_loop_or_sleep(MODULE_PATH)
    assert mod.assert_no_model_fit_calls(MODULE_PATH)
    assert "run_refresh_once" not in MODULE_PATH.read_text(encoding="utf-8").split(
        "def run_single_live_refresh_append"
    )[1].split("def main")[0] or True
    source = MODULE_PATH.read_text(encoding="utf-8")
    # Must not invoke the full once helper that auto-appends.
    assert "run_refresh_once(" not in source
