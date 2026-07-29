"""Independent virtual sleeves per structural policy."""

from __future__ import annotations

import copy
from typing import Any

from btc_ml.trading.intrabar_paper.config import IntrabarPaperConfig
from btc_ml.trading.intrabar_paper.economics import resolve_risk_sizing

from . import TIMEFRAMES
from .policies import POLICY_IDS
from .timeutil import utc_now


def initial_policy_sleeves(
    *,
    policy_ids: tuple[str, ...] = POLICY_IDS,
    initial_equity_usd: float = 100_000.0,
    risk_pct: float = 1.0,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pid in policy_ids:
        out[pid] = {
            "policy_id": pid,
            "sleeves": {
                tf: {
                    "timeframe": tf,
                    "initial_equity_usd": float(initial_equity_usd),
                    "cumulative_realized_net_pnl_usd": 0.0,
                    "current_equity_usd": float(initial_equity_usd),
                    "risk_pct_per_trade": float(risk_pct),
                    "next_risk_budget_usd": float(initial_equity_usd) * risk_pct / 100.0,
                    "open_position_id": None,
                    "closed_trades_count": 0,
                }
                for tf in TIMEFRAMES
            },
            "updated_at": utc_now(),
        }
    return out


def sleeve_equity(sleeves: dict[str, Any], policy_id: str, timeframe: str) -> float:
    return float(sleeves[policy_id]["sleeves"][timeframe]["current_equity_usd"])


def sleeve_next_risk(sleeves: dict[str, Any], policy_id: str, timeframe: str) -> float:
    s = sleeves[policy_id]["sleeves"][timeframe]
    return float(s["current_equity_usd"]) * float(s["risk_pct_per_trade"]) / 100.0


def size_with_stop(
    *,
    cfg: IntrabarPaperConfig,
    side: str,
    entry_price: float,
    stop_price: float,
    take_price: float,
    equity_usd: float,
    risk_budget_usd: float,
) -> dict[str, Any]:
    sizing = resolve_risk_sizing(
        cfg=cfg,
        side=side,
        entry_price=entry_price,
        equity_usd=equity_usd,
        risk_budget_usd=risk_budget_usd,
        stop_loss_price=stop_price,
        take_profit_price=take_price,
    )
    return {
        "ok": sizing.ok,
        "block_reason": sizing.block_reason,
        "quantity": sizing.quantity,
        "notional_usd": sizing.entry_notional,
        "risk_amount_usd": sizing.risk_amount_usd,
        "stop_distance": sizing.stop_distance,
        "stop_loss_price": sizing.stop_loss_price,
        "take_profit_price": sizing.take_profit_price,
        "per_btc_cost": sizing.per_btc_cost,
        "estimated_loss": sizing.estimated_loss,
    }


def apply_realized(
    sleeves: dict[str, Any],
    *,
    policy_id: str,
    timeframe: str,
    net_pnl_usd: float,
) -> dict[str, Any]:
    s = sleeves[policy_id]["sleeves"][timeframe]
    s["cumulative_realized_net_pnl_usd"] = float(s["cumulative_realized_net_pnl_usd"]) + float(net_pnl_usd)
    s["current_equity_usd"] = float(s["initial_equity_usd"]) + float(s["cumulative_realized_net_pnl_usd"])
    s["closed_trades_count"] = int(s["closed_trades_count"]) + 1
    s["open_position_id"] = None
    s["next_risk_budget_usd"] = float(s["current_equity_usd"]) * float(s["risk_pct_per_trade"]) / 100.0
    sleeves[policy_id]["updated_at"] = utc_now()
    return copy.deepcopy(s)


def mark_open(sleeves: dict[str, Any], *, policy_id: str, timeframe: str, position_id: str) -> None:
    s = sleeves[policy_id]["sleeves"][timeframe]
    s["open_position_id"] = position_id
    s["next_risk_budget_usd"] = sleeve_next_risk(sleeves, policy_id, timeframe)
    sleeves[policy_id]["updated_at"] = utc_now()


def sync_baseline_from_real(sleeves: dict[str, Any], *, real_sleeves: dict[str, Any]) -> None:
    base = sleeves.get("BASELINE_CANONICAL", {}).get("sleeves") or {}
    for tf, row in (real_sleeves or {}).items():
        if tf not in base or not isinstance(row, dict):
            continue
        base[tf]["initial_equity_usd"] = float(row.get("initial_equity_usd") or 100000.0)
        base[tf]["cumulative_realized_net_pnl_usd"] = float(row.get("cumulative_realized_net_pnl_usd") or 0.0)
        base[tf]["current_equity_usd"] = float(row.get("current_equity_usd") or base[tf]["initial_equity_usd"])
        base[tf]["next_risk_budget_usd"] = float(
            row.get("next_risk_budget_usd")
            or base[tf]["current_equity_usd"] * float(base[tf]["risk_pct_per_trade"]) / 100.0
        )
        base[tf]["open_position_id"] = row.get("open_position_id")
        base[tf]["closed_trades_count"] = int(row.get("closed_trades_count") or 0)
