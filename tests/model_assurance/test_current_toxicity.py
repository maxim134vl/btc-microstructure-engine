"""Minimal MODEL-4 current context/trade toxicity tests."""

from __future__ import annotations

import json
from pathlib import Path

from btc_ml.model_assurance.toxic_box import context_toxicity as ct
from btc_ml.model_assurance.toxic_box import trade_toxicity as tt
from btc_ml.model_assurance.toxic_box.common import read_jsonl
from btc_ml.trading.intrabar_paper.books import EpochBooks


ACTIVE = {
    "registry_record_id": "REG",
    "model_id": "M",
    "model_version": "V",
    "runtime_fingerprint": "fp",
    "paper_epoch_id": "EPOCH",
    "paper_only": True,
    "real_execution": False,
}

CFG = {
    "context": {
        "minimum_move_bps": 10.0,
        "false_direction_horizon": "3X",
        "false_direction_mae_to_mfe_ratio": 2.0,
        "premature_max_lifecycle_fraction": 0.5,
        "overstay_min_mfe_bps": 20.0,
        "overstay_giveback_ratio": 0.8,
        "flip_instability_max_flips": 3,
        "flip_instability_window_timeframes": 2,
    },
    "trade": {
        "severe_loss_r_lte": -1.25,
        "risk_tolerance_usd": 0.01,
        "pnl_reconciliation_tolerance_usd": 0.01,
    },
}


def test_false_direction_and_overstay_candidates(tmp_path: Path):
    events = tmp_path / "ctx.jsonl"
    pred = {
        "prediction_id": "P1",
        "registry_record_id": "REG",
        "paper_epoch_id": "EPOCH",
        "direction": "LONG",
        "timeframe": "M15",
        "context_event_id": "C1",
        "lifecycle_episode_id": "L1",
        "start_timestamp": "2026-07-28T12:00:00Z",
        "prediction_status": "CLOSED",
        "closed_at": "2026-07-28T12:45:00Z",
        "close_reason": "CONTEXT_END",
    }
    outs = [
        {
            "outcome_id": "O3",
            "prediction_id": "P1",
            "registry_record_id": "REG",
            "paper_epoch_id": "EPOCH",
            "horizon_type": "3xTF",
            "outcome_status": "EVALUATED",
            "signed_return_bps": -25.0,
            "mfe_bps": 2.0,
            "mae_bps": -40.0,
            "evaluated_at": "2026-07-28T12:45:00Z",
        },
        {
            "outcome_id": "OL",
            "prediction_id": "P1",
            "registry_record_id": "REG",
            "paper_epoch_id": "EPOCH",
            "horizon_type": "LIFECYCLE_END",
            "outcome_status": "EVALUATED",
            "signed_return_bps": 5.0,
            "mfe_bps": 40.0,
            "mae_bps": -5.0,
            "evaluated_at": "2026-07-28T12:45:00Z",
        },
    ]
    ids: set[str] = set()
    stats = ct.evaluate_context_toxicity(
        active=ACTIVE,
        predictions=[pred],
        outcomes=outs,
        config=CFG,
        events_path=events,
        existing_ids=ids,
    )
    rows = read_jsonl(events)
    subtypes = {r["subtype"] for r in rows}
    assert "CTX_FALSE_DIRECTION" in subtypes
    assert "CTX_OVERSTAY" in subtypes
    assert all(r["status"] == "CANDIDATE" for r in rows)
    assert stats["toxic_candidates"] >= 2


def test_normal_context_no_toxic(tmp_path: Path):
    events = tmp_path / "ctx.jsonl"
    pred = {
        "prediction_id": "P2",
        "registry_record_id": "REG",
        "paper_epoch_id": "EPOCH",
        "direction": "LONG",
        "timeframe": "M15",
        "start_timestamp": "2026-07-28T12:00:00Z",
        "prediction_status": "OPEN",
    }
    outs = [
        {
            "outcome_id": "O",
            "prediction_id": "P2",
            "registry_record_id": "REG",
            "paper_epoch_id": "EPOCH",
            "horizon_type": "3xTF",
            "outcome_status": "EVALUATED",
            "signed_return_bps": 15.0,
            "mfe_bps": 20.0,
            "mae_bps": -2.0,
            "evaluated_at": "2026-07-28T12:45:00Z",
        }
    ]
    ct.evaluate_context_toxicity(
        active=ACTIVE, predictions=[pred], outcomes=outs, config=CFG, events_path=events, existing_ids=set()
    )
    assert read_jsonl(events) == []


