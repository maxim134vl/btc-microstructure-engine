"""OPS-RISK-METRICS1 — independent equity-curve risk metric checks."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from btc_ml.trading.trading_performance_truth import (
    build_equity_curve_risk_metrics,
    build_trading_performance_truth,
    load_canonical_equity_snapshots,
)


def _independent_metrics(equities: list[float], hours: list[float]):
    """Reference implementation — must not call production helpers."""
    assert len(equities) == len(hours)
    returns = [equities[i] / equities[i - 1] - 1.0 for i in range(1, len(equities))]
    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    sharpe = mean_r / std
    downside = [min(r, 0.0) for r in returns]
    down_dev = math.sqrt(sum(d * d for d in downside) / len(returns))
    sortino = mean_r / down_dev

    peak = equities[0]
    peak_i = 0
    max_dd = 0.0
    longest = 0.0
    open_i = None
    dd_open = False
    for i, eq in enumerate(equities):
        if eq >= peak:
            if open_i is not None and eq >= peak:
                dur = hours[i] - hours[open_i]
                longest = max(longest, dur)
                open_i = None
            if eq > peak:
                peak = eq
                peak_i = i
        elif eq < peak:
            max_dd = max(max_dd, (peak - eq) / peak)
            if open_i is None:
                open_i = peak_i
    if open_i is not None:
        dur = hours[-1] - hours[open_i]
        longest = max(longest, dur)
        dd_open = equities[-1] < peak

    elapsed_years = (hours[-1] - hours[0]) / (365.25 * 24.0)
    ann = (equities[-1] / equities[0]) ** (1.0 / elapsed_years) - 1.0
    calmar = ann / max_dd
    return {
        "returns": returns,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "dd_hours": longest,
        "dd_open": dd_open,
        "ann": ann,
        "calmar": calmar,
    }


def test_synthetic_equity_curve_metrics_match_independent_math():
    t0 = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    # Explicit small series with an open drawdown at the end.
    series = [
        (t0, 100.0),
        (t0 + timedelta(hours=1), 110.0),  # new peak
        (t0 + timedelta(hours=3), 99.0),  # drawdown start at peak ts=1h
        (t0 + timedelta(hours=7), 95.0),
        (t0 + timedelta(hours=10), 105.0),  # recover to prior peak? peak was 110, still open
        (t0 + timedelta(hours=14), 90.0),
    ]
    # Rebuild as snapshots after initial point (production prepends initial).
    snaps = [
        {"_ts": ts, "ts": ts.isoformat().replace("+00:00", "Z"), "equity_usd": eq, "trade_id": f"t{i}"}
        for i, (ts, eq) in enumerate(series[1:], start=1)
    ]
    out = build_equity_curve_risk_metrics(
        initial_equity_usd=100.0,
        initial_timestamp=t0,
        equity_snapshots=snaps,
        initial_timestamp_inferred=False,
    )
    equities = [e for _, e in series]
    hours = [0.0, 1.0, 3.0, 7.0, 10.0, 14.0]
    ref = _independent_metrics(equities, hours)

    assert out["equity_point_count"] == 6
    assert out["return_observation_count"] == 5
    assert out["return_observation_count"] == len(ref["returns"])
    assert out["sharpe"]["value"] == pytest.approx(ref["sharpe"])
    assert out["sharpe"]["status"] == "PRELIMINARY"
    assert "EVENT_TIME_EQUITY_RETURNS" in out["sharpe"]["reason"]
    assert "NON_ANNUALISED" in out["sharpe"]["reason"]
    assert out["sortino"]["value"] == pytest.approx(ref["sortino"])
    assert out["sortino"]["status"] == "PRELIMINARY"
    assert out["max_drawdown"]["value"] == pytest.approx(ref["max_dd"])
    assert out["max_drawdown"]["status"] == "PRELIMINARY"
    assert out["drawdown_duration"]["value"] == pytest.approx(ref["dd_hours"])
    assert out["drawdown_duration"]["status"] == "PRELIMINARY"
    assert out["drawdown_open"] is True
    assert out["drawdown_open"] == ref["dd_open"]
    assert out["annualised_return"]["value"] == pytest.approx(ref["ann"])
    assert out["annualised_return"]["status"] == "UNSTABLE_SHORT_HISTORY"
    assert "ANNUALISATION_UNSTABLE" in out["annualised_return"]["reason"]
    assert out["calmar"]["value"] == pytest.approx(ref["calmar"])
    assert out["calmar"]["status"] == "UNSTABLE_SHORT_HISTORY"
    assert out["decision_grade"] is False

    def _walk(obj):
        if isinstance(obj, float):
            yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _walk(v)

    for num in _walk(out):
        assert not math.isnan(num)
        assert not math.isinf(num)


def test_zero_variance_and_no_downside_statuses():
    t0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    # Flat equity after initial → zero variance
    snaps = [
        {
            "_ts": t0 + timedelta(hours=i),
            "ts": (t0 + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
            "equity_usd": 100.0,
            "trade_id": f"f{i}",
        }
        for i in range(1, 4)
    ]
    flat = build_equity_curve_risk_metrics(
        initial_equity_usd=100.0, initial_timestamp=t0, equity_snapshots=snaps
    )
    assert flat["sharpe"]["value"] is None
    assert flat["sharpe"]["status"] == "UNDEFINED_ZERO_VARIANCE"
    assert flat["sortino"]["status"] == "UNDEFINED_NO_DOWNSIDE"

    # Strictly rising → no downside
    rising = [
        {
            "_ts": t0 + timedelta(hours=i),
            "ts": (t0 + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
            "equity_usd": 100.0 + 10.0 * i,
            "trade_id": f"r{i}",
        }
        for i in range(1, 4)
    ]
    up = build_equity_curve_risk_metrics(
        initial_equity_usd=100.0, initial_timestamp=t0, equity_snapshots=rising
    )
    assert up["sortino"]["value"] is None
    assert up["sortino"]["status"] == "UNDEFINED_NO_DOWNSIDE"
    assert up["sharpe"]["value"] is not None
    assert up["max_drawdown"]["value"] == pytest.approx(0.0)


def test_live_active_epoch_equity_curve_populated():
    payload = build_trading_performance_truth()
    if payload.get("source") != "LIVE1B_INTRABAR_PAPER_EPOCH":
        pytest.skip("LIVE1B intrabar epoch path not active")
    risk = payload["risk_adjusted_metrics"]
    dq = payload["data_quality"]
    books = Path(payload["source_policy"]["included_sources"][0])
    snaps = load_canonical_equity_snapshots(
        books_dir=books, paper_epoch_id=str(payload["paper_epoch_id"])
    )
    assert dq["equity_point_count"] == len(snaps) + 1  # initial + snapshots
    assert dq["return_observation_count"] == len(snaps)
    assert dq["canonical_closed_trade_count"] == payload["portfolio"]["closed_trade_count"]
    assert risk["sharpe"]["value"] is not None
    assert risk["sharpe"]["status"] == "PRELIMINARY"
    assert risk["sortino"]["value"] is not None
    assert risk["sortino"]["status"] == "PRELIMINARY"
    assert risk["max_drawdown"]["value"] is not None
    assert risk["max_drawdown"]["status"] == "PRELIMINARY"
    assert risk["drawdown_duration"]["value"] is not None
    assert risk["calmar"]["status"] == "UNSTABLE_SHORT_HISTORY"
    assert risk["annualised_return"]["status"] == "UNSTABLE_SHORT_HISTORY"
    assert risk["decision_grade"] is False
    assert "shadow" not in str(payload.get("source_policy")).lower()
