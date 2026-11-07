"""Closed-trade economic quality outcomes (post-exit only)."""

from __future__ import annotations

from typing import Any

from . import FIELD_NOT_AVAILABLE
from .features import parse_ts


def build_quality_outcome(
    *,
    candidate: dict[str, Any],
    trade: dict[str, Any],
    overlap_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    risk = float(trade.get("risk_amount_usd") or candidate.get("risk_budget_usd") or 0.0)
    net = float(trade.get("net_pnl_usd") or 0.0)
    gross = float(trade.get("gross_pnl_usd") or 0.0)
    entry_ts = parse_ts(trade.get("entry_ts") or candidate.get("entry_timestamp"))
    exit_ts = parse_ts(trade.get("exit_ts"))
    holding = FIELD_NOT_AVAILABLE
    if entry_ts and exit_ts:
        holding = max(0.0, (exit_ts - entry_ts).total_seconds())

    # Without intrabar path, MFE/MAE are not canonically available.
    mfe = FIELD_NOT_AVAILABLE
    mae = FIELD_NOT_AVAILABLE
    mfe_r = FIELD_NOT_AVAILABLE
    mae_r = FIELD_NOT_AVAILABLE

    overlap = overlap_stats or {}
    return {
        "candidate_id": candidate.get("candidate_id"),
        "paper_epoch_id": candidate.get("paper_epoch_id"),
        "timeframe": candidate.get("timeframe"),
        "side": candidate.get("side"),
        "trade_id": trade.get("trade_id"),
        "position_id": trade.get("position_id"),
        "gross_pnl_usd": gross,
        "fees_usd": float(trade.get("fees_usd") or 0.0),
        "slippage_usd": float(trade.get("slippage_usd") or 0.0),
        "net_pnl_usd": net,
        "net_R": (net / risk) if risk else FIELD_NOT_AVAILABLE,
        "MFE_usd": mfe,
        "MFE_R": mfe_r,
        "MAE_usd": mae,
        "MAE_R": mae_r,
        "holding_seconds": holding,
        "exit_reason": trade.get("exit_reason"),
        "exit_timestamp": trade.get("exit_ts"),
        "exit_price": trade.get("exit_price"),
        "overlap_seconds_with_same_direction_positions": overlap.get(
            "overlap_seconds_with_same_direction_positions", FIELD_NOT_AVAILABLE
        ),
        "maximum_same_direction_positions_during_trade": overlap.get(
            "maximum_same_direction_positions_during_trade", FIELD_NOT_AVAILABLE
        ),
        "maximum_same_direction_risk_during_trade": overlap.get(
            "maximum_same_direction_risk_during_trade", FIELD_NOT_AVAILABLE
        ),
        "simultaneous_loss_count": overlap.get("simultaneous_loss_count", FIELD_NOT_AVAILABLE),
        "simultaneous_stop_count": overlap.get("simultaneous_stop_count", FIELD_NOT_AVAILABLE),
        "quality_status": "DATA_COLLECTION",
        "path_source": "EXIT_ONLY_NO_INTRABAR_PATH",
    }


def scale_net_pnl(*, canonical_net: float, canonical_qty: float, virtual_qty: float) -> float:
    if not canonical_qty:
        return 0.0
    return float(canonical_net) * (float(virtual_qty) / float(canonical_qty))