def test_wrong_side_and_future_bbo_confirmed(tmp_path: Path):
    books_root = tmp_path / "books"
    books = EpochBooks(books_root, paper_epoch_id="EPOCH")
    books.append(
        "trades",
        {
            "trade_id": "T1",
            "position_id": "P1",
            "timeframe": "M15",
            "side": "LONG",
            "status": "CLOSED",
            "quantity": 1.0,
            "entry_price": 100.0,
            "exit_price": 101.0,
            "context_event_id": "C1",
            "lifecycle_episode_id": "L1",
            "exit_ts": "2026-07-28T12:10:00Z",
            "risk_amount_usd": 1000.0,
        },
    )
    books.append(
        "fills",
        {
            "fill_id": "F_ENTRY",
            "order_id": "O1",
            "command_id": "CMD1",
            "timeframe": "M15",
            "side": "LONG",
            "action": "ENTRY",
            "paper_fill_price": 100.0,  # should be ask 100.2
            "best_bid": 100.0,
            "best_ask": 100.2,
            "bbo_age_ms": 10,
            "bbo_receive_monotonic_ns": 200,
            "command_monotonic_ns": 100,  # future bbo
            "ts": "2026-07-28T12:00:00Z",
        },
    )
    books.append(
        "fills",
        {
            "fill_id": "F_EXIT",
            "order_id": "O2",
            "command_id": "CMD2",
            "timeframe": "M15",
            "side": "LONG",
            "action": "EXIT",
            "paper_fill_price": 101.0,
            "fill_bid": 101.0,
            "fill_ask": 101.1,
            "bbo_age_ms": 5,
            "bbo_receive_monotonic_ns": 50,
            "command_monotonic_ns": 60,
            "ts": "2026-07-28T12:10:00Z",
        },
    )
    books.append(
        "commands",
        {
            "command_id": "CMD1",
            "timeframe": "M15",
            "side": "LONG",
            "action": "ENTRY",
            "context_event_id": "C1",
            "lifecycle_episode_id": "L1",
            "command_monotonic_ns": 100,
        },
    )
    events = tmp_path / "trd.jsonl"
    tt.evaluate_trade_toxicity(
        active=ACTIVE,
        books=books,
        economic_evaluations=[],
        config=CFG,
        max_bbo_age_ms=2000.0,
        events_path=events,
        existing_ids=set(),
    )
    subtypes = {r["subtype"] for r in read_jsonl(events)}
    assert "TRD_WRONG_SIDE_FILL" in subtypes
    assert "TRD_FUTURE_BBO_USED" in subtypes
    assert all(r["status"] == "CONFIRMED" for r in read_jsonl(events) if r["subtype"] in subtypes)


