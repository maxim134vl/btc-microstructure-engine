"""SHADOW-STP1 — isolation, causality, exact profile, geometry, economics, idempotency."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.economics import resolve_risk_sizing
from btc_ml.trading.shadow_structural_protection import (
    EXPECTED_ACTIVE_FP,
    EXPECTED_EPOCH,
    EXPECTED_PARENT_FP,
    WRITE_BOUNDARY_VIOLATION,
)
from btc_ml.trading.shadow_structural_protection.engine import StructuralProtectionEngine
from btc_ml.trading.shadow_structural_protection.paths import assert_shadow_write_path
from btc_ml.trading.shadow_structural_protection.policies import (
    geometry_valid,
    structural_stop_price,
    structural_take_price,
)
from btc_ml.trading.shadow_structural_protection.profile import build_exact_candle_volume_profile
from btc_ml.trading.shadow_structural_protection.sleeves import apply_realized, initial_policy_sleeves, size_with_stop
from btc_ml.trading.shadow_structural_protection.zones import extract_zones


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def stp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    shutil.copy(REPO / "config" / "intrabar_paper_execution.json", repo / "config" / "intrabar_paper_execution.json")
    books = repo / "data" / "trading" / "intrabar_paper" / EXPECTED_EPOCH / "books"
    books.mkdir(parents=True)
    for name in ("signals", "commands", "orders", "fills", "positions", "trades"):
        (books / f"{name}.jsonl").write_text("", encoding="utf-8")
    epochs = repo / "data" / "trading" / "paper_epochs"
    epochs.mkdir(parents=True)
    (epochs / "active.json").write_text(
        json.dumps(
            {
                "paper_epoch_id": EXPECTED_EPOCH,
                "trading_contract_fingerprint": EXPECTED_ACTIVE_FP,
                "parent_trading_contract_fingerprint": EXPECTED_PARENT_FP,
            }
        )
        + "\n"
    )
    # Exact agg trades for M15 candle 18:15-18:30, decision 18:39
    agg_dir = repo / "data/raw_market_events_v2/agg_trade/date=2026-07-29/hour=18"
    agg_dir.mkdir(parents=True)
    rows = []
    # prices around 64000 with volume concentration at 63950
    for i, (px, qty) in enumerate(
        [
            (63950.00, 1.0),
            (63950.01, 0.2),
            (63949.99, 0.2),
            (64000.00, 0.1),
            (63800.00, 0.05),
            (64100.00, 0.05),
        ]
    ):
        rows.append(
            {
                "schema_version": "1.0.0",
                "stream_type": "AGG_TRADE",
                "symbol": "BTCUSDT",
                "exchange_event_timestamp": f"2026-07-29T18:20:0{i}.000000Z",
                "exchange_trade_timestamp": f"2026-07-29T18:20:0{i}.000000Z",
                "local_receive_timestamp": f"2026-07-29T18:20:0{i}.000000Z",
                "aggregate_trade_id": 1000 + i,
                "price": px,
                "quantity": qty,
                "quote_quantity": px * qty,
                "buyer_is_market_maker": i % 2 == 0,
            }
        )
    # duplicate trade id to test dedup
    rows.append({**rows[0], "quantity": 99.0, "quote_quantity": 99.0 * 63950.0})
    # future trade after decision — must be excluded by cutoff
    rows.append(
        {
            "schema_version": "1.0.0",
            "stream_type": "AGG_TRADE",
            "symbol": "BTCUSDT",
            "exchange_event_timestamp": "2026-07-29T18:45:00.000000Z",
            "exchange_trade_timestamp": "2026-07-29T18:45:00.000000Z",
            "local_receive_timestamp": "2026-07-29T18:45:00.000000Z",
            "aggregate_trade_id": 9999,
            "price": 65000.0,
            "quantity": 10.0,
            "quote_quantity": 650000.0,
            "buyer_is_market_maker": False,
        }
    )
    pd.DataFrame(rows).to_parquet(agg_dir / "agg_trade__test.parquet", index=False)

    book_dir = repo / "data/raw_market_events_v2/book_ticker/date=2026-07-29/hour=18"
    book_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "symbol": "BTCUSDT",
                "exchange_event_timestamp": "2026-07-29T18:40:00Z",
                "local_receive_timestamp": "2026-07-29T18:40:00Z",
                "update_id": 1,
                "best_bid_price": 64200.0,
                "best_ask_price": 64201.0,
                "spread": 1.0,
            }
        ]
    ).to_parquet(book_dir / "book__test.parquet", index=False)

    # M15 volume classification for candle 18:15
    (repo / "data/cognition").mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-29T18:15:00Z",
                "open": 63900.0,
                "high": 64100.0,
                "low": 63800.0,
                "close": 64000.0,
                "volume": 1.6,
                "volume_class": "climax",
            }
        ]
    ).to_parquet(repo / "data/cognition/volume_classification_memory.parquet", index=False)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-29T18:30:10Z",
                "source_timeframe": "M15",
                "source_candle_timestamp": "2026-07-29T18:15:00Z",
                "effort_result_state": "ABSORPTION_RESPONSE",
                "localized_behavior": "localized_absorption",
                "volume_event": "STOPPING_VOLUME",
                "unfinished_auction": False,
            }
        ]
    ).to_parquet(repo / "data/cognition/volume_response_state.parquet", index=False)

    # EQCORR dir present to ensure we don't write there
    (repo / "data/trading/shadow_economic_correlation").mkdir(parents=True)
    (repo / "data/trading/shadow_economic_correlation/health.json").write_text("{}\n")
    (repo / "data/runtime").mkdir(parents=True)
    return repo


def _seed_entry(repo: Path, *, tf: str = "M15") -> None:
    books = repo / "data/trading/intrabar_paper" / EXPECTED_EPOCH / "books"
    fill = {
        "fill_id": "fill1",
        "order_id": "ord1",
        "command_id": "cmd1",
        "action": "ENTRY",
        "timeframe": tf,
        "side": "LONG",
        "quantity": 1.0,
        "paper_fill_price": 64200.0,
        "ts": "2026-07-29T18:39:54Z",
        "best_bid": 64199.0,
        "best_ask": 64200.0,
        "risk_budget_usd": 1000.0,
        "entry_fee_bps": 2.0,
        "entry_slippage_bps": 3.0,
        "notional_usd": 64200.0,
        "equity_at_entry_usd": 100000.0,
    }
    pos = {
        "position_id": "pos1",
        "status": "OPEN",
        "timeframe": tf,
        "side": "LONG",
        "quantity": 1.0,
        "entry_price": 64200.0,
        "stop_loss_price": 63557.8,
        "take_profit_price": 65163.0,
        "entry_fill_id": "fill1",
        "entry_command_id": "cmd1",
        "entry_context_event_id": "ctx1",
        "lifecycle_episode_id": "ep1",
        "opened_at": "2026-07-29T18:39:54Z",
        "risk_budget_usd": 1000.0,
        "notional_usd": 64200.0,
        "equity_at_entry_usd": 100000.0,
    }
    for name, rows in (
        ("fills", [fill]),
        ("positions", [pos]),
        ("commands", [{"command_id": "cmd1", "signal_id": "sig1"}]),
        ("signals", [{"signal_id": "sig1", "context_event_id": "ctx1", "timeframe": tf}]),
    ):
        (books / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_write_boundary(stp_repo: Path):
    with pytest.raises(RuntimeError, match=WRITE_BOUNDARY_VIOLATION):
        assert_shadow_write_path(stp_repo / "data/trading/intrabar_paper/x.json", repo=stp_repo)
    with pytest.raises(RuntimeError, match=WRITE_BOUNDARY_VIOLATION):
        assert_shadow_write_path(stp_repo / "data/trading/shadow_economic_correlation/x.json", repo=stp_repo)


def test_no_paper_or_eqcorr_mutation(stp_repo: Path):
    _seed_entry(stp_repo)
    books = stp_repo / "data/trading/intrabar_paper" / EXPECTED_EPOCH / "books"
    before_books = {p.name: p.read_bytes() for p in books.glob("*.jsonl")}
    eq_before = (stp_repo / "data/trading/shadow_economic_correlation/health.json").read_bytes()
    active_before = (stp_repo / "data/trading/paper_epochs/active.json").read_bytes()
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    after_books = {p.name: p.read_bytes() for p in books.glob("*.jsonl")}
    assert before_books == after_books
    assert (stp_repo / "data/trading/shadow_economic_correlation/health.json").read_bytes() == eq_before
    assert (stp_repo / "data/trading/paper_epochs/active.json").read_bytes() == active_before


def test_exact_profile_dedup_conservation_and_no_future(stp_repo: Path):
    from btc_ml.trading.shadow_structural_protection.trades import load_agg_trades

    start = datetime(2026, 7, 29, 18, 15, tzinfo=timezone.utc)
    cutoff = datetime(2026, 7, 29, 18, 29, 59, tzinfo=timezone.utc)
    trades = load_agg_trades(repo=stp_repo, start=start, end=cutoff)
    # future 18:45 excluded by end filter
    assert trades["_ts"].max() < pd.Timestamp("2026-07-29T18:45:00Z")
    # dedup removes duplicate id
    assert trades["aggregate_trade_id"].is_unique
    p1 = build_exact_candle_volume_profile(trades, candle_start=start, causal_cutoff=cutoff)
    p2 = build_exact_candle_volume_profile(trades, candle_start=start, causal_cutoff=cutoff)
    assert p1["ok"] and p1["conservation_ok"]
    assert abs(p1["total_base_volume"] - p1["source_base_volume"]) < 1e-12
    assert p1["poc_price"] == pytest.approx(63950.0)
    assert p1["bins"] == p2["bins"]
    # future price not in profile
    assert all(b["price"] < 65000 for b in p1["bins"])


def test_zone_methods_and_geometry():
    profile = {
        "ok": True,
        "total_base_volume": 10.0,
        "poc_price": 100.0,
        "bins": [
            {"price": 99.0, "base_volume": 2.0, "quote_volume": 2.0, "buy_aggressor_volume": 1, "sell_aggressor_volume": 1},
            {"price": 100.0, "base_volume": 5.0, "quote_volume": 5.0, "buy_aggressor_volume": 2, "sell_aggressor_volume": 3},
            {"price": 101.0, "base_volume": 3.0, "quote_volume": 3.0, "buy_aggressor_volume": 1, "sell_aggressor_volume": 2},
        ],
    }
    zones = {z["zone_method"]: z for z in extract_zones(profile)}
    assert zones["POC_BIN"]["lower_boundary"] == 100.0
    assert zones["POC_VALUE_AREA_70"]["lower_boundary"] <= 100.0
    stop_l = structural_stop_price(
        side="LONG", zone=zones["POC_BIN"], buffer_policy="DISTAL_PLUS_ONE_TICK", tick_size=0.01, executable_spread=1.0
    )
    assert stop_l == pytest.approx(99.99)
    take_l = structural_take_price(side="LONG", zone={"lower_boundary": 110, "upper_boundary": 120, "peak_volume_price": 115}, take_policy="TP_POC")
    assert take_l == 115
    ok, _ = geometry_valid(side="LONG", entry=105, stop=100, take=110)
    assert ok
    ok2, reason = geometry_valid(side="LONG", entry=105, stop=106, take=110)
    assert not ok2 and reason == "SKIP_INVALID_STOP_GEOMETRY"


def test_wider_stop_reduces_quantity(stp_repo: Path):
    cfg = load_intrabar_paper_config(repo_root=stp_repo)
    tight = size_with_stop(
        cfg=cfg, side="LONG", entry_price=100.0, stop_price=99.0, take_price=102.0, equity_usd=100000, risk_budget_usd=1000
    )
    wide = size_with_stop(
        cfg=cfg, side="LONG", entry_price=100.0, stop_price=95.0, take_price=110.0, equity_usd=100000, risk_budget_usd=1000
    )
    assert tight["ok"] and wide["ok"]
    assert wide["quantity"] < tight["quantity"]
    # canonical helper path
    r = resolve_risk_sizing(cfg=cfg, side="LONG", entry_price=100.0, risk_budget_usd=1000, stop_loss_price=99.0, take_profit_price=102.0)
    assert r.ok and r.stop_loss_price == 99.0


def test_sleeve_isolation():
    sleeves = initial_policy_sleeves(policy_ids=("BASELINE_CANONICAL", "P2"))
    apply_realized(sleeves, policy_id="P2", timeframe="M15", net_pnl_usd=50)
    assert sleeves["P2"]["sleeves"]["M15"]["current_equity_usd"] == 100050
    assert sleeves["BASELINE_CANONICAL"]["sleeves"]["M15"]["current_equity_usd"] == 100000
    assert sleeves["P2"]["sleeves"]["H1"]["current_equity_usd"] == 100000


def test_engine_m15_ingest_and_idempotent(stp_repo: Path):
    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    assert eng.exact_ok
    eng.poll_once()
    c1 = len(eng.processed_candidates)
    d1 = len([d for d in eng.store.read_all("policy_decisions") if not d.get("record_type")])
    eng.poll_once()
    assert len(eng.processed_candidates) == c1 == 1
    d2 = len([d for d in eng.store.read_all("policy_decisions") if not d.get("record_type")])
    assert d2 == d1
    assert eng.lookahead_violation_count == 0
    assert eng.counters["exact_profile_count"] >= 1
    # M30 wrong TF classification path
    _seed_entry(stp_repo, tf="M30")
    # overwrite fill ids to new candidate
    books = stp_repo / "data/trading/intrabar_paper" / EXPECTED_EPOCH / "books"
    fill = json.loads((books / "fills.jsonl").read_text().splitlines()[0])
    fill.update({"fill_id": "fill2", "timeframe": "M30", "ts": "2026-07-29T18:39:55Z"})
    pos = json.loads((books / "positions.jsonl").read_text().splitlines()[0])
    pos.update({"position_id": "pos2", "entry_fill_id": "fill2", "timeframe": "M30", "opened_at": "2026-07-29T18:39:55Z"})
    (books / "fills.jsonl").write_text(json.dumps(fill) + "\n")
    (books / "positions.jsonl").write_text(json.dumps(pos) + "\n")
    eng2 = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng2.poll_once()
    # M30 should mark insufficient / skip protective due to WRONG_TIMEFRAME class
    assert eng2.insufficient_causal_data_count >= 1


def test_manifest_fingerprint_stable(stp_repo: Path):
    eng1 = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng2 = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    assert eng1.manifest_fp == eng2.manifest_fp
