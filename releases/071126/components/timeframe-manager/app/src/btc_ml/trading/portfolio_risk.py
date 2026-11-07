"""S4.1 OPEN-gate risk coordinator.

Hybrid live capital is four independent $100k sleeves (M15 0.5%, M30 0.5%,
H1 1%, H4 1%). CatBoost only multiplies that sleeve budget at LIVE1B fill.
This coordinator must not block one TF because another TF is already open.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RISK_CONFIG_PATH = ROOT / "config" / "timeframe_trader_risk.json"

REASON_PORTFOLIO_LIMIT = "PORTFOLIO_RISK_LIMIT"
REASON_TRADER_LIMIT = "TRADER_RISK_LIMIT"
REASON_INVALID_STOP = "INVALID_STOP_DISTANCE"
REASON_POSITION_LIMIT = "TRADER_POSITION_LIMIT"
INDEPENDENT_AGGREGATION = frozenset({"PER_TIMEFRAME_INDEPENDENT", "PER_TF_SLEEVE"})


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
    risk_aggregation: str = "PER_TIMEFRAME_INDEPENDENT"

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
            "risk_aggregation": self.risk_aggregation,
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
        self.risk_aggregation = str(config.get("risk_aggregation") or "GROSS_NO_NETTING").upper()
        self.independent_timeframes = self.risk_aggregation in INDEPENDENT_AGGREGATION

    @classmethod
    def load(cls, path: Path | None = None) -> "PortfolioRiskCoordinator":
        target = path or RISK_CONFIG_PATH
        payload = json.loads(target.read_text(encoding="utf-8"))
        return cls(payload)

    def with_live1b_sleeves(self, views: dict[str, dict[str, Any]]) -> "PortfolioRiskCoordinator":
        """Read the execution authority's committed per-TF realized equity.

        Only the budget source changes; percentages, independent admission and
        occupancy rules are the original September sleeve contract.
        """
        from .live1b_position_views import Live1BBooksUnavailable
        import math
        if not self.independent_timeframes:
            raise Live1BBooksUnavailable("LIVE1B_INDEPENDENT_RISK_CONFIG_REQUIRED")
        percentages = self.config.get("risk_pct_per_trade") or {}
        budgets: dict[str, float] = {}
        equity_snapshots = {}
        epochs = {}
        for tf in self.weights:
            try:
                view = views[tf]
                if view.get("position_source") != "live1b_epoch_books" or not view.get("paper_epoch_id"):
                    raise ValueError("LIVE1B_SLEEVE_SOURCE_REQUIRED")
                equity = float(view["sleeve_current_equity_usd"])
                pct = float(view["sleeve_risk_pct_per_trade"])
                if pct != float(percentages[tf]) or not math.isfinite(equity) or equity < 0:
                    raise ValueError("LIVE1B_SLEEVE_RISK_CONTRACT_MISMATCH")
                budgets[tf] = equity * pct / 100.0
                equity_snapshots[tf] = equity
                authority = view["execution_authority"]
                if (authority["timeframe"] != tf or authority["epoch"] != view["paper_epoch_id"]
                        or float(authority["equity"]) != equity
                        or authority["position_id"] != (view.get("open_position") or {}).get("position_id")):
                    raise ValueError("LIVE1B_COMMITTED_AUTHORITY_CONFLICT")
                epochs[tf] = {"epoch": view["paper_epoch_id"], "authority": authority}
            except (KeyError, ValueError, TypeError) as exc:
                raise Live1BBooksUnavailable("LIVE1B_SLEEVE_RISK_CONTRACT_MISMATCH") from exc
        return type(self)({**self.config, "per_trader_max_risk_usd": budgets,
                           "portfolio_max_risk_usd": sum(budgets.values()),
                           "committed_sleeve_equity_snapshot": equity_snapshots,
                           "committed_sleeve_epoch": epochs})
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
                self.risk_aggregation,
            )

        if not stop_valid:
            return deny(REASON_INVALID_STOP)
        positions = int((open_positions_by_timeframe or {}).get(tf, 0))
        if positions >= self.max_open_positions_per_trader:
            return deny(REASON_POSITION_LIMIT)
        # NaN compares false to both <= 0 and > budget and would otherwise
        # produce an approved NaN allocation through min(). No finite sizing
        # or risk formula changes: an unrepresentable request is invalid.
        if not math.isfinite(requested) or requested <= 0:
            return deny(REASON_TRADER_LIMIT)
        if requested > budget or available_trader <= 0:
            return deny(REASON_TRADER_LIMIT)
        if not self.independent_timeframes and requested > available_portfolio:
            return deny(REASON_PORTFOLIO_LIMIT)

        if self.independent_timeframes:
            approved = min(requested, available_trader)
            if approved <= 0:
                return deny(REASON_TRADER_LIMIT)
        else:
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
            self.risk_aggregation,
        )
