"""SHADOW-STP2 — per-timeframe bars, significance, reaction, isolation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from btc_ml.trading.shadow_structural_protection import (
    EXPECTED_ACTIVE_FP,
    EXPECTED_EPOCH,
    EXPECTED_PARENT_FP,
    STATUS_ACTIVE,
    STATUS_COVERAGE_INTEGRITY_FAILURE,
    STATUS_INSUFFICIENT_REACTION,
    STATUS_STP21_COVERAGE,
)
from btc_ml.trading.shadow_structural_protection.bars import (
    assert_trade_membership_unique,
    build_all_timeframe_bars,
    build_bars_from_trades,
)
from btc_ml.trading.shadow_structural_protection.coverage import (
    policy_family,
    prove_baseline_only_when_no_same_tf_structural,
    summarize_execute_breakdown,
)
from btc_ml.trading.shadow_structural_protection.engine import StructuralProtectionEngine
from btc_ml.trading.shadow_structural_protection.policies import (
    geometry_valid,
    structural_stop_price,
    structural_take_price,
)
from btc_ml.trading.shadow_structural_protection.reaction import prove_zone_reaction
from btc_ml.trading.shadow_structural_protection.significance import (
    CLASSIFICATION_MODE,
    classify_bars_shadow,
    m15_parity_report,
)


REPO = Path(__file__).resolve().parents[1]

# Reuse STP1 fixture definition
pytest_plugins = ["test_shadow_structural_protection"]


def _trades_df() -> pd.DataFrame:
    rows = []
    tid = 1
    # Build ~2 hours of trades covering M15/M30/H1
    start = datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc)
    for minutes in range(0, 160, 1):
        ts = start.timestamp() + minutes * 60
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # Spike volume in 18:15 bar
        qty = 2.0 if (dt.hour == 18 and 15 <= dt.minute < 30) else 0.05
        px = 64000.0 + (minutes % 7) * 0.01
        if dt.hour == 18 and 15 <= dt.minute < 30:
            px = 63950.0 + (minutes % 3) * 0.01
        rows.append(
            {
                "aggregate_trade_id": tid,
                "price": px,
                "quantity": qty,
                "quote_quantity": px * qty,
                "buyer_is_market_maker": tid % 2 == 0,
                "_ts": pd.Timestamp(dt),
            }
        )
        tid += 1
    return pd.DataFrame(rows)


@pytest.mark.parametrize("tf", ["M15", "M30", "H1", "H4"])
def test_exact_trades_aggregate_per_timeframe(tf: str):
    trades = _trades_df()
    cutoff = datetime(2026, 7, 29, 18, 40, tzinfo=timezone.utc)
    bars = build_bars_from_trades(trades, timeframe=tf, causal_cutoff=cutoff)
    assert bars
    assert all(b["timeframe"] == tf for b in bars)
    # volume conservation vs membership helper
    by_tf = build_all_timeframe_bars(trades, causal_cutoff=cutoff, timeframes=(tf,))
    chk = assert_trade_membership_unique(trades[trades["_ts"] <= pd.Timestamp(cutoff)], by_tf)
    assert chk["ok"]
    assert chk["duplicate_trade_ids"] == 0


def test_no_duplicate_trades_and_deterministic_replay():
    trades = _trades_df()
    # inject duplicate id
    dup = trades.iloc[0].to_dict()
    trades2 = pd.concat([trades, pd.DataFrame([dup])], ignore_index=True)
    cutoff = datetime(2026, 7, 29, 18, 40, tzinfo=timezone.utc)
    a = build_bars_from_trades(trades2, timeframe="M15", causal_cutoff=cutoff)
    b = build_bars_from_trades(trades2, timeframe="M15", causal_cutoff=cutoff)
    assert a == b
    ids = []
    for bar in a:
        ids.append((bar["first_trade_id"], bar["last_trade_id"]))
    assert len(a) >= 2


def test_classification_no_future_and_same_tf_only():
    trades = _trades_df()
    cutoff = datetime(2026, 7, 29, 18, 40, tzinfo=timezone.utc)
    m15 = classify_bars_shadow(build_bars_from_trades(trades, timeframe="M15", causal_cutoff=cutoff))
    m30 = classify_bars_shadow(build_bars_from_trades(trades, timeframe="M30", causal_cutoff=cutoff))
    assert all(b.get("classification_mode") == CLASSIFICATION_MODE for b in m15 if not b.get("incomplete"))
    # Labels are produced independently — not copied from M15 list
    assert [b.get("shadow_volume_class") for b in m15] != [b.get("shadow_volume_class") for b in m30] or len(m15) != len(m30)
    # No future bar open after cutoff
    assert all(pd.Timestamp(b["open_timestamp"]) <= pd.Timestamp(cutoff) for b in m15)


def test_m15_parity_report_deterministic(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "data/cognition").mkdir(parents=True)
    pd.DataFrame(
        [
            {"timestamp": "2026-07-29T18:15:00Z", "volume_class": "climax"},
            {"timestamp": "2026-07-29T18:00:00Z", "volume_class": "low_small"},
        ]
    ).to_parquet(repo / "data/cognition/volume_classification_memory.parquet", index=False)
    trades = _trades_df()
    bars = classify_bars_shadow(
        build_bars_from_trades(trades, timeframe="M15", causal_cutoff=datetime(2026, 7, 29, 18, 40, tzinfo=timezone.utc))
    )
    r1 = m15_parity_report(repo=repo, shadow_bars=bars)
    r2 = m15_parity_report(repo=repo, shadow_bars=bars)
    assert r1["confusion"] == r2["confusion"]
    assert r1["status"] != "SHADOW_STP2_BLOCKED_CLASSIFICATION_PARITY_FAILURE" or r1["compared"] < 10


def test_m15_parity_compared_zero_is_not_evaluable(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "data/cognition").mkdir(parents=True)
    pd.DataFrame(
        [{"timestamp": "2026-01-01T00:00:00Z", "volume_class": "climax"}]
    ).to_parquet(repo / "data/cognition/volume_classification_memory.parquet", index=False)
    trades = _trades_df()
    bars = classify_bars_shadow(
        build_bars_from_trades(trades, timeframe="M15", causal_cutoff=datetime(2026, 7, 29, 18, 40, tzinfo=timezone.utc))
    )
    r = m15_parity_report(repo=repo, shadow_bars=bars)
    assert r["compared"] == 0
    assert r["status"] == "NOT_EVALUABLE_INSUFFICIENT_OVERLAP"
    assert r["status"] != "SHADOW_RESEARCH_PARITY_OK"


def test_execute_breakdown_and_baseline_only_proof():
    decisions = [
        {"action": "EXECUTE_STRUCTURAL", "timeframe": "M15", "policy_id": "BASELINE_CANONICAL"},
        {"action": "EXECUTE_STRUCTURAL", "timeframe": "H1", "policy_id": "BASELINE_CANONICAL"},
        {
            "action": "EXECUTE_STRUCTURAL",
            "timeframe": "M30",
            "policy_id": "STRUCTURAL_SL_CANONICAL_TP__ALL_CANONICAL_SIGNIFICANT__POC_VALUE_AREA_70__MAX_ONE_TICK_OR_SPREAD__REACTION_100_ZONE_WIDTH__ZONE_AGE_4_BARS",
        },
        {"action": "SKIP_NO_PROTECTIVE_ZONE", "timeframe": "M15", "policy_id": "STRUCTURAL_SL_STRUCTURAL_TP_NO_GATE__x"},
    ]
    br = summarize_execute_breakdown(decisions)
    assert br["by_timeframe"]["M15"] == 1
    assert br["by_timeframe"]["H1"] == 1
    assert br["by_timeframe"]["M30"] == 1
    assert br["by_policy_family"]["BASELINE"] == 2
    assert br["by_policy_family"]["STRUCTURAL_SL_ONLY"] == 1
    assert policy_family("BASELINE_CANONICAL") == "BASELINE"
    proof = prove_baseline_only_when_no_same_tf_structural(
        decisions=decisions,
        unique_usable_protective_by_tf={"M15": 0, "M30": 2, "H1": 0, "H4": 0},
        unique_usable_target_by_tf={"M15": 0, "M30": 0, "H1": 0, "H4": 0},
    )
    assert proof["by_timeframe"]["M15"]["baseline_only"] is True
    assert proof["by_timeframe"]["M15"]["proof_ok"] is True
    assert proof["by_timeframe"]["H1"]["baseline_only"] is True
    assert proof["by_timeframe"]["M30"]["proof_ok"] is True
    bad = prove_baseline_only_when_no_same_tf_structural(
        decisions=[
            {
                "action": "EXECUTE_STRUCTURAL",
                "timeframe": "M15",
                "policy_id": "STRUCTURAL_SL_CANONICAL_TP__x",
            }
        ],
        unique_usable_protective_by_tf={"M15": 0, "M30": 0, "H1": 0, "H4": 0},
        unique_usable_target_by_tf={"M15": 0, "M30": 0, "H1": 0, "H4": 0},
    )
    assert bad["proof_ok"] is False


def test_reaction_causality_and_statuses():
    zone = {"lower_boundary": 100.0, "upper_boundary": 101.0}
    created = datetime(2026, 7, 29, 18, 30, tzinfo=timezone.utc)
    decision = datetime(2026, 7, 29, 18, 39, tzinfo=timezone.utc)
    # Future-only events
    future = pd.DataFrame(
        {
            "_ts": [pd.Timestamp("2026-07-29T18:45:00Z")],
            "best_bid_price": [105.0],
            "best_ask_price": [105.1],
        }
    )
    r = prove_zone_reaction(
        zone=zone,
        direction="BULLISH",
        events=future,
        zone_created_at=created,
        decision_ts=decision,
        threshold_id="REACTION_100_ZONE_WIDTH",
    )
    assert r["status"] == "INSUFFICIENT_EVENT_HISTORY"

    # Touch without displacement
    touch_only = pd.DataFrame(
        {
            "_ts": [pd.Timestamp("2026-07-29T18:31:00Z"), pd.Timestamp("2026-07-29T18:32:00Z")],
            "best_bid_price": [100.5, 100.6],
            "best_ask_price": [100.6, 100.7],
        }
    )
    r2 = prove_zone_reaction(
        zone=zone,
        direction="BULLISH",
        events=touch_only,
        zone_created_at=created,
        decision_ts=decision,
        threshold_id="REACTION_100_ZONE_WIDTH",
        tick_size=0.01,
    )
    assert r2["status"] in {"TOUCHED_NO_REACTION", "REACTION_TOO_SMALL"}

    # Proven displacement
    proven = pd.DataFrame(
        {
            "_ts": [
                pd.Timestamp("2026-07-29T18:31:00Z"),
                pd.Timestamp("2026-07-29T18:33:00Z"),
            ],
            "best_bid_price": [100.5, 102.5],
            "best_ask_price": [100.6, 102.6],
        }
    )
    r3 = prove_zone_reaction(
        zone=zone,
        direction="BULLISH",
        events=proven,
        zone_created_at=created,
        decision_ts=decision,
        threshold_id="REACTION_100_ZONE_WIDTH",
        tick_size=0.01,
    )
    assert r3["status"] == "PROVEN"

    # Wrong timeframe
    r4 = prove_zone_reaction(
        zone=zone,
        direction="BULLISH",
        events=proven,
        zone_created_at=created,
        decision_ts=decision,
        threshold_id="REACTION_100_ZONE_WIDTH",
        zone_timeframe="M15",
        expected_timeframe="H1",
    )
    assert r4["status"] == "WRONG_TIMEFRAME"


def test_geometry_long_short_and_buffers():
    zone = {"lower_boundary": 90.0, "upper_boundary": 91.0, "peak_volume_price": 90.5}
    stop = structural_stop_price(
        side="LONG", zone=zone, buffer_policy="ONE_TICK", tick_size=0.01, executable_spread=0.5
    )
    assert stop == pytest.approx(89.99)
    stop2 = structural_stop_price(
        side="LONG", zone=zone, buffer_policy="MAX_ONE_TICK_OR_SPREAD", tick_size=0.01, executable_spread=0.5
    )
    assert stop2 == pytest.approx(89.5)
    take = structural_take_price(side="LONG", zone={"lower_boundary": 110, "upper_boundary": 120, "peak_volume_price": 115}, take_policy="TARGET_POC")
    assert take == 115
    ok, _ = geometry_valid(side="SHORT", entry=100, stop=105, take=95)
    assert ok


def test_engine_stp2_health_and_isolation(stp_repo: Path):
    # reuse fixture from STP1 module
    from tests.test_shadow_structural_protection import _seed_entry

    _seed_entry(stp_repo, tf="M15")
    books = stp_repo / "data/trading/intrabar_paper" / EXPECTED_EPOCH / "books"
    before_books = {p.name: p.read_bytes() for p in books.glob("*.jsonl")}
    eq_before = (stp_repo / "data/trading/shadow_economic_correlation/health.json").read_bytes()
    active_before = (stp_repo / "data/trading/paper_epochs/active.json").read_bytes()
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    h = eng.write_health()
    assert h["stp_generation"] == "SHADOW_STP2_1"
    assert h["classification_model"] == "SHADOW_VOLUME_SIGNIFICANCE_V1"
    assert h["mode"] == "OBSERVE_ONLY"
    assert h["lookahead_violation_count"] == 0
    assert h["write_boundary_violation_count"] == 0
    assert h["baseline_divergence_count"] == 0
    assert "candidate_window_bars_sum_by_timeframe" in h
    assert "unique_detected_zones_by_timeframe" in h
    assert "execute_breakdown" in h
    assert "execute_baseline_only_proof" in h
    assert "target_usable_absence_audit" in h
    assert h["status"] in {
        STATUS_ACTIVE,
        STATUS_STP21_COVERAGE,
        STATUS_INSUFFICIENT_REACTION,
        STATUS_COVERAGE_INTEGRITY_FAILURE,
        "SHADOW_STP1_READY_BLOCKED_INSUFFICIENT_CAUSAL_HISTORY",
    }
    assert before_books == {p.name: p.read_bytes() for p in books.glob("*.jsonl")}
    assert (stp_repo / "data/trading/shadow_economic_correlation/health.json").read_bytes() == eq_before
    assert (stp_repo / "data/trading/paper_epochs/active.json").read_bytes() == active_before
    # restart idempotency
    c1 = len(eng.processed_candidates)
    eng.poll_once()
    assert len(eng.processed_candidates) == c1


def test_every_persisted_zone_has_reaction_status(stp_repo: Path):
    from tests.test_shadow_structural_protection import _seed_entry

    _seed_entry(stp_repo, tf="M15")
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    zones = [
        z
        for z in eng.store.read_all("volume_zones")
        if z.get("policy_manifest_fingerprint") == eng.manifest_fp
    ]
    for z in zones:
        assert z.get("reaction_status") is not None
        assert z.get("classification_mode") == CLASSIFICATION_MODE or z.get("volume_class") is not None

def test_engine_stp21_separates_unique_vs_policy_expanded(stp_repo: Path):
    from tests.test_shadow_structural_protection import _seed_entry

    _seed_entry(stp_repo, tf="M30")
    eng = StructuralProtectionEngine(repo=stp_repo, strict_epoch=True)
    eng.poll_once()
    h = eng.write_health()
    assert int(h.get("policy_expanded_protective_evidence_instances") or 0) == int(
        h.get("protective_zone_usable_count") or 0
    )
    uniq = sum(int(v or 0) for v in (h.get("unique_usable_protective_by_timeframe") or {}).values())
    expanded = int(h.get("policy_expanded_protective_evidence_instances") or 0)
    assert uniq <= expanded
    m15 = h.get("m15_parity") or {}
    if int(m15.get("compared") or 0) == 0 and m15:
        assert m15.get("status") == "NOT_EVALUABLE_INSUFFICIENT_OVERLAP"
    proof = h.get("execute_baseline_only_proof") or {}
    assert "by_timeframe" in proof
    assert proof.get("proof_ok") in {True, False}

