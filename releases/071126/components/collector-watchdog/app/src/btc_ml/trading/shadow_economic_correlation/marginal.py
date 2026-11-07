"""Marginal contribution of a candidate vs portfolio-without-candidate."""

from __future__ import annotations

from typing import Any

from . import FIELD_NOT_AVAILABLE


def marginal_contribution(
    *,
    with_candidate_net_pnl: float,
    without_candidate_net_pnl: float,
    with_candidate_peak_equity: float | None,
    without_candidate_peak_equity: float | None,
    with_candidate_trough_equity: float | None,
    without_candidate_trough_equity: float | None,
    risk_used_usd: float,
    capital_used_usd: float,
    blocked: bool,
    counterfactual_net_pnl: float | None,
) -> dict[str, Any]:
    marginal_pnl = float(with_candidate_net_pnl) - float(without_candidate_net_pnl)

    def _dd(peak: float | None, trough: float | None) -> float | None:
        if peak is None or trough is None:
            return None
        return max(0.0, float(peak) - float(trough))

    dd_with = _dd(with_candidate_peak_equity, with_candidate_trough_equity)
    dd_without = _dd(without_candidate_peak_equity, without_candidate_trough_equity)
    marginal_dd = None if dd_with is None or dd_without is None else float(dd_with) - float(dd_without)

    opportunity = FIELD_NOT_AVAILABLE
    loss_avoided = FIELD_NOT_AVAILABLE
    if blocked and counterfactual_net_pnl is not None:
        if counterfactual_net_pnl > 0:
            opportunity = float(counterfactual_net_pnl)
            loss_avoided = 0.0
        else:
            opportunity = 0.0
            loss_avoided = abs(float(counterfactual_net_pnl))

    return {
        "marginal_net_pnl_usd": marginal_pnl,
        "marginal_drawdown_usd": marginal_dd if marginal_dd is not None else FIELD_NOT_AVAILABLE,
        "marginal_drawdown_pct": FIELD_NOT_AVAILABLE,
        "marginal_volatility": "INSUFFICIENT_SAMPLE",
        "marginal_capital_usage": capital_used_usd,
        "marginal_risk_usage": risk_used_usd,
        "opportunity_cost_if_blocked": opportunity,
        "loss_avoided_if_blocked": loss_avoided,
        "sharpe": "INSUFFICIENT_SAMPLE",
        "calmar": "INSUFFICIENT_SAMPLE",
        "status": "DESCRIPTIVE_ONLY",
    }
