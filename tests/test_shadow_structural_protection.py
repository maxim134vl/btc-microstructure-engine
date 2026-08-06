"""SHADOW-STP1 — isolation, causality, exact profile, geometry, economics, idempotency."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
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
    POLICY_SPECS,
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
    # Exact agg trades spanning multiple M15 bars for shadow classification history
    rows = []
    tid = 1000
    # History: 18:00-18:15 low volume, 18:15-18:30 high volume concentration at 63950
    for minute_base, vol_scale in [(0, 0.05), (15, 1.0)]:
        for i, (px_off, qty) in enumerate(
            [
                (0.00, 1.0 * vol_scale),
                (0.01, 0.2 * vol_scale),
                (-0.01, 0.2 * vol_scale),
                (50.00, 0.1 * vol_scale),
                (-150.00, 0.05 * vol_scale),
                (150.00, 0.05 * vol_scale),
            ]
        ):
            px = 63950.0 + px_off
            ts = f"2026-07-29T18:{minute_base + (i % 10):02d}:0{i}.000000Z"
            rows.append(
                {
                    "schema_version": "1.0.0",
                    "stream_type": "AGG_TRADE",
                    "symbol": "BTCUSDT",
                    "exchange_event_timestamp": ts,
                    "exchange_trade_timestamp": ts,
                    "local_receive_timestamp": ts,
                    "aggregate_trade_id": tid,
                    "price": px,
                    "quantity": qty,
                    "quote_quantity": px * qty,
                    "buyer_is_market_maker": i % 2 == 0,
                }
            )
            tid += 1
    # Additional low-volume history bars 16:00-17:45 for rolling percentiles
    for hour in (16, 17):
        for minute in (0, 15, 30, 45):
            for j in range(3):
                px = 63800.0 + j
                ts = f"2026-07-29T{hour:02d}:{minute:02d}:{j:02d}.000000Z"
                rows.append(
                    {
                        "schema_version": "1.0.0",
                        "stream_type": "AGG_TRADE",
                        "symbol": "BTCUSDT",
                        "exchange_event_timestamp": ts,
                        "exchange_trade_timestamp": ts,
                        "local_receive_timestamp": ts,
                        "aggregate_trade_id": tid,
                        "price": px,
                        "quantity": 0.02,
                        "quote_quantity": px * 0.02,
                        "buyer_is_market_maker": False,
                    }
                )
                tid += 1
    # Fresh raw-event tail inside the decision timeframe.
    fresh_tail_ts = "2026-07-29T18:39:53.000000Z"
    rows.append(
        {
            "schema_version": "1.0.0",
            "stream_type": "AGG_TRADE",
            "symbol": "BTCUSDT",
            "exchange_event_timestamp": fresh_tail_ts,
            "exchange_trade_timestamp": fresh_tail_ts,
            "local_receive_timestamp": fresh_tail_ts,
            "aggregate_trade_id": tid,
            "price": 64199.5,
            "quantity": 0.001,
            "quote_quantity": 64.1995,
            "buyer_is_market_maker": False,
        }
    )
    tid += 1

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
    # Write into hour partitions
    for hour in (16, 17, 18):
        agg_dir = repo / f"data/raw_market_events_v2/agg_trade/date=2026-07-29/hour={hour:02d}"
        agg_dir.mkdir(parents=True)
        subset = [r for r in rows if f"T{hour:02d}:" in r["exchange_trade_timestamp"] or (hour == 18 and "T18:" in r["exchange_trade_timestamp"])]
        # simpler: filter by hour in timestamp
        subset = [r for r in rows if f"T{hour:02d}:" in str(r["exchange_trade_timestamp"])]
        if subset:
            pd.DataFrame(subset).to_parquet(agg_dir / "agg_trade__test.parquet", index=False)

    book_dir = repo / "data/raw_market_events_v2/book_ticker/date=2026-07-29/hour=18"
    book_dir.mkdir(parents=True)
    # Reaction path after 18:30 candle close, before 18:39 decision: touch zone then displace up
    bbo_rows = []
    for i, (sec, bid, ask) in enumerate(
        [
            (31, 63950.0, 63950.5),  # touch
            (33, 63960.0, 63960.5),
            (35, 63980.0, 63980.5),  # displace above
            (37, 64050.0, 64050.5),
            (40, 64200.0, 64201.0),
        ]
    ):
        bbo_rows.append(
            {
                "symbol": "BTCUSDT",
                "exchange_event_timestamp": f"2026-07-29T18:{sec:02d}:00Z",
                "local_receive_timestamp": f"2026-07-29T18:{sec:02d}:00Z",
                "update_id": i + 1,
                "best_bid_price": bid,
                "best_ask_price": ask,
                "spread": ask - bid,
            }
        )
    pd.DataFrame(bbo_rows).to_parquet(book_dir / "book__test.parquet", index=False)

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
    import inspect

    cfg = load_intrabar_paper_config(repo_root=stp_repo)
    tight = size_with_stop(
        cfg=cfg, side="LONG", entry_price=100.0, stop_price=99.0, take_price=102.0, equity_usd=100000, risk_budget_usd=1000
    )
    wide = size_with_stop(
        cfg=cfg, side="LONG", entry_price=100.0, stop_price=95.0, take_price=110.0, equity_usd=100000, risk_budget_usd=1000
    )
    assert tight["ok"] and wide["ok"]
    assert wide["quantity"] < tight["quantity"]
    # canonical helper has no structural kwargs — LIVE1B cannot activate structural path
    sig = inspect.signature(resolve_risk_sizing)
    assert "stop_loss_price" not in sig.parameters
    assert "take_profit_price" not in sig.parameters
    r = resolve_risk_sizing(cfg=cfg, side="LONG", entry_price=100.0, risk_budget_usd=1000)
    assert r.ok
    # adapter encodes structural stop as temporary cfg bps
    assert tight["stop_loss_price"] == 99.0
    assert tight["sizing_path"] == "resolve_risk_sizing+cfg_bps_adapter"


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
    # M30 uses independent shadow classification (never copies M15 labels)
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
    snaps = [s for s in eng2.store.read_all("candidate_snapshots") if s.get("timeframe") == "M30"]
    assert snaps
    assert snaps[-1].get("classification_mode") == "SHADOW_RESEARCH"
    assert snaps[-1].get("classification", {}).get("status") != "WRONG_TIMEFRAME"


def test_manifest_fingerprint_stable(stp_repo: Path):
    eng1 = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng2 = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    assert eng1.manifest_fp == eng2.manifest_fp


def _decisions(eng: StructuralProtectionEngine) -> list[dict]:
    return [
        d
        for d in eng.store.read_all("policy_decisions")
        if not d.get("record_type") and d.get("policy_manifest_fingerprint") == eng.manifest_fp
    ]


def test_stp11_baseline_executes_without_structural_evidence(stp_repo: Path):
    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    base = [d for d in _decisions(eng) if d.get("policy_id") == "BASELINE_CANONICAL"]
    assert len(base) == 1
    assert base[0]["action"] == "EXECUTE_STRUCTURAL"
    assert base[0].get("protective_zone_usable") in (False, None)
    assert base[0].get("research_valid") is True


def test_stp11_structural_gates_require_usable_proven_zones(stp_repo: Path):
    """Fixture has protective reaction PROVEN (ABSORPTION) but target AMBIGUOUS/MISSING direction."""
    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    decs = _decisions(eng)

    for d in decs:
        if str(d.get("policy_id", "")).startswith("CANONICAL_SL_STRUCTURAL_TP"):
            assert d["action"] != "EXECUTE_STRUCTURAL"
            assert d["action"] in {"SKIP_NO_TARGET_ZONE", "SKIP_NO_REACTION_PROOF", "SKIP_INVALID_TARGET_GEOMETRY", "SKIP_INVALID_STOP_GEOMETRY", "SKIP_SIZING_REJECTED"}
            if d.get("target_zone_detected"):
                assert d.get("target_reaction_status") is not None
                assert d.get("target_reaction_status") != "PROVEN" or d["action"] != "EXECUTE_STRUCTURAL"

    for d in decs:
        pid = str(d.get("policy_id", ""))
        if pid.startswith("STRUCTURAL_SL_STRUCTURAL_TP") or pid.startswith("STRUCTURAL_SL_TP"):
            assert d["action"] != "EXECUTE_STRUCTURAL"

    # Economic gate never runs before evidence: SKIP_NON_ECONOMIC only after evidence
    for d in decs:
        if d.get("action") == "SKIP_NON_ECONOMIC_AFTER_COSTS":
            assert d.get("protective_zone_usable") or d.get("policy_id") == "BASELINE_CANONICAL"


def test_stp11_structural_sl_requires_protective_proven(stp_repo: Path):
    """Full structural SL+TP cannot execute without both sides usable/proven."""
    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    for d in _decisions(eng):
        pid = str(d.get("policy_id") or "")
        if pid.startswith("STRUCTURAL_SL_STRUCTURAL_TP") or pid.startswith("STRUCTURAL_SL_TP__"):
            if d["action"] == "EXECUTE_STRUCTURAL":
                assert d.get("protective_zone_usable") is True
                assert d.get("target_zone_usable") is True
                assert d.get("protective_reaction_status") == "PROVEN"
                assert d.get("target_reaction_status") == "PROVEN"
            else:
                assert d["action"] != "EXECUTE_STRUCTURAL" or (
                    d.get("protective_zone_usable") and d.get("target_zone_usable")
                )
        if pid.startswith("STRUCTURAL_SL_CANONICAL_TP") and d["action"] == "EXECUTE_STRUCTURAL":
            assert d.get("protective_zone_usable") is True
            assert d.get("protective_reaction_status") == "PROVEN"


def test_stp11_wrong_timeframe_skip(stp_repo: Path):
    """STP2: M30 is classified independently; M15 canonical labels are never copied."""
    _seed_entry(stp_repo, tf="M30")
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    snaps = eng.store.read_all("candidate_snapshots")
    assert snaps
    assert snaps[-1]["timeframe"] == "M30"
    assert snaps[-1].get("classification_mode") == "SHADOW_RESEARCH"
    # No decision should claim WRONG_TIMEFRAME solely because canonical memory is M15-only
    structural = [d for d in _decisions(eng) if d.get("policy_id") != "BASELINE_CANONICAL"]
    assert structural
    assert not any(d.get("decision_reason") == "WRONG_TIMEFRAME" for d in structural)


def test_stp11_detected_usable_counters_and_reaction_status(stp_repo: Path):
    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    h = eng.write_health()
    # With ABSORPTION protective can be detected+usable; target detected but not usable
    assert h["protective_zone_detected_count"] >= h["protective_zone_usable_count"]
    assert h["target_zone_detected_count"] >= h["target_zone_usable_count"]
    # Forbidden: zones detected with both reaction counters stuck at 0
    if h["protective_zone_detected_count"] or h["target_zone_detected_count"]:
        assert (h["reaction_proven_count"] + h["reaction_missing_count"]) > 0
    for d in _decisions(eng):
        if d.get("protective_zone_detected"):
            assert d.get("protective_reaction_status") is not None
        if d.get("target_zone_detected"):
            assert d.get("target_reaction_status") is not None


def test_stp11_canonical_economics_isolation(stp_repo: Path):
    import inspect
    import re

    from btc_ml.trading.intrabar_paper import economics as eco

    sig = inspect.signature(eco.resolve_risk_sizing)
    assert "stop_loss_price" not in sig.parameters
    assert "take_profit_price" not in sig.parameters
    live1b_path = Path(eco.__file__).resolve().parent / "engine.py"
    text = live1b_path.read_text(encoding="utf-8")
    for call in re.findall(r"resolve_risk_sizing\((.*?)\)", text, flags=re.S):
        assert "stop_loss_price" not in call
        assert "take_profit_price" not in call
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    h = eng.write_health()
    assert h["canonical_economics_isolated"] is True


def test_stp11_invalidated_manifest_excluded_from_valid_metrics(stp_repo: Path):
    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    # Inject legacy invalid open structural position
    eng.store.append(
        "virtual_positions",
        {
            "virtual_position_id": "vpos_legacy_bad",
            "policy_id": "CANONICAL_SL_STRUCTURAL_TP__ALL_CANONICAL_SIGNIFICANT__POC_BIN__TP_POC",
            "candidate_id": "legacy|cand",
            "position_id": "pos_legacy",
            "timeframe": "M15",
            "side": "LONG",
            "status": "OPEN",
            "research_valid": False,
            "invalidated": True,
            "invalidated_virtual": True,
            "policy_manifest_fingerprint": "deadbeef",
        },
    )
    h = eng.write_health()
    assert h["virtual_positions_open"] == len(eng._valid_open_positions())
    assert all(p.get("policy_manifest_fingerprint") == eng.manifest_fp for p in eng._valid_open_positions())
    assert all(p.get("policy_id") == "BASELINE_CANONICAL" or p.get("research_valid") for p in eng._valid_open_positions())


def test_stp_strict_start_requires_readable_active_contract(stp_repo: Path):
    active = stp_repo / "data" / "trading" / "paper_epochs" / "active.json"
    active.unlink()

    with pytest.raises(
        RuntimeError,
        match="SOURCE_EPOCH_MISMATCH: active contract unreadable",
    ):
        StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)


def _rows_for_candidate(
    eng: StructuralProtectionEngine,
    table: str,
    candidate_id: str,
) -> list[dict]:
    return [
        row
        for row in eng.store.read_all(table)
        if row.get("candidate_id") == candidate_id
    ]


def test_candidate_partial_write_rolls_back_and_retries_once(
    stp_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    candidate_id = f"{EXPECTED_EPOCH}|pos1|fill1"

    original_append = eng.store.append
    raised = {"value": False}

    def flaky_append(table: str, row: dict):
        result = original_append(table, row)
        if (
            table == "policy_decisions"
            and not row.get("record_type")
            and not raised["value"]
        ):
            raised["value"] = True
            raise RuntimeError("SIMULATED_CANDIDATE_CRASH")
        return result

    monkeypatch.setattr(eng.store, "append", flaky_append)
    result = eng.process_new_entries()

    assert result[0]["status"] == "INGEST_ERROR"
    assert candidate_id not in eng.processed_candidates
    assert not eng.store.read_inflight()

    for table in eng.store.TABLES:
        assert not _rows_for_candidate(
            eng,
            table,
            candidate_id,
        )

    monkeypatch.setattr(eng.store, "append", original_append)
    eng.process_new_entries()

    assert candidate_id in eng.processed_candidates

    assert len(
        _rows_for_candidate(
            eng,
            "candidate_snapshots",
            candidate_id,
        )
    ) == 1

    assert len(
        _rows_for_candidate(
            eng,
            "policy_decisions",
            candidate_id,
        )
    ) == len(POLICY_SPECS)

    before = {
        table: len(
            _rows_for_candidate(eng, table, candidate_id)
        )
        for table in eng.store.TABLES
    }

    restarted = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    restarted.process_new_entries()

    after = {
        table: len(
            _rows_for_candidate(
                restarted,
                table,
                candidate_id,
            )
        )
        for table in restarted.store.TABLES
    }

    assert after == before


def test_restart_rolls_back_uncommitted_candidate_transaction(
    stp_repo: Path,
):
    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    candidate_id = f"{EXPECTED_EPOCH}|pos1|fill1"

    eng.store.begin_transaction(
        kind="candidate",
        key=candidate_id,
        base_generation=eng.state_generation,
    )
    eng.store.append(
        "candidate_snapshots",
        {
            "candidate_id": candidate_id,
            "policy_manifest_fingerprint": eng.manifest_fp,
            "simulated_partial": True,
        },
    )

    marker = eng.store.read_inflight()
    marker["owner_pid"] = 2_147_483_647
    eng.store.write_json(
        eng.store.INFLIGHT_NAME,
        marker,
    )

    restarted = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )

    assert (
        restarted.transaction_recovery["status"]
        == "ROLLED_BACK"
    )
    assert not restarted.store.read_inflight()
    assert not _rows_for_candidate(
        restarted,
        "candidate_snapshots",
        candidate_id,
    )

    restarted.process_new_entries()

    assert len(
        _rows_for_candidate(
            restarted,
            "candidate_snapshots",
            candidate_id,
        )
    ) == 1


def test_no_candidate_close_is_not_marked_processed_or_reclaimed(
    stp_repo: Path,
):
    books = (
        stp_repo
        / "data/trading/intrabar_paper"
        / EXPECTED_EPOCH
        / "books"
    )

    trade = {
        "trade_id": "trade_without_candidate",
        "position_id": "missing_position",
        "exit_ts": "2026-07-29T18:40:00Z",
        "exit_price": 64300.0,
        "exit_reason": "CONTEXT_END",
        "net_pnl_usd": 0.0,
    }

    (books / "trades.jsonl").write_text(
        json.dumps(trade) + "\n",
        encoding="utf-8",
    )

    eng = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )

    first = eng.process_new_closes()
    second = eng.process_new_closes()

    assert first[0]["status"] == "NO_CANDIDATE"
    assert second[0]["status"] == "NO_CANDIDATE"
    assert trade["trade_id"] not in eng.processed_closes

    assert not any(
        "reclaimed_stale_processed_closes" in error
        for error in eng.errors
    )


def test_partial_close_rolls_back_then_closes_once(
    stp_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    eng.process_new_entries()

    books = (
        stp_repo
        / "data/trading/intrabar_paper"
        / EXPECTED_EPOCH
        / "books"
    )

    trade = {
        "trade_id": "trade1",
        "position_id": "pos1",
        "exit_ts": "2026-07-29T18:40:00Z",
        "exit_price": 64300.0,
        "exit_reason": "CONTEXT_END",
        "net_pnl_usd": 0.0,
    }

    (books / "trades.jsonl").write_text(
        json.dumps(trade) + "\n",
        encoding="utf-8",
    )

    original_append = eng.store.append
    raised = {"value": False}

    def flaky_append(table: str, row: dict):
        result = original_append(table, row)
        if table == "virtual_trades" and not raised["value"]:
            raised["value"] = True
            raise RuntimeError("SIMULATED_CLOSE_CRASH")
        return result

    monkeypatch.setattr(eng.store, "append", flaky_append)
    failed = eng.process_new_closes()

    assert failed[0]["status"] == "CLOSE_ERROR"
    assert trade["trade_id"] not in eng.processed_closes

    assert not [
        row
        for row in eng.store.read_all("virtual_trades")
        if row.get("trade_id") == trade["trade_id"]
    ]

    monkeypatch.setattr(eng.store, "append", original_append)
    eng.process_new_closes()

    assert trade["trade_id"] in eng.processed_closes

    baseline = [
        row
        for row in eng.store.read_all("virtual_trades")
        if row.get("trade_id") == trade["trade_id"]
        and row.get("policy_id") == "BASELINE_CANONICAL"
    ]
    assert len(baseline) == 1

    restarted = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    restarted.process_new_closes()

    baseline_after_restart = [
        row
        for row in restarted.store.read_all("virtual_trades")
        if row.get("trade_id") == trade["trade_id"]
        and row.get("policy_id") == "BASELINE_CANONICAL"
    ]
    assert len(baseline_after_restart) == 1


def test_checkpoint_sleeves_are_authoritative_after_restart(
    stp_repo: Path,
):
    eng = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )

    eng.sleeves["BASELINE_CANONICAL"]["sleeves"]["M15"][
        "current_equity_usd"
    ] = 123456.0
    eng._save_checkpoint()

    mirror = eng.store.read_json("policy_sleeves.json")
    mirror["BASELINE_CANONICAL"]["sleeves"]["M15"][
        "current_equity_usd"
    ] = 999.0
    eng.store.write_json("policy_sleeves.json", mirror)

    restarted = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )

    assert (
        restarted.sleeves["BASELINE_CANONICAL"]["sleeves"]["M15"][
            "current_equity_usd"
        ]
        == 123456.0
    )


def test_live_transaction_owner_blocks_duplicate_engine(
    stp_repo: Path,
):
    eng = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )

    eng.store.begin_transaction(
        kind="candidate",
        key="live_candidate",
        base_generation=eng.state_generation,
    )

    try:
        with pytest.raises(
            RuntimeError,
            match="SHADOW_TRANSACTION_OWNER_ALIVE",
        ):
            StructuralProtectionEngine(
                repo=stp_repo,
                strict_epoch=True,
            )
    finally:
        eng.store.clear_inflight()


def test_atomic_transaction_claim_rejects_second_owner(
    stp_repo: Path,
):
    eng = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )

    eng.store.begin_transaction(
        kind="candidate",
        key="exclusive_candidate",
        base_generation=eng.state_generation,
    )

    try:
        with pytest.raises(
            RuntimeError,
            match="SHADOW_TRANSACTION_ALREADY_ACTIVE",
        ):
            eng.store.begin_transaction(
                kind="candidate",
                key="second_candidate",
                base_generation=eng.state_generation,
            )
    finally:
        eng.store.clear_inflight()


def test_committed_checkpoint_clears_leftover_marker(
    stp_repo: Path,
):
    eng = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    candidate_id = "committed_candidate"

    eng.store.begin_transaction(
        kind="candidate",
        key=candidate_id,
        base_generation=eng.state_generation,
    )
    eng.processed_candidates.add(candidate_id)
    eng._save_checkpoint()

    restarted = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )

    assert (
        restarted.transaction_recovery["status"]
        == "COMMITTED_MARKER_CLEARED"
    )
    assert candidate_id in restarted.processed_candidates
    assert not restarted.store.read_inflight()


def test_policy_sleeves_mirror_failure_does_not_fail_commit(
    stp_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    eng = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    original_write_json = eng.store.write_json
    generation_before = eng.state_generation

    def flaky_write_json(name: str, payload: dict):
        if name == "policy_sleeves.json":
            raise OSError("SIMULATED_MIRROR_FAILURE")
        return original_write_json(name, payload)

    monkeypatch.setattr(
        eng.store,
        "write_json",
        flaky_write_json,
    )

    eng._save_checkpoint()

    checkpoint = original_write_json
    _ = checkpoint
    persisted = eng.store.read_json("checkpoint.json")

    assert (
        int(persisted["state_generation"])
        == generation_before + 1
    )
    assert "policy_sleeves" in persisted
    assert any(
        error
        == "policy_sleeves_mirror:"
        "SIMULATED_MIRROR_FAILURE"
        for error in eng.errors
    )



def test_causal_coverage_requires_minimum_history_and_fresh_tail():
    from btc_ml.trading.shadow_structural_protection.catalog import (
        lookback_coverage,
    )

    decision = datetime(
        2026,
        7,
        29,
        18,
        39,
        54,
        tzinfo=timezone.utc,
    )

    bars = []

    for offset in range(5):
        natural_close = decision - timedelta(
            minutes=5 + (4 - offset) * 15
        )
        bars.append(
            {
                "incomplete": False,
                "open_timestamp": (
                    natural_close
                    - timedelta(minutes=15)
                ).isoformat(),
                "natural_close_timestamp": (
                    natural_close.isoformat()
                ),
            }
        )

    fresh_trades = pd.DataFrame(
        {
            "_ts": [
                pd.Timestamp(
                    decision
                    - timedelta(seconds=10)
                )
            ]
        }
    )

    fresh = lookback_coverage(
        timeframe="M15",
        decision_ts=decision,
        bars=bars,
        trades=fresh_trades,
    )

    assert fresh["coverage_ok"] is True
    assert fresh["coverage_reasons"] == []
    assert (
        fresh["minimum_closed_bars_required"]
        == 5
    )
    assert fresh["max_tail_lag_seconds"] == 900

    stale_bars = []

    for bar in bars:
        stale_bars.append(
            {
                **bar,
                "open_timestamp": (
                    datetime.fromisoformat(
                        bar["open_timestamp"]
                    )
                    - timedelta(hours=2)
                ).isoformat(),
                "natural_close_timestamp": (
                    datetime.fromisoformat(
                        bar[
                            "natural_close_timestamp"
                        ]
                    )
                    - timedelta(hours=2)
                ).isoformat(),
            }
        )

    stale_trades = pd.DataFrame(
        {
            "_ts": [
                pd.Timestamp(
                    decision
                    - timedelta(hours=2)
                )
            ]
        }
    )

    stale = lookback_coverage(
        timeframe="M15",
        decision_ts=decision,
        bars=stale_bars,
        trades=stale_trades,
    )

    assert stale["coverage_ok"] is False
    assert (
        "STALE_TRADE_EVENT_TAIL"
        in stale["coverage_reasons"]
    )
    assert (
        "STALE_CLOSED_BAR_TAIL"
        in stale["coverage_reasons"]
    )


def test_insufficient_history_is_not_catalog_defect():
    from btc_ml.trading.shadow_structural_protection.catalog import (
        audit_target_absence,
    )
    from btc_ml.trading.shadow_structural_protection.coverage import (
        aggregate_target_absence,
    )

    audit = audit_target_absence(
        zones=[],
        side="LONG",
        coverage={
            "coverage_ok": False,
            "coverage_status": (
                "INSUFFICIENT_CAUSAL_HISTORY"
            ),
            "coverage_reasons": [
                "NO_TRADE_EVENTS"
            ],
        },
    )

    assert (
        audit["verdict"]
        == "INSUFFICIENT_CAUSAL_HISTORY_NOT_EVALUABLE"
    )

    aggregate = aggregate_target_absence(
        [audit]
    )

    assert (
        aggregate["search_or_catalog_defect"]
        is False
    )
    assert (
        aggregate["insufficient_causal_history"]
        is True
    )
    assert (
        aggregate[
            "insufficient_causal_history_count"
        ]
        == 1
    )
    assert aggregate["legitimate_absence"] is False


def test_coverage_integrity_checks_contract_consistency():
    from btc_ml.trading.shadow_structural_protection.coverage import (
        coverage_integrity_ok,
    )

    ok, blockers = coverage_integrity_ok(
        m15_parity={
            "compared": 0,
            "status": (
                "NOT_EVALUABLE_INSUFFICIENT_OVERLAP"
            ),
        },
        execute_proof={"proof_ok": True},
        target_audit={
            "search_or_catalog_defect": False
        },
        bar_coverage={
            "explanation": "test"
        },
        lookback_by_tf={
            "M15": {
                "coverage_ok": False,
                "coverage_reasons": [
                    "NO_TRADE_EVENTS"
                ],
            }
        },
    )

    assert ok is True
    assert blockers == []

    bad_ok, bad_blockers = (
        coverage_integrity_ok(
            m15_parity={
                "compared": 0,
                "status": (
                    "NOT_EVALUABLE_"
                    "INSUFFICIENT_OVERLAP"
                ),
            },
            execute_proof={"proof_ok": True},
            target_audit={
                "search_or_catalog_defect": False
            },
            bar_coverage={
                "explanation": "test"
            },
            lookback_by_tf={
                "M15": {
                    "coverage_ok": True,
                    "coverage_reasons": [
                        "STALE_TRADE_EVENT_TAIL"
                    ],
                }
            },
        )
    )

    assert bad_ok is False
    assert (
        "M15_COVERAGE_OK_WITH_REASONS"
        in bad_blockers
    )


def test_insufficient_history_keeps_baseline_only(
    stp_repo: Path,
):
    from btc_ml.trading.shadow_structural_protection import (
        READY_BLOCKED_HISTORY,
    )

    _seed_entry(
        stp_repo,
        tf="M15",
    )

    books = (
        stp_repo
        / "data/trading/intrabar_paper"
        / EXPECTED_EPOCH
        / "books"
    )

    fill = json.loads(
        (
            books / "fills.jsonl"
        ).read_text(
            encoding="utf-8"
        )
    )
    position = json.loads(
        (
            books / "positions.jsonl"
        ).read_text(
            encoding="utf-8"
        )
    )

    fill["ts"] = (
        "2026-07-31T18:39:54Z"
    )
    position["opened_at"] = (
        "2026-07-31T18:39:54Z"
    )

    (
        books / "fills.jsonl"
    ).write_text(
        json.dumps(fill) + "\n",
        encoding="utf-8",
    )
    (
        books / "positions.jsonl"
    ).write_text(
        json.dumps(position) + "\n",
        encoding="utf-8",
    )

    engine = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    engine.poll_once()

    decisions = _decisions(engine)
    baseline = [
        row
        for row in decisions
        if row.get("policy_id")
        == "BASELINE_CANONICAL"
    ]
    structural = [
        row
        for row in decisions
        if row.get("policy_id")
        != "BASELINE_CANONICAL"
    ]

    assert len(decisions) == len(POLICY_SPECS)
    assert len(baseline) == 1
    assert (
        baseline[0]["action"]
        == "EXECUTE_STRUCTURAL"
    )
    assert (
        baseline[0]["research_valid"]
        is True
    )

    assert structural
    assert all(
        row["action"]
        == "SKIP_INSUFFICIENT_CAUSAL_HISTORY"
        for row in structural
    )
    assert all(
        row["research_valid"] is False
        for row in structural
    )

    snapshot = engine.store.read_all(
        "candidate_snapshots"
    )[-1]

    assert (
        snapshot["causal_history_ok"]
        is False
    )
    assert (
        snapshot["exact_profile_ok"]
        is False
    )
    assert snapshot["zones_detected"] == 0
    assert (
        snapshot[
            "target_absence_audit"
        ]["verdict"]
        == "INSUFFICIENT_CAUSAL_HISTORY_NOT_EVALUABLE"
    )

    health = engine.write_health()

    assert (
        health["status"]
        == READY_BLOCKED_HISTORY
    )
    assert (
        health["coverage_integrity_ok"]
        is True
    )
    assert health["research_valid"] is False
    assert (
        health[
            "target_usable_absence_audit"
        ]["search_or_catalog_defect"]
        is False
    )



def test_catchup_status_requires_full_source_universe(
    stp_repo: Path,
):
    from btc_ml.trading.shadow_structural_protection import (
        STATUS_STP21_CATCHUP,
    )

    _seed_entry(stp_repo, tf="M15")

    books = (
        stp_repo
        / "data/trading/intrabar_paper"
        / EXPECTED_EPOCH
        / "books"
    )

    fill_1 = json.loads(
        (books / "fills.jsonl").read_text(
            encoding="utf-8"
        )
    )
    position_1 = json.loads(
        (books / "positions.jsonl").read_text(
            encoding="utf-8"
        )
    )

    fill_2 = {
        **fill_1,
        "fill_id": "fill2",
        "order_id": "ord2",
        "command_id": "cmd2",
        "ts": "2026-07-29T18:39:55Z",
    }
    position_2 = {
        **position_1,
        "position_id": "pos2",
        "entry_fill_id": "fill2",
        "entry_command_id": "cmd2",
        "opened_at": "2026-07-29T18:39:55Z",
    }

    (books / "fills.jsonl").write_text(
        json.dumps(fill_1)
        + "\n"
        + json.dumps(fill_2)
        + "\n",
        encoding="utf-8",
    )
    (books / "positions.jsonl").write_text(
        json.dumps(position_1)
        + "\n"
        + json.dumps(position_2)
        + "\n",
        encoding="utf-8",
    )
    (books / "commands.jsonl").write_text(
        json.dumps(
            {
                "command_id": "cmd1",
                "signal_id": "sig1",
            }
        )
        + "\n"
        + json.dumps(
            {
                "command_id": "cmd2",
                "signal_id": "sig2",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (books / "signals.jsonl").write_text(
        json.dumps(
            {
                "signal_id": "sig1",
                "context_event_id": "ctx1",
                "timeframe": "M15",
            }
        )
        + "\n"
        + json.dumps(
            {
                "signal_id": "sig2",
                "context_event_id": "ctx2",
                "timeframe": "M15",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    engine = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )

    engine.poll_once()
    first = engine.write_health()

    assert first["source_candidate_count"] == 2
    assert (
        first["processed_source_candidate_count"]
        == 1
    )
    assert first["remaining_candidate_count"] == 1
    assert (
        first["unexpected_processed_candidate_count"]
        == 0
    )
    assert first["catchup_complete"] is False
    assert (
        first["coverage_integrity_scope"]
        == "PROCESSED_SUBSET"
    )
    assert first["status"] == STATUS_STP21_CATCHUP
    assert first["research_valid"] is False

    engine.poll_once()
    second = engine.write_health()

    assert second["source_candidate_count"] == 2
    assert (
        second["processed_source_candidate_count"]
        == 2
    )
    assert second["remaining_candidate_count"] == 0
    assert (
        second["unexpected_processed_candidate_count"]
        == 0
    )
    assert second["catchup_complete"] is True
    assert (
        second["coverage_integrity_scope"]
        == "FULL_SOURCE_UNIVERSE"
    )
    assert second["status"] != STATUS_STP21_CATCHUP



def test_attached_close_outcome_reconciles_stale_open_without_duplicate_pnl(
    stp_repo: Path,
):
    _seed_entry(stp_repo, tf="M15")

    engine = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    engine.process_new_entries()

    books = (
        stp_repo
        / "data/trading/intrabar_paper"
        / EXPECTED_EPOCH
        / "books"
    )

    trade = {
        "trade_id": "trade_exactly_once",
        "position_id": "pos1",
        "exit_ts": "2026-07-29T18:40:00Z",
        "exit_price": 64300.0,
        "exit_reason": "CONTEXT_END",
        "net_pnl_usd": 0.0,
    }

    (books / "trades.jsonl").write_text(
        json.dumps(trade) + "\n",
        encoding="utf-8",
    )

    first = engine.process_new_closes()

    assert first[0]["status"] == "CLOSED"
    assert (
        trade["trade_id"]
        in engine.processed_closes
    )

    baseline_outcomes = [
        row
        for row in engine.store.read_all(
            "virtual_trades"
        )
        if (
            row.get("trade_id")
            == trade["trade_id"]
            and row.get("policy_id")
            == "BASELINE_CANONICAL"
            and row.get(
                "policy_manifest_fingerprint"
            )
            == engine.manifest_fp
        )
    ]

    assert len(baseline_outcomes) == 1

    baseline_sleeve = engine.sleeves[
        "BASELINE_CANONICAL"
    ]["sleeves"]["M15"]

    before_pnl = float(
        baseline_sleeve[
            "cumulative_realized_net_pnl_usd"
        ]
    )
    before_equity = float(
        baseline_sleeve[
            "current_equity_usd"
        ]
    )
    before_closed_count = int(
        baseline_sleeve[
            "closed_trades_count"
        ]
    )
    before_match_count = int(
        engine.baseline_match_count
    )

    closed_position = [
        row
        for row in engine.store.read_all(
            "virtual_positions"
        )
        if (
            row.get("policy_id")
            == "BASELINE_CANONICAL"
            and row.get("position_id")
            == "pos1"
            and row.get("status")
            == "CLOSED"
            and row.get(
                "policy_manifest_fingerprint"
            )
            == engine.manifest_fp
        )
    ][-1]

    stale_open = {
        key: value
        for key, value
        in closed_position.items()
        if key
        not in {
            "exit_timestamp",
            "exit_price",
            "exit_reason",
            "outcome_already_attached",
            "state_reconciled_without_pnl",
        }
    }
    stale_open["status"] = "OPEN"

    engine.store.append(
        "virtual_positions",
        stale_open,
    )
    engine._rebuild_open_index()

    baseline_sleeve[
        "open_position_id"
    ] = stale_open["virtual_position_id"]

    second = engine.process_new_closes()

    assert second[0]["status"] == "CLOSED"
    assert (
        trade["trade_id"]
        in engine.processed_closes
    )

    baseline_after = [
        row
        for row in engine.store.read_all(
            "virtual_trades"
        )
        if (
            row.get("trade_id")
            == trade["trade_id"]
            and row.get("policy_id")
            == "BASELINE_CANONICAL"
            and row.get(
                "policy_manifest_fingerprint"
            )
            == engine.manifest_fp
        )
    ]

    assert len(baseline_after) == 1

    latest_position = [
        row
        for row in engine.store.read_all(
            "virtual_positions"
        )
        if (
            row.get("policy_id")
            == "BASELINE_CANONICAL"
            and row.get("position_id")
            == "pos1"
            and row.get(
                "policy_manifest_fingerprint"
            )
            == engine.manifest_fp
        )
    ][-1]

    assert latest_position["status"] == "CLOSED"
    assert (
        latest_position[
            "outcome_already_attached"
        ]
        is True
    )
    assert (
        latest_position[
            "state_reconciled_without_pnl"
        ]
        is True
    )

    baseline_sleeve_after = engine.sleeves[
        "BASELINE_CANONICAL"
    ]["sleeves"]["M15"]

    assert float(
        baseline_sleeve_after[
            "cumulative_realized_net_pnl_usd"
        ]
    ) == before_pnl

    assert float(
        baseline_sleeve_after[
            "current_equity_usd"
        ]
    ) == before_equity

    assert int(
        baseline_sleeve_after[
            "closed_trades_count"
        ]
    ) == before_closed_count

    assert (
        baseline_sleeve_after[
            "open_position_id"
        ]
        is None
    )

    assert (
        engine.baseline_match_count
        == before_match_count
    )

    restarted = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )
    restarted.process_new_closes()

    baseline_after_restart = [
        row
        for row in restarted.store.read_all(
            "virtual_trades"
        )
        if (
            row.get("trade_id")
            == trade["trade_id"]
            and row.get("policy_id")
            == "BASELINE_CANONICAL"
            and row.get(
                "policy_manifest_fingerprint"
            )
            == restarted.manifest_fp
        )
    ]

    assert len(baseline_after_restart) == 1


def test_manifest_declares_close_outcome_idempotency_contract(
    stp_repo: Path,
):
    engine = StructuralProtectionEngine(
        repo=stp_repo,
        strict_epoch=True,
    )

    assert (
        engine.manifest[
            "shadow_model_version"
        ]
        == "SHADOW_STP2_1_V3"
    )
    assert (
        engine.manifest[
            "close_outcome_idempotency_contract"
        ]
        == "STP2_1_POLICY_TRADE_EXACTLY_ONCE_V1"
    )
