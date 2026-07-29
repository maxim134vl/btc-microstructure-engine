"""Net R / economic gate helpers using canonical fee-slippage contract."""

from __future__ import annotations

from typing import Any

from btc_ml.trading.intrabar_paper.config import IntrabarPaperConfig
from btc_ml.trading.intrabar_paper.economics import bps_to_rate, closed_trade_economics

from .policies import net_r_threshold


def expected_net_r(
    *,
    cfg: IntrabarPaperConfig,
    side: str,
    entry: float,
    stop: float,
    take: float,
    quantity: float,
    risk_budget_usd: float,
) -> dict[str, Any]:
    stop_econ = closed_trade_economics(
        cfg=cfg,
        side=side,
        entry_price=entry,
        exit_price=stop,
        quantity=quantity,
        risk_amount_usd=risk_budget_usd,
        exit_reason="STOP_LOSS",
    )
    take_econ = closed_trade_economics(
        cfg=cfg,
        side=side,
        entry_price=entry,
        exit_price=take,
        quantity=quantity,
        risk_amount_usd=risk_budget_usd,
        exit_reason="TAKE_PROFIT",
    )
    risk = float(risk_budget_usd) if risk_budget_usd else 0.0
    net_loss = float(stop_econ["net_pnl_usd"])
    net_profit = float(take_econ["net_pnl_usd"])
    # For LONG stop path net_loss is negative; net_R uses |risk budget| as denom
    net_r = (net_profit / risk) if risk else None
    gross_r = None
    if risk:
        gross_profit = float(take_econ["gross_pnl_usd"])
        gross_r = gross_profit / risk
    return {
        "gross_loss_at_stop": float(stop_econ["gross_pnl_usd"]),
        "net_loss_at_stop": net_loss,
        "gross_profit_at_take": float(take_econ["gross_pnl_usd"]),
        "net_profit_at_take": net_profit,
        "gross_R": gross_r,
        "net_R": net_r,
        "entry_fee_rate": bps_to_rate(cfg.entry_fee_bps),
        "exit_fee_rate": bps_to_rate(cfg.exit_fee_bps),
    }


def economic_gate_decision(*, gate: str, net_r: float | None) -> tuple[str, str | None]:
    thr = net_r_threshold(gate)
    if thr is None:
        return "EXECUTE_STRUCTURAL", None
    if net_r is None or net_r < thr:
        return "SKIP_NON_ECONOMIC_AFTER_COSTS", f"net_R<{thr}"
    return "EXECUTE_STRUCTURAL", None
