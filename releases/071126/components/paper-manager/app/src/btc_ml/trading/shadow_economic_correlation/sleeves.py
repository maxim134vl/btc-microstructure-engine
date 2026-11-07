"""Independent virtual sleeves per shadow policy."""

from __future__ import annotations

import copy
from typing import Any

from btc_ml.trading.intrabar_paper.config import IntrabarPaperConfig
from btc_ml.trading.intrabar_paper.economics import resolve_risk_sizing

from . import POLICY_IDS, TIMEFRAMES
from .features import utc_now


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
                    "open_position_risk_usd": 0.0,
                    "closed_trades_count": 0,
                    "last_realized_update_at": None,
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


def apply_policy_sizing(
    *,
    cfg: IntrabarPaperConfig,
    candidate: dict[str, Any],
    sleeves: dict[str, Any],
    policy_id: str,
    risk_multiplier: float,
) -> dict[str, Any]:
    tf = str(candidate["timeframe"]).upper()
    side = str(candidate["side"]).upper()
    entry = float(candidate["entry_executable_price"])
    equity = sleeve_equity(sleeves, policy_id, tf)
    standard = sleeve_next_risk(sleeves, policy_id, tf)
    effective = float(standard) * float(risk_multiplier)

    # Full-size baseline / full execute: mirror canonical fill quantity for parity.
    if abs(float(risk_multiplier) - 1.0) < 1e-12 and policy_id == "BASELINE_ALL_ELIGIBLE":
        qty = float(candidate.get("quantity") or 0.0)
        notional = float(candidate.get("notional_usd") or (qty * entry))
        risk_amt = float(candidate.get("risk_amount_usd") or candidate.get("risk_budget_usd") or effective)
        return {
            "equity_at_entry_usd": float(candidate.get("equity_at_entry_usd") or equity),
            "standard_risk_budget_usd": standard,
            "effective_risk_budget_usd": float(candidate.get("risk_budget_usd") or effective),
            "risk_multiplier": risk_multiplier,
            "quantity": qty,
            "notional_usd": notional,
            "stop_price": candidate.get("stop_price"),
            "take_price": candidate.get("take_price"),
            "risk_amount_usd": risk_amt,
            "sizing_ok": qty > 0,
            "block_reason": None if qty > 0 else "BASELINE_MISSING_QUANTITY",
            "sizing_path": "canonical_fill_mirror",
        }

    sizing = resolve_risk_sizing(
        cfg=cfg,
        side=side,
        entry_price=entry,
        equity_usd=equity,
        risk_budget_usd=effective,
    )
    return {
        "equity_at_entry_usd": equity,
        "standard_risk_budget_usd": standard,
        "effective_risk_budget_usd": effective,
        "risk_multiplier": risk_multiplier,
        "quantity": sizing.quantity,
        "notional_usd": sizing.entry_notional,
        "stop_price": sizing.stop_loss_price,
        "take_price": sizing.take_profit_price,
        "risk_amount_usd": sizing.risk_amount_usd,
        "sizing_ok": sizing.ok,
        "block_reason": sizing.block_reason,
        "sizing_path": "resolve_risk_sizing",
    }


def mark_open(
    sleeves: dict[str, Any],
    *,
    policy_id: str,
    timeframe: str,
    position_id: str,
    risk_usd: float,
) -> None:
    s = sleeves[policy_id]["sleeves"][timeframe]
    s["open_position_id"] = position_id
    s["open_position_risk_usd"] = float(risk_usd)
    s["next_risk_budget_usd"] = sleeve_next_risk(sleeves, policy_id, timeframe)
    sleeves[policy_id]["updated_at"] = utc_now()


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
    s["last_realized_update_at"] = utc_now()
    s["open_position_id"] = None
    s["open_position_risk_usd"] = 0.0
    s["next_risk_budget_usd"] = float(s["current_equity_usd"]) * float(s["risk_pct_per_trade"]) / 100.0
    sleeves[policy_id]["updated_at"] = utc_now()
    return copy.deepcopy(s)


def sync_baseline_from_real(
    sleeves: dict[str, Any],
    *,
    real_sleeves: dict[str, Any],
) -> None:
    """Align BASELINE sleeves to live sleeve ledger (read-only source)."""
    base = sleeves["BASELINE_ALL_ELIGIBLE"]["sleeves"]
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
        base[tf]["open_position_risk_usd"] = float(row.get("open_position_risk_usd") or 0.0)
        base[tf]["closed_trades_count"] = int(row.get("closed_trades_count") or 0)
    sleeves["BASELINE_ALL_ELIGIBLE"]["updated_at"] = utc_now()
