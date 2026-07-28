"""Minimal MODEL-3 economic validation tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from btc_ml.model_assurance import economic_validation as ev
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config


def _cfg_obj():
    return SimpleNamespace(
        entry_fee_bps=2.0,
        exit_fee_bps=5.0,
        entry_slippage_bps=3.0,
        exit_slippage_bps=3.0,
        stop_exit_slippage_bps=5.0,
    )


def test_long_economics_and_r():
    cfg = _cfg_obj()
    econ = ev.compute_trade_economics(
        side="LONG",
        entry_price=100.0,
        exit_price=101.0,
        quantity=1.0,
        risk_amount_usd=1000.0,
        exit_reason="TP",
        cfg=cfg,
    )
    assert econ["gross_pnl_usd"] == pytest.approx(1.0)
    assert econ["entry_fee_usd"] == pytest.approx(100.0 * 0.0002)
    assert econ["exit_fee_usd"] == pytest.approx(101.0 * 0.0005)
    assert econ["entry_slippage_usd"] == pytest.approx(100.0 * 0.0003)
    assert econ["exit_slippage_usd"] == pytest.approx(101.0 * 0.0003)
    expected_net = (
        econ["gross_pnl_usd"]
        - econ["entry_fee_usd"]
        - econ["exit_fee_usd"]
        - econ["entry_slippage_usd"]
        - econ["exit_slippage_usd"]
    )
    assert econ["net_pnl_usd"] == pytest.approx(expected_net)
    assert econ["r_multiple"] == pytest.approx(expected_net / 1000.0)


def test_short_symmetric_to_long():
    cfg = _cfg_obj()
    long_e = ev.compute_trade_economics(
        side="LONG", entry_price=100.0, exit_price=101.0, quantity=1.0, risk_amount_usd=1000.0, exit_reason="TP", cfg=cfg
    )
    short_e = ev.compute_trade_economics(
        side="SHORT", entry_price=100.0, exit_price=99.0, quantity=1.0, risk_amount_usd=1000.0, exit_reason="TP", cfg=cfg
    )
    # Symmetric $1 favorable move
    assert long_e["gross_pnl_usd"] == pytest.approx(1.0)
    assert short_e["gross_pnl_usd"] == pytest.approx(1.0)
    assert short_e["gross_pnl_usd"] == pytest.approx(long_e["gross_pnl_usd"])


def test_legacy_void_inactive_excluded():
    activated = datetime(2026, 7, 28, 11, 0, tzinfo=timezone.utc)
    epoch = "EPOCH_ACTIVE"
    base = {
        "trade_id": "t1",
        "paper_epoch_id": epoch,
        "status": "CLOSED",
        "exit_ts": "2026-07-28T12:00:00Z",
        "entry_price": 1.0,
        "exit_price": 1.1,
        "quantity": 1.0,
    }
    assert ev.is_eligible_closed_trade(base, paper_epoch_id=epoch, activated_at=activated) is True
    assert (
        ev.is_eligible_closed_trade(
            {**base, "status": "VOID_PRE_INTRABAR_RULE_CONTRACT"},
            paper_epoch_id=epoch,
            activated_at=activated,
        )
        is False
    )
    assert (
        ev.is_eligible_closed_trade(
            {**base, "paper_epoch_id": "OTHER"},
            paper_epoch_id=epoch,
            activated_at=activated,
        )
        is False
    )
    assert (
        ev.is_eligible_closed_trade(
            {**base, "paper_epoch_id": ""},
            paper_epoch_id=epoch,
            activated_at=activated,
        )
        is False
    )
    assert (
        ev.is_eligible_closed_trade(
            {**base, "exit_ts": "2026-07-28T10:00:00Z"},
            paper_epoch_id=epoch,
            activated_at=activated,
        )
        is False
    )


def test_rerun_no_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path
    epoch_id = "INTRABAR_RULES_V1_TEST"
    for rel in [
        "config",
        "data/trading/paper_epochs",
        f"data/trading/intrabar_paper/{epoch_id}/books",
        "data/model_assurance/registry/active",
    ]:
        (root / rel).mkdir(parents=True)
    (root / "config" / "model_assurance_economic_validation.json").write_text(
        json.dumps(
            {
                "check_interval_seconds": 5,
                "pnl_reconciliation_tolerance_usd": 0.01,
                "min_closed_trades_for_current": 5,
                "source_stale_seconds": 120,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Minimal execution config for load_intrabar_paper_config
    exec_cfg = json.loads(Path("/Users/fontecrypto/btc-ml/config/intrabar_paper_execution.json").read_text())
    (root / "config" / "intrabar_paper_execution.json").write_text(json.dumps(exec_cfg) + "\n", encoding="utf-8")
    active = {
        "registry_record_id": "REG",
        "model_id": "M",
        "model_version": "V",
        "runtime_fingerprint": "fp",
        "paper_epoch_id": epoch_id,
        "paper_epoch_activated_at": "2026-07-28T11:00:00Z",
        "paper_only": True,
        "real_execution": False,
    }
    (root / "data" / "model_assurance" / "registry" / "active" / "active_model.json").write_text(
        json.dumps(active) + "\n", encoding="utf-8"
    )
    (root / "data" / "trading" / "paper_epochs" / "active.json").write_text(
        json.dumps(
            {
                "paper_epoch_id": epoch_id,
                "epoch_status": "ACTIVE",
                "activated_at": "2026-07-28T11:00:00Z",
                "rule_contract_version": "INTRABAR_RULES_V1",
                "initial_equity_usd": 100000.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    books = root / f"data/trading/intrabar_paper/{epoch_id}/books"
    for name in ("trades", "positions", "equity_snapshots", "fills", "orders", "signals", "commands", "metrics", "blocked"):
        (books / f"{name}.jsonl").write_text("", encoding="utf-8")
    trade = {
        "trade_id": "T1",
        "position_id": "P1",
        "paper_epoch_id": epoch_id,
        "timeframe": "M15",
        "side": "LONG",
        "status": "CLOSED",
        "quantity": 1.0,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "risk_amount_usd": 1000.0,
        "exit_reason": "TP",
        "entry_ts": "2026-07-28T12:00:00Z",
        "exit_ts": "2026-07-28T12:10:00Z",
        "lifecycle_episode_id": "L1",
    }
    # Precompute canonical net via LIVE1B economics so reconciliation MATCHES
    cfg = load_intrabar_paper_config(repo_root=root)
    econ = ev.compute_trade_economics(
        side="LONG",
        entry_price=100.0,
        exit_price=101.0,
        quantity=1.0,
        risk_amount_usd=1000.0,
        exit_reason="TP",
        cfg=cfg,
    )
    trade["net_pnl_usd"] = econ["net_pnl_usd"]
    trade["gross_pnl_usd"] = econ["gross_pnl_usd"]
    (books / "trades.jsonl").write_text(json.dumps(trade, sort_keys=True) + "\n", encoding="utf-8")
    (books / "equity_snapshots.jsonl").write_text(
        json.dumps({"ts": "2026-07-28T11:00:00Z", "equity_usd": 100000.0, "paper_epoch_id": epoch_id}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ev, "read_active_runtime", lambda repo_root=None: active)
    s1 = ev.run_once(repo_root=root)
    s2 = ev.run_once(repo_root=root)
    assert s1["evaluated_trades"] == 1
    assert s2["evaluated_trades"] == 1
    lines = [
        ln
        for ln in (root / "data/model_assurance/economic_validation/trades/trade_evaluations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if ln.strip()
    ]
    assert len(lines) == 1


def test_summary_aggregation_and_mismatch(tmp_path: Path):
    evals = [
        {
            "trade_id": "A",
            "timeframe": "M15",
            "direction": "LONG",
            "gross_pnl_usd": 10.0,
            "net_pnl_usd": 8.0,
            "total_fee_usd": 1.0,
            "total_slippage_usd": 1.0,
            "realized_r_multiple": 0.8,
            "pnl_reconciliation_status": "MATCHED",
            "exit_timestamp": "2026-07-28T12:00:00Z",
            "evaluated_at": "2026-07-28T12:01:00Z",
        },
        {
            "trade_id": "B",
            "timeframe": "H1",
            "direction": "SHORT",
            "gross_pnl_usd": -5.0,
            "net_pnl_usd": -6.0,
            "total_fee_usd": 0.5,
            "total_slippage_usd": 0.5,
            "realized_r_multiple": -0.6,
            "pnl_reconciliation_status": "MISMATCH",
            "exit_timestamp": "2026-07-28T13:00:00Z",
            "evaluated_at": "2026-07-28T13:01:00Z",
        },
    ]
    summary = ev.build_summary(
        active={"registry_record_id": "REG", "model_id": "M", "model_version": "V", "paper_epoch_id": "E"},
        evaluations=evals,
        open_positions=1,
        closed_trade_count=2,
        equity_snaps=[{"equity_usd": 100000.0, "ts": "2026-07-28T11:00:00Z"}],
        config={"min_closed_trades_for_current": 5, "source_stale_seconds": 120},
        source_age_seconds=10.0,
    )
    assert summary["gross_pnl_usd"] == pytest.approx(5.0)
    assert summary["net_pnl_usd"] == pytest.approx(2.0)
    assert summary["fees_usd"] == pytest.approx(1.5)
    assert summary["slippage_usd"] == pytest.approx(1.5)
    assert summary["counts_by_timeframe"]["M15"] == 1
    assert summary["counts_by_direction"]["SHORT"] == 1
    assert summary["mismatched_reconciliations"] == 1
    assert summary["matched_reconciliations"] == 1
    assert summary["status"] == "RECONCILIATION_WARNING"
    assert summary["open_positions"] == 1
    status, diff = ev.reconcile_net_pnl(computed_net=1.0, canonical_net=1.02, tolerance_usd=0.01)
    assert status == "MISMATCH"
    assert diff == pytest.approx(-0.02)
