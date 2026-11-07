#!/usr/bin/env python3
"""Canonical paper-trade economics math.

Pure infrastructure helper: no ledger writes, no runtime calls, no exchange APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

INITIAL_CAPITAL_USD = 100000.0
MAX_RISK_PER_TRADE_PCT = 1.0
MAX_RISK_PER_TRADE_FRACTION = MAX_RISK_PER_TRADE_PCT / 100.0
MAX_RISK_USD = INITIAL_CAPITAL_USD * MAX_RISK_PER_TRADE_FRACTION

STOP_LOSS_BPS = 100.0
TAKE_PROFIT_BPS = 150.0

ENTRY_FEE_BPS = 2.0
EXIT_FEE_BPS = 5.0
NORMAL_ENTRY_SLIPPAGE_BPS = 3.0
NORMAL_EXIT_SLIPPAGE_BPS = 3.0
STOP_FORCED_EXIT_SLIPPAGE_BPS = 5.0
CANDLE_CLOSE_FALLBACK_MIN_SLIPPAGE_BPS = 5.0

SIZING_METHOD = "risk_based_stop_loss_cost_aware"
POSITION_SIZING_MODE = "Risk-based, 1% max loss per trade"
ECONOMICS_SOURCE = "canonical_paper_trade_economics_v1"
EXECUTION_QUALITY_OK = "OK"
EXECUTION_QUALITY_DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class RiskSizing:
    allowed: bool
    reason: str | None
    side: str
    entry_price: float | None
    stop_loss_price: float | None
    take_profit_price: float | None
    stop_distance: float | None
    risk_amount_usd: float
    position_size_btc: float | None
    position_notional_usd: float | None
    effective_loss_per_unit_at_stop: float | None
    estimated_loss_at_stop_usd: float | None
    entry_fee_usd: float | None
    estimated_exit_fee_usd_at_stop: float | None
    entry_slippage_usd: float | None
    estimated_exit_slippage_usd_at_stop: float | None
    entry_fee_bps: float
    exit_fee_bps: float
    entry_slippage_bps: float
    exit_slippage_bps: float

    def to_controller_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "sizing_method": SIZING_METHOD,
            "position_sizing_mode": POSITION_SIZING_MODE,
            "initial_equity": INITIAL_CAPITAL_USD,
            "initial_capital_usd": INITIAL_CAPITAL_USD,
            "max_risk_pct": MAX_RISK_PER_TRADE_FRACTION,
            "max_risk_per_trade_pct": MAX_RISK_PER_TRADE_PCT,
            "max_risk_usd": self.risk_amount_usd,
            "risk_amount_usd": self.risk_amount_usd,
            "quantity_btc": self.position_size_btc,
            "notional_usd": self.position_notional_usd,
            "position_size_btc": self.position_size_btc,
            "position_notional_usd": self.position_notional_usd,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "stop_loss_source": "provided" if self.stop_loss_price is not None else None,
            "take_profit_source": "provided" if self.take_profit_price is not None else None,
            "stop_distance": self.stop_distance,
            "stop_distance_usd": self.stop_distance,
            "effective_loss_per_unit_at_stop": self.effective_loss_per_unit_at_stop,
            "estimated_loss_at_stop": self.estimated_loss_at_stop_usd,
            "estimated_loss_at_stop_usd": self.estimated_loss_at_stop_usd,
            "entry_fee_usd": self.entry_fee_usd,
            "estimated_exit_fee_usd_at_stop": self.estimated_exit_fee_usd_at_stop,
            "entry_slippage_usd": self.entry_slippage_usd,
            "estimated_exit_slippage_usd_at_stop": self.estimated_exit_slippage_usd_at_stop,
            "estimated_slippage_usd_at_stop": None
            if self.entry_slippage_usd is None or self.estimated_exit_slippage_usd_at_stop is None
            else self.entry_slippage_usd + self.estimated_exit_slippage_usd_at_stop,
            "fee_model_used": (
                f"entry_fee_bps={self.entry_fee_bps};"
                f"exit_fee_bps={self.exit_fee_bps};"
                f"entry_slippage_bps={self.entry_slippage_bps};"
                f"exit_slippage_bps={self.exit_slippage_bps}"
            ),
            "entry_fee_bps": self.entry_fee_bps,
            "exit_fee_bps": self.exit_fee_bps,
            "entry_slippage_bps": self.entry_slippage_bps,
            "exit_slippage_bps": self.exit_slippage_bps,
            "slippage_bps": self.entry_slippage_bps + self.exit_slippage_bps,
            "fixed_notional_used": False,
            "economics_source": ECONOMICS_SOURCE,
        }


def bps_to_rate(bps: float) -> float:
    return float(bps) / 10000.0


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        out = float(value)
    except Exception:
        return None
    if out != out or out in {float("inf"), float("-inf")}:
        return None
    return out


def stop_take_prices(side: str, entry_price: float) -> tuple[float, float]:
    entry = float(entry_price)
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return entry * (1.0 - bps_to_rate(STOP_LOSS_BPS)), entry * (1.0 + bps_to_rate(TAKE_PROFIT_BPS))
    if side_u == "SHORT":
        return entry * (1.0 + bps_to_rate(STOP_LOSS_BPS)), entry * (1.0 - bps_to_rate(TAKE_PROFIT_BPS))
    raise ValueError(f"unsupported_side:{side}")


def stop_distance(side: str, entry_price: float, stop_loss_price: float) -> float:
    if str(side or "").upper() == "LONG":
        return float(entry_price) - float(stop_loss_price)
    if str(side or "").upper() == "SHORT":
        return float(stop_loss_price) - float(entry_price)
    return -1.0


def exit_slippage_bps_for_execution(
    *,
    exit_reason: Any = None,
    execution_source: Any = None,
    fallback_slippage_bps: Any = None,
) -> float:
    source = str(execution_source or "").strip().lower()
    reason = str(exit_reason or "").strip().upper()
    fallback = safe_float(fallback_slippage_bps)
    if "candle_close_fallback" in source:
        return max(CANDLE_CLOSE_FALLBACK_MIN_SLIPPAGE_BPS, fallback or 0.0)
    if any(token in reason for token in ("STOP", "FORCED", "FORCE", "FALLBACK")):
        return STOP_FORCED_EXIT_SLIPPAGE_BPS
    return NORMAL_EXIT_SLIPPAGE_BPS


def execution_quality_status(*, execution_source: Any = None, exit_reason: Any = None) -> str:
    source = str(execution_source or "").strip().lower()
    reason = str(exit_reason or "").strip().upper()
    if "candle_close_fallback" in source or "FALLBACK" in reason:
        return EXECUTION_QUALITY_DEGRADED
    return EXECUTION_QUALITY_OK


def resolve_risk_sizing(
    *,
    side: str,
    entry_price: Any,
    stop_loss_price: Any,
    take_profit_price: Any = None,
    block_missing_stop_reason: str = "ENTRY_BLOCKED_NO_VALID_STOP_FOR_RISK_SIZING",
    block_invalid_stop_reason: str = "ENTRY_BLOCKED_INVALID_STOP_DISTANCE",
) -> RiskSizing:
    side_u = str(side or "").upper()
    entry = safe_float(entry_price)
    stop = safe_float(stop_loss_price)
    take = safe_float(take_profit_price)
    risk_amount = MAX_RISK_USD
    if entry is None or entry <= 0 or stop is None or stop <= 0:
        return RiskSizing(False, block_missing_stop_reason, side_u, entry, stop, take, None, risk_amount, None, None, None, None, None, None, None, None, ENTRY_FEE_BPS, EXIT_FEE_BPS, NORMAL_ENTRY_SLIPPAGE_BPS, STOP_FORCED_EXIT_SLIPPAGE_BPS)
    distance = stop_distance(side_u, entry, stop)
    if distance <= 0:
        return RiskSizing(False, block_invalid_stop_reason, side_u, entry, stop, take, distance, risk_amount, None, None, None, None, None, None, None, None, ENTRY_FEE_BPS, EXIT_FEE_BPS, NORMAL_ENTRY_SLIPPAGE_BPS, STOP_FORCED_EXIT_SLIPPAGE_BPS)
    per_btc = (
        distance
        + entry * bps_to_rate(ENTRY_FEE_BPS)
        + stop * bps_to_rate(EXIT_FEE_BPS)
        + entry * bps_to_rate(NORMAL_ENTRY_SLIPPAGE_BPS)
        + stop * bps_to_rate(STOP_FORCED_EXIT_SLIPPAGE_BPS)
    )
    if per_btc <= 0:
        return RiskSizing(False, block_invalid_stop_reason, side_u, entry, stop, take, distance, risk_amount, None, None, per_btc, None, None, None, None, None, ENTRY_FEE_BPS, EXIT_FEE_BPS, NORMAL_ENTRY_SLIPPAGE_BPS, STOP_FORCED_EXIT_SLIPPAGE_BPS)
    qty = risk_amount / per_btc
    entry_notional = qty * entry
    stop_notional = qty * stop
    entry_fee = entry_notional * bps_to_rate(ENTRY_FEE_BPS)
    stop_exit_fee = stop_notional * bps_to_rate(EXIT_FEE_BPS)
    entry_slippage = entry_notional * bps_to_rate(NORMAL_ENTRY_SLIPPAGE_BPS)
    stop_exit_slippage = stop_notional * bps_to_rate(STOP_FORCED_EXIT_SLIPPAGE_BPS)
    estimated_loss = qty * distance + entry_fee + stop_exit_fee + entry_slippage + stop_exit_slippage
    return RiskSizing(
        True,
        None,
        side_u,
        entry,
        stop,
        take,
        distance,
        risk_amount,
        qty,
        entry_notional,
        per_btc,
        estimated_loss,
        entry_fee,
        stop_exit_fee,
        entry_slippage,
        stop_exit_slippage,
        ENTRY_FEE_BPS,
        EXIT_FEE_BPS,
        NORMAL_ENTRY_SLIPPAGE_BPS,
        STOP_FORCED_EXIT_SLIPPAGE_BPS,
    )


def closed_trade_economics(
    *,
    side: str,
    entry_price: Any,
    exit_price: Any,
    position_size_btc: Any,
    stop_loss_price: Any = None,
    take_profit_price: Any = None,
    risk_amount_usd: Any = None,
    exit_reason: Any = None,
    exit_execution_source: Any = None,
    fallback_slippage_bps: Any = None,
) -> dict[str, Any]:
    side_u = str(side or "").upper()
    entry = float(safe_float(entry_price) or 0.0)
    exit_ = float(safe_float(exit_price) or 0.0)
    qty = abs(float(safe_float(position_size_btc) or 0.0))
    risk_amount = float(safe_float(risk_amount_usd) or MAX_RISK_USD)
    exit_slip_bps = exit_slippage_bps_for_execution(
        exit_reason=exit_reason,
        execution_source=exit_execution_source,
        fallback_slippage_bps=fallback_slippage_bps,
    )
    entry_notional = qty * entry
    exit_notional = qty * exit_
    gross = (entry - exit_) * qty if side_u == "SHORT" else (exit_ - entry) * qty
    entry_fee = entry_notional * bps_to_rate(ENTRY_FEE_BPS)
    exit_fee = exit_notional * bps_to_rate(EXIT_FEE_BPS)
    entry_slip = entry_notional * bps_to_rate(NORMAL_ENTRY_SLIPPAGE_BPS)
    exit_slip = exit_notional * bps_to_rate(exit_slip_bps)
    fees = entry_fee + exit_fee
    slippage = entry_slip + exit_slip
    net = gross - fees - slippage
    slip_r = slippage / risk_amount if risk_amount else 0.0
    r_multiple = net / risk_amount if risk_amount else 0.0
    stop = safe_float(stop_loss_price)
    take = safe_float(take_profit_price)
    return {
        "side": side_u,
        "entry_price": entry,
        "exit_price": exit_,
        "stop_loss_price": stop,
        "take_profit_price": take,
        "position_size_btc": qty,
        "position_notional_usd": entry_notional,
        "risk_amount_usd": risk_amount,
        "stop_distance_usd": None if stop is None else stop_distance(side_u, entry, stop),
        "entry_notional_usd": entry_notional,
        "exit_notional_usd": exit_notional,
        "entry_fee_usd": entry_fee,
        "exit_fee_usd": exit_fee,
        "fees_usd": fees,
        "entry_slippage_usd": entry_slip,
        "exit_slippage_usd": exit_slip,
        "slippage_usd": slippage,
        "entry_fee_bps": ENTRY_FEE_BPS,
        "exit_fee_bps": EXIT_FEE_BPS,
        "entry_slippage_bps": NORMAL_ENTRY_SLIPPAGE_BPS,
        "exit_slippage_bps": exit_slip_bps,
        "slippage_bps": NORMAL_ENTRY_SLIPPAGE_BPS + exit_slip_bps,
        "slippage_R": slip_r,
        "gross_pnl_before_fees_slippage": gross,
        "gross_pnl_usd": gross,
        "net_pnl_after_fees_slippage": net,
        "net_pnl_usd": net,
        "R": r_multiple,
        "r_multiple": r_multiple,
        "execution_quality_status": execution_quality_status(
            execution_source=exit_execution_source,
            exit_reason=exit_reason,
        ),
        "economics_source": ECONOMICS_SOURCE,
    }
