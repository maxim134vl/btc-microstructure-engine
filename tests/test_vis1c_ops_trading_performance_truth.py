#!/usr/bin/env python3
"""VIS1C — OPS Trading Operations performance truth wiring tests."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import ops_dashboard_runtime_truth as truth  # noqa: E402
from btc_ml.trading.trading_performance_truth import (  # noqa: E402
    EXCLUDED_SOURCE_CATEGORIES,
    build_trading_performance_truth,
)


def _walk_numbers(obj: Any):
    if isinstance(obj, float):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_numbers(v)


def test_ops_imports_canonical_adapter_not_old_calculator():
    src = (ROOT / "ops_dashboard_runtime_truth.py").read_text(encoding="utf-8")
    assert "trading_performance_truth" in src
    assert "_build_canonical_trading_performance_truth" in src
    assert "Intentionally do NOT sum trades.parquet" in src
    # Old parallel realised sum path must be gone.
    assert "realized_total +=" not in src
    assert "unrealized_total +=" not in src
    assert 'trades["net_pnl_usd"]' not in src


def test_portfolio_parity_same_mark_payload():
    canon = build_trading_performance_truth()
    plane = truth.build_timeframe_traders(performance_payload=canon, load_performance=False)
    projected = truth.project_trading_performance_for_ops(canon)
    cp = canon["portfolio"]
    port = plane["portfolio"]
    assert port["realized_pnl"] == pytest.approx(float(cp["realised_net_pnl_usd"]))
    assert port["unrealized_pnl"] == pytest.approx(float(cp["unrealised_gross_pnl_usd"]))
    assert port["total_fees_usd"] == pytest.approx(float(cp["total_fees_usd"]))
    assert port["total_slippage_usd"] == pytest.approx(float(cp["total_slippage_usd"]))
    assert port["closed_equity_usd"] == pytest.approx(float(cp["closed_equity_usd"]))
    assert port["mark_to_market_equity_usd"] == pytest.approx(float(cp["mark_to_market_equity_usd"]))
    assert port["closed_trade_count"] == cp["closed_trade_count"]
    assert port["performance_open_position_count"] == cp["open_position_count"]
    assert projected["realized_pnl"] == port["realized_pnl"]
    assert projected["source"]["adapter"] == truth.PERFORMANCE_ADAPTER_PATH
    assert projected["source"]["mark_timestamp"] == cp["mark_timestamp"]
    assert projected["source"]["mtm_basis"] == cp["mtm_basis"]


def test_per_tf_parity_m15_m30_h1_h4():
    canon = build_trading_performance_truth()
    plane = truth.build_timeframe_traders(performance_payload=canon, load_performance=False)
    by_tf = {t["timeframe"]: t for t in plane["traders"]}
    for tf in ("M15", "M30", "H1", "H4"):
        c = canon["timeframes"][tf]
        row = by_tf[tf]
        assert row["closed_trades"] == c["closed_trade_count"]
        assert row["realized_pnl_usd"] == pytest.approx(float(c["realised_net_pnl_usd"] or 0.0))
        if c["unrealised_gross_pnl_usd"] is None:
            assert row["unrealized_pnl_usd"] is None
        else:
            assert row["unrealized_pnl_usd"] == pytest.approx(float(c["unrealised_gross_pnl_usd"]))
        assert row["total_fees_usd"] == c["total_fees_usd"]
        assert row["total_slippage_usd"] == c["total_slippage_usd"]


def test_source_exclusion_policy_preserved():
    canon = build_trading_performance_truth()
    projected = truth.project_trading_performance_for_ops(canon)
    excluded = set(projected["source"]["excluded_sources"])
    for cat in EXCLUDED_SOURCE_CATEGORIES:
        assert cat in excluded
    dq = projected["data_quality"]
    assert dq["excluded_research_count"] == 11
    assert dq["excluded_legacy_count"] == 4
    assert dq["canonical_closed_trade_count"] == canon["portfolio"]["closed_trade_count"]
    # Contamination: totals must equal canonical closed, not 6+4+11.
    assert projected["portfolio"]["closed_trade_count"] == canon["portfolio"]["closed_trade_count"]
    assert projected["portfolio"]["closed_trade_count"] != (
        int(dq["canonical_closed_trade_count"]) + 4 + 11
    )


def test_status_semantics_preliminary_and_insufficient():
    canon = build_trading_performance_truth()
    projected = truth.project_trading_performance_for_ops(canon)
    n = int(projected["portfolio"]["closed_trade_count"] or 0)
    assert n < 30
    assert projected["descriptive_metrics"]["status"] == "PRELIMINARY"
    assert projected["sample_quality"]["sample_status"] == "PRELIMINARY"
    sharpe = projected["risk_adjusted_metrics"]["sharpe"]
    assert isinstance(sharpe, dict)
    # Equity-curve path: finite event-time Sharpe marked PRELIMINARY, not nulled.
    if (projected.get("data_quality") or {}).get("return_observation_count", 0) >= 2:
        assert sharpe["value"] is not None
        assert sharpe["status"] == "PRELIMINARY"
        assert "EVENT_TIME_EQUITY_RETURNS" in str(sharpe.get("reason") or "")
    else:
        assert sharpe["value"] is None
        assert sharpe["status"] in {"INSUFFICIENT_SAMPLE", "UNDEFINED_ZERO_VARIANCE"}
    calmar = projected["risk_adjusted_metrics"]["calmar"]
    assert isinstance(calmar, dict)
    assert calmar["status"] in {"UNSTABLE_SHORT_HISTORY", "INSUFFICIENT_HISTORY", "UNDEFINED_ZERO_DRAWDOWN"}
    annualised = projected["risk_adjusted_metrics"].get("annualised_return")
    if isinstance(annualised, dict):
        assert annualised["status"] in {"UNSTABLE_SHORT_HISTORY", "INSUFFICIENT_HISTORY", "UNDEFINED"}
    assert projected["descriptive_metrics"]["profit_factor"]["status"] == "PRELIMINARY"
    assert projected["descriptive_metrics"]["expectancy"]["status"] == "PRELIMINARY"


def test_section_isolation_performance_failure_preserves_others(monkeypatch):
    def _boom(**_kwargs):
        raise RuntimeError("VIS1C_ISOLATION_PROBE")

    monkeypatch.setattr(truth, "_build_canonical_trading_performance_truth", _boom)
    snap = truth.build_runtime_truth_snapshot()
    assert "trading_performance" in (snap.get("section_errors") or {})
    assert "VIS1C_ISOLATION_PROBE" in snap["section_errors"]["trading_performance"]
    assert snap.get("processes"), "process truth must remain"
    assert (snap.get("timeframe_traders") or {}).get("traders"), "traders must remain"
    assert snap.get("context_chain") is not None
    port = (snap.get("timeframe_traders") or {}).get("portfolio") or {}
    assert port.get("risk_status") in {
        "AVAILABLE",
        "ZERO_CONFIRMED",
        "SOURCE_UNAVAILABLE",
        "SOURCE_STALE",
    }
    assert port.get("realized_pnl") is None
    assert port.get("unrealized_pnl") is None
    perf = (snap.get("trading_operations") or {}).get("performance") or {}
    assert perf.get("status") == "UNKNOWN"
    # Risk group still present separately.
    assert "risk" in (snap.get("trading_operations") or {})
    assert (snap.get("trading_operations") or {})["risk"].get("risk_status") == port.get("risk_status")


def test_serialization_no_nan_inf_null_reason_preserved():
    canon = build_trading_performance_truth()
    projected = truth.project_trading_performance_for_ops(canon)
    snap = {
        "trading_operations": truth.build_trading_operations_block(
            timeframe_traders=truth.build_timeframe_traders(
                performance_payload=canon, load_performance=False
            ),
            performance=projected,
        )
    }
    raw = json.dumps(snap, allow_nan=False)
    assert "NaN" not in raw
    assert "Infinity" not in raw
    for num in _walk_numbers(projected):
        assert not math.isnan(num)
        assert not math.isinf(num)
    sharpe = projected["risk_adjusted_metrics"]["sharpe"]
    assert sharpe["reason"]
    if sharpe["value"] is None:
        assert sharpe["status"] in {
            "INSUFFICIENT_SAMPLE",
            "UNDEFINED_ZERO_VARIANCE",
        }
    else:
        assert math.isfinite(float(sharpe["value"]))


def test_regression_risk_process_pipeline_unchanged_by_performance():
    snap = truth.build_runtime_truth_snapshot()
    assert snap.get("schema_version") == "ops_dashboard_runtime_truth_v1"
    assert snap.get("processes")
    assert snap.get("pipeline_metadata") is not None
    port = (snap.get("timeframe_traders") or {}).get("portfolio") or {}
    # Risk truth still from manager (VIS0), not replaced by performance.
    assert port.get("risk_semantics") == "reserved_open_risk"
    assert "reserved_open_risk_usd" in port
    assert "realized_pnl" in port
    assert snap["trading_operations"]["performance"]["source"]["adapter"].endswith(
        "trading_performance_truth.py"
    )


def test_episode_743_multi_tf_entities_not_deduped():
    canon = build_trading_performance_truth()
    rows = [
        r
        for r in list(canon.get("closed_trades") or []) + list(canon.get("open_positions") or [])
        if "743" in str(r.get("episode_id") or "")
    ]
    if not rows:
        pytest.skip("episode 743 not present in current active paper epoch")
    tfs = {r["timeframe"] for r in rows}
    assert {"M15", "M30", "H1"}.issubset(tfs)
    # Distinct TF entities — not collapsed by episode id.
    keys = {(r["timeframe"], r.get("trade_id") or r.get("position_id")) for r in rows}
    assert len(keys) == len(rows)
    projected = truth.project_trading_performance_for_ops(canon)
    for tf in ("M15", "M30", "H1"):
        assert tf in projected["timeframes"]
        assert int(projected["timeframes"][tf]["closed_trade_count"] or 0) >= 1 or int(
            projected["timeframes"][tf]["open_position_count"] or 0
        ) >= 1


def test_frontend_compatible_aliases_present():
    snap = truth.build_runtime_truth_snapshot()
    port = snap["timeframe_traders"]["portfolio"]
    assert "realized_pnl" in port
    assert "unrealized_pnl" in port
    for row in snap["timeframe_traders"]["traders"]:
        assert "realized_pnl_usd" in row
        assert "unrealized_pnl_usd" in row
        assert "open_position_count" in row
    # New block optional for UI; must not break shape.
    assert "performance" in snap["trading_operations"]
    assert "risk" in snap["trading_operations"]
