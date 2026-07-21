"""Tests for bounded paper trading controller (auto ledger / no real execution)."""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CTRL_PATH = (
    ROOT
    / "scripts"
    / "live"
    / "bounded_paper_trading_controller_auto_ledger_no_real_execution.py"
)
RESEARCH = ROOT / "data" / "research" / "paper_simulator"
LIVE = ROOT / "data" / "live"

spec = importlib.util.spec_from_file_location(
    "bounded_paper_trading_controller_auto_ledger_no_real_execution", CTRL_PATH
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["bounded_paper_trading_controller_auto_ledger_no_real_execution"] = mod
spec.loader.exec_module(mod)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)


def _seed(tmp_path: Path, *, force_open_position: bool = False) -> Path:
    research = tmp_path / "data" / "research" / "paper_simulator"
    live = tmp_path / "data" / "live"
    cognition = tmp_path / "data" / "cognition"
    scripts_live = tmp_path / "scripts" / "live"
    for d in (research, live, cognition, scripts_live, tmp_path / "logs", tmp_path / "run"):
        d.mkdir(parents=True)

    for name in (
        "paper_signals.parquet",
        "paper_orders.parquet",
        "paper_events.parquet",
        "paper_trades.parquet",
        "paper_positions.parquet",
        "paper_equity_curve.parquet",
        "paper_risk_blocks.parquet",
    ):
        _copy(RESEARCH / name, research / name)
    _copy(LIVE / "live_market_feed.parquet", live / "live_market_feed.parquet")
    _copy(LIVE / "context_decision_log.parquet", live / "context_decision_log.parquet")

    if force_open_position:
        pos_path = research / "paper_positions.parquet"
        df = pd.read_parquet(pos_path)
        # Ensure exactly one OPEN LONG for controller open-block tests.
        df["status"] = "CLOSED"
        target = "PAPER_POSITION_ONE_SHOT_a44e90c3306cdb59"
        idx = df.index[df["position_id"].astype(str) == target]
        assert len(idx) >= 1
        i = int(idx[-1])
        df.at[i, "status"] = "OPEN"
        df.at[i, "closed_at"] = None
        df.at[i, "exit_price"] = None
        meta = {}
        raw = df.at[i, "metadata_json"]
        if isinstance(raw, str) and raw.strip():
            try:
                meta = json.loads(raw)
            except Exception:
                meta = {}
        meta["position_status"] = "OPEN"
        meta["side"] = "LONG"
        meta["stop_loss_price"] = 65253.87
        meta["take_profit_price"] = 66901.695
        meta["quantity_btc"] = 0.15171513965378605
        meta["entry_fee_usd"] = 10.0
        df.at[i, "metadata_json"] = json.dumps(meta)
        df.to_parquet(pos_path, index=False)
    return tmp_path


def test_01_approval_required():
    assert mod.main([]) == 2
    assert (
        mod.main(
            [
                "--approved-bounded-paper-controller-auto-ledger",
                "--paper-only",
            ]
        )
        == 2
    )


