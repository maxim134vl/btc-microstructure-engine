"""Independent per-TF sleeve risk: CatBoost multiplies, TFs do not share $1000."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402


def test_live_bug_h1_must_open_when_m15_and_m30_occupy_981():
    risk = PortfolioRiskCoordinator.load()
    decision = risk.evaluate(
        timeframe="H1",
        requested_risk_usd=risk.trader_budget("H1"),
        open_risk_by_timeframe={"M15": 594.27, "M30": 387.14},
        open_positions_by_timeframe={"M15": 1, "M30": 1, "H1": 0, "H4": 0},
    )
    assert decision.approved is True
    assert decision.reason is None
    assert decision.approved_risk_usd == 1000.0


def test_m15_not_blocked_by_h1_open_risk():
    risk = PortfolioRiskCoordinator.load()
    decision = risk.evaluate(
        timeframe="M15",
        requested_risk_usd=risk.trader_budget("M15"),
        open_risk_by_timeframe={"H1": 1319.38, "M15": 0.0},
        open_positions_by_timeframe={"H1": 1, "M15": 0},
    )
    assert decision.approved is True
    assert decision.reason is None
    assert decision.approved_risk_usd == 500.0
    assert decision.reason != "PORTFOLIO_RISK_LIMIT"


def test_sleeve_percents_match_host_hybrid():
    risk = PortfolioRiskCoordinator.load()
    pct = risk.config.get("risk_pct_per_trade") or {}
    assert float(pct["M15"]) == 0.5
    assert float(pct["M30"]) == 0.5
    assert float(pct["H1"]) == 1.0
    assert float(pct["H4"]) == 1.0
    assert risk.per_trader_max_risk_usd["M15"] == 500.0
    assert risk.per_trader_max_risk_usd["M30"] == 500.0
    assert risk.per_trader_max_risk_usd["H1"] == 1000.0
    assert risk.per_trader_max_risk_usd["H4"] == 1000.0
