"""Portfolio risk coordinator (S4.1).

Gross risk only: an M15 LONG and an H1 SHORT both consume budget. Opposite
directions are never netted, and unused budget is never reallocated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RISK_CONFIG_PATH = ROOT / "config" / "timeframe_trader_risk.json"

REASON_PORTFOLIO_LIMIT = "PORTFOLIO_RISK_LIMIT"
REASON_TRADER_LIMIT = "TRADER_RISK_LIMIT"
REASON_INVALID_STOP = "INVALID_STOP_DISTANCE"
REASON_POSITION_LIMIT = "TRADER_POSITION_LIMIT"


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    requested_risk_usd: float
    approved_risk_usd: float
    portfolio_open_risk_usd: float
    trader_open_risk_usd: float
    available_portfolio_risk_usd: float
    available_trader_risk_usd: float
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "requested_risk_usd": self.requested_risk_usd,
            "approved_risk_usd": self.approved_risk_usd,
            "portfolio_open_risk_usd": self.portfolio_open_risk_usd,
            "trader_open_risk_usd": self.trader_open_risk_usd,
            "available_portfolio_risk_usd": self.available_portfolio_risk_usd,
            "available_trader_risk_usd": self.available_trader_risk_usd,
            "reason": self.reason,
            "risk_aggregation": "GROSS_NO_NETTING",
        }


class PortfolioRiskCoordinator:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.portfolio_max_risk_usd = float(config.get("portfolio_max_risk_usd") or 0.0)
        self.weights: dict[str, float] = {
            str(k).upper(): float(v) for k, v in (config.get("weights") or {}).items()
        }
        explicit = config.get("per_trader_max_risk_usd") or {}
        self.per_trader_max_risk_usd: dict[str, float] = {
            tf: float(explicit.get(tf, self.portfolio_max_risk_usd * weight))
            for tf, weight in self.weights.items()
        }
        self.max_open_positions_per_trader = int(config.get("max_open_positions_per_trader") or 1)
        self.auto_reallocation = bool(config.get("auto_reallocation_of_unused_risk"))

    @classmethod
    def load(cls, path: Path | None = None) -> "PortfolioRiskCoordinator":
        target = path or RISK_CONFIG_PATH
        payload = json.loads(target.read_text(encoding="utf-8"))
        return cls(payload)

    def trader_budget(self, timeframe: str) -> float:
        return float(self.per_trader_max_risk_usd.get(str(timeframe).upper(), 0.0))

    def gross_open_risk(self, open_risk_by_timeframe: dict[str, float]) -> float:
        return float(sum(abs(float(v or 0.0)) for v in open_risk_by_timeframe.values()))

    def evaluate(
        self,
        *,
        timeframe: str,
        requested_risk_usd: float | None = None,
        open_risk_by_timeframe: dict[str, float] | None = None,
        open_positions_by_timeframe: dict[str, int] | None = None,
        stop_valid: bool = True,
    ) -> RiskDecision:
        tf = str(timeframe).upper()
        budget = self.trader_budget(tf)
        requested = float(requested_risk_usd if requested_risk_usd is not None else budget)
        open_risk = {str(k).upper(): abs(float(v or 0.0)) for k, v in (open_risk_by_timeframe or {}).items()}
        trader_open = open_risk.get(tf, 0.0)
        portfolio_open = self.gross_open_risk(open_risk)
        available_trader = max(0.0, budget - trader_open)
        available_portfolio = max(0.0, self.portfolio_max_risk_usd - portfolio_open)

        def deny(reason: str) -> RiskDecision:
            return RiskDecision(
                False,
                requested,
                0.0,
                portfolio_open,
                trader_open,
                available_portfolio,
                available_trader,
                reason,
            )

        if not stop_valid:
            return deny(REASON_INVALID_STOP)
        positions = int((open_positions_by_timeframe or {}).get(tf, 0))
        if positions >= self.max_open_positions_per_trader:
            return deny(REASON_POSITION_LIMIT)
        if requested <= 0:
            return deny(REASON_TRADER_LIMIT)
        if requested > budget or available_trader <= 0:
            return deny(REASON_TRADER_LIMIT)
        if requested > available_portfolio:
            return deny(REASON_PORTFOLIO_LIMIT)

        approved = min(requested, available_trader, available_portfolio)
        if approved <= 0:
            return deny(REASON_PORTFOLIO_LIMIT)
        return RiskDecision(
            True,
            requested,
            float(approved),
            portfolio_open,
            trader_open,
            available_portfolio,
            available_trader,
            None,
        )