def test_02_no_exchange_imports_or_fit_calls():
    tree = ast.parse(CTRL_PATH.read_text(encoding="utf-8"))
    forbidden = {"ccxt", "binance", "bybit", "exchange_api", "broker"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            assert name.lower() not in {"fit", "retrain", "train_model"}
    audit = mod.audit_imports(CTRL_PATH)
    assert audit["exchange_api_import_absent"] is True
    assert audit["model_fit_call_absent"] is True


def test_03_bounded_loop_defaults():
    assert mod.DEFAULT_MAX_CYCLES == 96
    assert mod.DEFAULT_INTERVAL_SECONDS == 900
    assert mod.DEFAULT_MAX_DURATION_HOURS == 24
    assert mod.CONTROLLER_MODE == "PAPER_ONLY"


def test_04_long_short_stop_take_context_and_stop_first():
    long_stop = mod.evaluate_exit_preview(
        side="LONG",
        entry_price=100.0,
        quantity=1.0,
        stop_loss_price=99.0,
        take_profit_price=101.5,
        entry_fee_usd=0.1,
        current_price=100.5,
        latest_high=101.6,
        latest_low=98.5,
        latest_context="LONG_CONTEXT",
        latest_lifecycle_state="ACTIVE",
    )
    assert long_stop["same_bar_stop_take_hit"] is True
    assert long_stop["exit_preview_action"] == "PREVIEW_CLOSE_LONG_STOP_LOSS"
    assert "STOP_FIRST" in long_stop["exit_preview_reason"]

    long_take = mod.evaluate_exit_preview(
        side="LONG",
        entry_price=100.0,
        quantity=1.0,
        stop_loss_price=99.0,
        take_profit_price=101.5,
        entry_fee_usd=0.1,
        current_price=101.6,
        latest_high=101.6,
        latest_low=100.2,
        latest_context="LONG_CONTEXT",
        latest_lifecycle_state="ACTIVE",
    )
    assert long_take["exit_preview_action"] == "PREVIEW_CLOSE_LONG_TAKE_PROFIT"

    long_ctx = mod.evaluate_exit_preview(
        side="LONG",
        entry_price=100.0,
        quantity=1.0,
        stop_loss_price=99.0,
        take_profit_price=101.5,
        entry_fee_usd=0.1,
        current_price=100.5,
        latest_high=100.6,
        latest_low=100.2,
        latest_context="SHORT_CONTEXT",
        latest_lifecycle_state="ACTIVE",
    )
    assert long_ctx["exit_preview_action"] == "PREVIEW_CLOSE_LONG_CONTEXT_EXIT"

    short_stop = mod.evaluate_exit_preview(
        side="SHORT",
        entry_price=100.0,
        quantity=1.0,
        stop_loss_price=101.0,
        take_profit_price=98.5,
        entry_fee_usd=0.1,
        current_price=100.5,
        latest_high=101.2,
        latest_low=98.0,
        latest_context="SHORT_CONTEXT",
        latest_lifecycle_state="ACTIVE",
    )
    assert short_stop["same_bar_stop_take_hit"] is True
    assert short_stop["exit_preview_action"] == "PREVIEW_CLOSE_SHORT_STOP_LOSS"

    short_take = mod.evaluate_exit_preview(
        side="SHORT",
        entry_price=100.0,
        quantity=1.0,
        stop_loss_price=101.0,
        take_profit_price=98.5,
        entry_fee_usd=0.1,
        current_price=98.0,
        latest_high=100.2,
        latest_low=98.0,
        latest_context="SHORT_CONTEXT",
        latest_lifecycle_state="CHALLENGED",
    )
    assert short_take["exit_preview_action"] == "PREVIEW_CLOSE_SHORT_TAKE_PROFIT"

    short_ctx = mod.evaluate_exit_preview(
        side="SHORT",
        entry_price=100.0,
        quantity=1.0,
        stop_loss_price=101.0,
        take_profit_price=98.5,
        entry_fee_usd=0.1,
        current_price=100.0,
        latest_high=100.2,
        latest_low=99.8,
        latest_context="LONG_CONTEXT",
        latest_lifecycle_state="ACTIVE",
    )
    assert short_ctx["exit_preview_action"] == "PREVIEW_CLOSE_SHORT_CONTEXT_EXIT"


def test_05_open_position_blocks_new_entry(tmp_path: Path):
    root = _seed(tmp_path, force_open_position=True)
    research = root / "data/research/paper_simulator"
    opens = mod.load_open_positions(research)
    assert len(opens) == 1
    assert opens[0]["position_id"] == "PAPER_POSITION_ONE_SHOT_a44e90c3306cdb59"
    pre = mod.safety_preflight(
        research=research,
        paper_only=True,
        no_real_execution=True,
        this_path=CTRL_PATH,
    )
    assert pre["ok"] is True
    assert pre["open_position_count"] == 1

    # Force HOLD path by using LONG context in a fake decision via skip_refresh +
    # temporarily patching decision log latest row context in seed isn't needed if
    # current market/context would close — set stop/take far away already in meta.
    # Replace decision log last row to LONG_CONTEXT ACTIVE to avoid context exit.
    log_path = root / "data/live/context_decision_log.parquet"
    log = pd.read_parquet(log_path)
    log = log.copy()
    log["_ts"] = pd.to_datetime(log["candle_timestamp"], utc=True, errors="coerce")
    log = log.sort_values("_ts").reset_index(drop=True)
    i = len(log) - 1
    log.at[i, "active_market_context"] = "LONG_CONTEXT"
    log.at[i, "lifecycle_state"] = "CHALLENGED"
    log.at[i, "decision_stale"] = False
    log = log.drop(columns=["_ts"])
    log.to_parquet(log_path, index=False)

    result = mod.run_one_cycle(root=root, cycle_idx=1, skip_refresh=True)
    assert result["cycle_status"] == "OK"
    assert result["position_state_before"] == "LONG"
    assert result["action_taken"] == "OBSERVE_HOLD"
    assert result["execution_enabled"] is False
    assert result["paper_ledger_write_performed"] is False
    opens_after = mod.load_open_positions(research)
    assert len(opens_after) == 1


def test_06_no_duplicate_ids_and_idempotent_open_ids():
    a = mod.make_id("PAPER_SIGNAL_CTRL", "ts", "LONG", "1.0", "OPEN")
    b = mod.make_id("PAPER_SIGNAL_CTRL", "ts", "LONG", "1.0", "OPEN")
    c = mod.make_id("PAPER_SIGNAL_CTRL", "ts", "LONG", "1.1", "OPEN")
    assert a == b
    assert a != c


def test_07_one_cycle_writes_pid_status_dataset(tmp_path: Path):
    root = _seed(tmp_path)
    # Redirect PID/LOG via monkeypatch attributes
    pid_path = root / "run" / "bounded_paper_trading_controller_auto_ledger.pid"
    log_path = root / "logs" / "bounded_paper_trading_controller_auto_ledger.log"
    mod.PID_PATH = pid_path
    mod.LOG_PATH = log_path

    slept = []

    def _sleep(s: float) -> None:
        slept.append(s)

    rc = mod.run_controller(
        root=root,
        max_cycles=1,
        interval_seconds=0,
        max_duration_hours=24,
        skip_refresh=True,
        one_cycle=True,
        sleep_fn=_sleep,
        background_safe=True,
    )
    assert rc == 0
    assert slept == []
    research = root / "data/research/paper_simulator"
    status = json.loads(
        (research / "bounded_paper_controller_status.json").read_text()
    )
    final = json.loads(
        (research / "bounded_paper_controller_final_decision.json").read_text()
    )
    safety = json.loads(
        (research / "bounded_paper_controller_safety.json").read_text()
    )
    assert status["execution_enabled"] is False
    assert status["exchange_api_call_used"] is False
    assert final["execution_enabled"] is False
    assert safety["bounded_loop"] is True
    assert safety["dashboard_started"] is False
    assert safety["model_fit_used"] is False
    assert safety["retraining_used"] is False
    assert (research / "bounded_paper_controller_cycles.parquet").exists()
    assert (research / "bounded_paper_controller_cycles.csv").exists()
    assert log_path.exists()
    # PID cleared on stop for one-cycle
    assert not pid_path.exists() or pid_path.read_text().strip() == ""


def test_08_flat_entry_gate_and_synthetic_price_forbidden():
    ok = mod.evaluate_flat_entry_gate(
        {
            "decision_stale": False,
            "active_market_context": "LONG_CONTEXT",
            "lifecycle_state": "CHALLENGED",
            "expected_edge_bps": 4.5,
            "confidence": 0.6,
        }
    )
    assert ok["allowed"] is True
    assert ok["side"] == "LONG"
    bad = mod.evaluate_flat_entry_gate(
        {
            "decision_stale": True,
            "active_market_context": "LONG_CONTEXT",
            "lifecycle_state": "CHALLENGED",
            "expected_edge_bps": 4.5,
            "confidence": 0.6,
        }
    )
    assert bad["allowed"] is False
    stop, take = mod.compute_stop_take("LONG", 65913.0)
    assert abs(stop - 65253.87) < 0.05
    assert abs(take - 66901.695) < 0.05