def test_ordinary_loss_vs_severe_and_cost_dominated(tmp_path: Path):
    books = EpochBooks(tmp_path / "books", paper_epoch_id="EPOCH")
    for tid, net, gross, fees, slip, r in [
        ("T_ORD", -5.0, -4.0, 0.5, 0.5, -0.2),
        ("T_SEV", -20.0, -18.0, 1.0, 1.0, -1.5),
        ("T_COST", -2.0, -0.5, 1.0, 1.0, -0.1),
    ]:
        books.append(
            "trades",
            {
                "trade_id": tid,
                "position_id": f"P_{tid}",
                "timeframe": "M15",
                "side": "LONG",
                "status": "CLOSED",
                "quantity": 1.0,
                "entry_price": 100.0,
                "exit_price": 99.0,
                "context_event_id": "C",
                "lifecycle_episode_id": "L",
                "exit_ts": "2026-07-28T12:10:00Z",
                "risk_amount_usd": 1000.0,
                "net_pnl_usd": net,
            },
        )
    econ = [
        {
            "trade_id": "T_ORD",
            "registry_record_id": "REG",
            "paper_epoch_id": "EPOCH",
            "net_pnl_usd": -5.0,
            "gross_pnl_usd": -4.0,
            "total_fee_usd": 0.5,
            "total_slippage_usd": 0.5,
            "realized_r_multiple": -0.2,
            "pnl_reconciliation_status": "MATCHED",
        },
        {
            "trade_id": "T_SEV",
            "registry_record_id": "REG",
            "paper_epoch_id": "EPOCH",
            "net_pnl_usd": -20.0,
            "gross_pnl_usd": -18.0,
            "total_fee_usd": 1.0,
            "total_slippage_usd": 1.0,
            "realized_r_multiple": -1.5,
            "pnl_reconciliation_status": "MATCHED",
        },
        {
            "trade_id": "T_COST",
            "registry_record_id": "REG",
            "paper_epoch_id": "EPOCH",
            "net_pnl_usd": -2.0,
            "gross_pnl_usd": -0.5,
            "total_fee_usd": 1.0,
            "total_slippage_usd": 1.0,
            "realized_r_multiple": -0.1,
            "pnl_reconciliation_status": "MATCHED",
        },
    ]
    events = tmp_path / "trd.jsonl"
    tt.evaluate_trade_toxicity(
        active=ACTIVE,
        books=books,
        economic_evaluations=econ,
        config=CFG,
        max_bbo_age_ms=2000.0,
        events_path=events,
        existing_ids=set(),
    )
    rows = read_jsonl(events)
    by_trade = {}
    for r in rows:
        by_trade.setdefault(r.get("trade_id"), set()).add(r["subtype"])
    assert "T_ORD" not in by_trade or not ({"TRD_SEVERE_LOSS", "TRD_COST_DOMINATED"} & by_trade.get("T_ORD", set()))
    assert "TRD_SEVERE_LOSS" in by_trade.get("T_SEV", set())
    assert "TRD_COST_DOMINATED" in by_trade.get("T_COST", set())


def test_epoch_filter_and_no_duplicates(tmp_path: Path):
    events = tmp_path / "ctx.jsonl"
    pred = {
        "prediction_id": "P9",
        "registry_record_id": "REG",
        "paper_epoch_id": "EPOCH",
        "direction": "SHORT",
        "timeframe": "M15",
        "start_timestamp": "2026-07-28T12:00:00Z",
        "prediction_status": "CLOSED",
        "closed_at": "2026-07-28T12:45:00Z",
        "close_reason": "CONTEXT_END",
    }
    legacy = {**pred, "prediction_id": "P_LEG", "paper_epoch_id": "OLD"}
    outs = [
        {
            "outcome_id": "O9",
            "prediction_id": "P9",
            "registry_record_id": "REG",
            "paper_epoch_id": "EPOCH",
            "horizon_type": "3xTF",
            "outcome_status": "EVALUATED",
            "signed_return_bps": -30.0,
            "mfe_bps": 1.0,
            "mae_bps": -50.0,
            "evaluated_at": "2026-07-28T12:45:00Z",
        },
        {
            "outcome_id": "OL9",
            "prediction_id": "P9",
            "registry_record_id": "REG",
            "paper_epoch_id": "EPOCH",
            "horizon_type": "LIFECYCLE_END",
            "outcome_status": "EVALUATED",
            "signed_return_bps": 0.0,
            "mfe_bps": 50.0,
            "mae_bps": -1.0,
            "evaluated_at": "2026-07-28T12:45:00Z",
        },
        {
            "outcome_id": "OLEG",
            "prediction_id": "P_LEG",
            "registry_record_id": "REG",
            "paper_epoch_id": "OLD",
            "horizon_type": "3xTF",
            "outcome_status": "EVALUATED",
            "signed_return_bps": -30.0,
            "mfe_bps": 1.0,
            "mae_bps": -50.0,
        },
    ]
    ids: set[str] = set()
    ct.evaluate_context_toxicity(
        active=ACTIVE, predictions=[pred, legacy], outcomes=outs, config=CFG, events_path=events, existing_ids=ids
    )
    ct.evaluate_context_toxicity(
        active=ACTIVE, predictions=[pred, legacy], outcomes=outs, config=CFG, events_path=events, existing_ids=ids
    )
    rows = read_jsonl(events)
    assert all(r.get("paper_epoch_id") == "EPOCH" for r in rows)
    # idempotent: unique toxic_event_id
    assert len(rows) == len({r["toxic_event_id"] for r in rows})
