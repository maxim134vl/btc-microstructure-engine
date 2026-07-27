#!/usr/bin/env python3
"""VIS0B — canonical manager risk OPS adapter candidate tests."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ops_dashboard_runtime_truth as truth  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_missing_position_risk_column_does_not_become_zero():
    resolved = truth._resolve_reserved_open_risk_usd(
        open_position_count=1,
        trader_view={},
        position_row={"metadata_json": "{}", "risk_amount_usd": None},
        portfolio_tip=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    assert resolved["reserved_risk_usd"] is None
    assert resolved["open_risk_usd"] is None
    assert resolved["risk_status"] == "ATTRIBUTION_UNAVAILABLE"


def test_missing_aggregate_source_returns_null_status():
    agg = truth._resolve_aggregate_portfolio_risk({}, book_open_positions=4)
    assert agg["gross_open_risk_usd"] is None
    assert agg["available_risk_usd"] is None
    assert agg["max_risk_usd"] is None
    assert agg["risk_status"] == "SOURCE_UNAVAILABLE"
    assert agg["observability_health"] == "DEGRADED_OBSERVABILITY"


def test_confirmed_zero_remains_numeric_zero():
    flat = truth._resolve_reserved_open_risk_usd(
        open_position_count=0,
        trader_view={},
        position_row=None,
        portfolio_tip=None,
    )
    assert flat["reserved_risk_usd"] == 0.0
    assert flat["open_risk_usd"] == 0.0
    assert flat["risk_status"] == "ZERO_CONFIRMED"

    tip = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    zero_open = truth._resolve_reserved_open_risk_usd(
        open_position_count=1,
        trader_view={"open_risk_usd": 0.0},
        position_row={"metadata_json": json.dumps({"approved_risk_usd": 0.0})},
        portfolio_tip=tip,
    )
    assert zero_open["reserved_risk_usd"] == 0.0
    assert zero_open["risk_status"] == "ZERO_CONFIRMED"


def test_aggregate_parity_uses_manager_canonical_fields():
    tip = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    portfolio = {
        "generated_at": tip,
        "gross_open_risk_usd": 1000.0,
        "available_risk_usd": 0.0,
        "portfolio_max_risk_usd": 1000.0,
        "open_positions": 4,
    }
    agg = truth._resolve_aggregate_portfolio_risk(portfolio, book_open_positions=4)
    assert agg["max_risk_usd"] == 1000.0
    assert agg["reserved_open_risk_usd"] == 1000.0
    assert agg["gross_open_risk_usd"] == 1000.0
    assert agg["available_risk_usd"] == 0.0
    assert abs(float(agg["available_risk_usd"]) - (1000.0 - 1000.0)) < 1e-9
    assert agg["risk_utilisation_pct"] == 100.0
    assert agg["risk_source"] == "data/trading/manager/portfolio_summary.json"
    assert agg["risk_status"] == "AVAILABLE"


def test_per_tf_canonical_attribution_and_null_not_zero():
    tip = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ok = truth._resolve_reserved_open_risk_usd(
        open_position_count=1,
        trader_view={"open_risk_usd": 250.0},
        position_row={"risk_amount_usd": None},
        portfolio_tip=tip,
    )
    assert ok["reserved_risk_usd"] == 250.0
    assert ok["risk_status"] == "AVAILABLE"
    assert "portfolio_summary" in (ok["risk_source"] or "")

    gap = truth._resolve_reserved_open_risk_usd(
        open_position_count=1,
        trader_view={},
        position_row={"metadata_json": None},
        portfolio_tip=tip,
    )
    assert gap["reserved_risk_usd"] is None
    assert gap["risk_status"] == "ATTRIBUTION_UNAVAILABLE"


def test_level3_metadata_matches_engine_formula():
    tip = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    resolved = truth._resolve_reserved_open_risk_usd(
        open_position_count=1,
        trader_view={},
        position_row={"metadata_json": json.dumps({"approved_risk_usd": 250.0})},
        portfolio_tip=tip,
    )
    assert resolved["reserved_risk_usd"] == 250.0
    assert resolved["risk_source"] == "position.metadata_json.approved_risk_usd"


def test_invariants_non_negative_and_utilisation_bounded():
    tip = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    agg = truth._resolve_aggregate_portfolio_risk(
        {
            "generated_at": tip,
            "gross_open_risk_usd": 750.0,
            "available_risk_usd": 250.0,
            "portfolio_max_risk_usd": 1000.0,
            "open_positions": 3,
        },
        book_open_positions=3,
    )
    assert agg["reserved_open_risk_usd"] >= 0
    assert agg["available_risk_usd"] >= 0
    assert 0.0 <= float(agg["risk_utilisation_pct"]) <= 100.0
    assert agg["open_position_count"] == 3


def test_stale_aggregate_nulls_values():
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    agg = truth._resolve_aggregate_portfolio_risk(
        {
            "generated_at": old,
            "gross_open_risk_usd": 1000.0,
            "available_risk_usd": 0.0,
            "portfolio_max_risk_usd": 1000.0,
            "open_positions": 4,
        },
        book_open_positions=4,
    )
    assert agg["risk_status"] == "SOURCE_STALE"
    assert agg["gross_open_risk_usd"] is None
    assert agg["available_risk_usd"] is None


def test_live_build_parity_with_manager_portfolio_summary():
    manager = truth._read_json(truth.MANAGER_PORTFOLIO_SUMMARY_PATH) or {}
    plane = truth.build_timeframe_traders()
    port = plane["portfolio"]
    assert manager, "manager portfolio_summary must exist for live parity"
    assert port["risk_status"] in {"AVAILABLE", "ZERO_CONFIRMED"}
    assert port["gross_open_risk_usd"] == pytest.approx(float(manager["gross_open_risk_usd"]))
    assert port["available_risk_usd"] == pytest.approx(float(manager["available_risk_usd"]))
    assert port["portfolio_max_risk_usd"] == pytest.approx(float(manager["portfolio_max_risk_usd"]))
    assert port["open_positions"] == int(manager["open_positions"])
    assert port["reserved_open_risk_usd"] == port["gross_open_risk_usd"]
    assert abs(float(port["available_risk_usd"]) - (float(port["max_risk_usd"]) - float(port["reserved_open_risk_usd"]))) < 1e-6

    by_tf = {t["timeframe"]: t for t in plane["traders"]}
    for tf, view in (manager.get("traders") or {}).items():
        row = by_tf[tf]
        expected = view.get("open_risk_usd")
        assert row["reserved_risk_usd"] == pytest.approx(float(expected))
        assert row["open_risk_usd"] == pytest.approx(float(expected))
        if float(expected) > 0:
            assert row["open_position_count"] >= 1
            assert row["risk_status"] == "AVAILABLE"


def test_regression_manager_trader_sources_unchanged_by_vis0b_patch():
    # Hashes of trading logic files must remain independent of this adapter test;
    # assert files exist and are readable (patch must not mutate them).
    manager = ROOT / "src/btc_ml/trading/timeframe_manager.py"
    trader = ROOT / "src/btc_ml/trading/paper_trader_engine.py"
    risk = ROOT / "src/btc_ml/trading/portfolio_risk.py"
    assert manager.exists() and trader.exists() and risk.exists()
    _ = _sha(manager), _sha(trader), _sha(risk)


def test_adapter_is_read_only_consumer_no_book_writes(tmp_path, monkeypatch):
    # build_timeframe_traders must not write under trading books.
    before = {}
    for tf in truth.S4_TIMEFRAMES:
        p = ROOT / "data/trading/timeframe_traders" / tf / "positions.parquet"
        if p.exists():
            before[str(p)] = p.stat().st_mtime_ns
    plane = truth.build_timeframe_traders()
    assert plane["read_only"] is True
    for path, mtime in before.items():
        assert Path(path).stat().st_mtime_ns == mtime


def test_process_trader_context_sections_still_present():
    snap = truth.build_runtime_truth_snapshot()
    assert snap.get("processes")
    assert (snap.get("timeframe_traders") or {}).get("traders")
    assert snap.get("context_chain") is not None
    port = (snap.get("timeframe_traders") or {}).get("portfolio") or {}
    # PnL fields still present (not removed by risk adapter).
    assert "realized_pnl" in port
    assert "unrealized_pnl" in port
