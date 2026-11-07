"""Read-only LIVE1B epoch open-position views for the S4.1 manager.

Used by hybrid mode: manager emits commands; LIVE1B owns books/capital/PnL.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except OSError:
        return []
    return rows


def _sf(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def active_live1b_epoch_id(repo_root: Path | None = None) -> str | None:
    root = repo_root or ROOT
    active = _read_json(root / "data/trading/paper_epochs/active.json")
    if str(active.get("epoch_status") or "").upper() != "ACTIVE":
        return None
    epoch_id = active.get("paper_epoch_id")
    return str(epoch_id) if epoch_id else None


def _latest_open_by_timeframe(positions_path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(positions_path):
        pid = str(row.get("position_id") or "").strip()
        if not pid:
            continue
        latest[pid] = row
    opens: dict[str, dict[str, Any]] = {}
    for row in latest.values():
        if str(row.get("status") or "").upper() != "OPEN":
            continue
        tf = str(row.get("timeframe") or "").upper()
        if tf:
            opens[tf] = row
    return opens


def live1b_trader_views(
    *,
    timeframes: tuple[str, ...] | list[str],
    mark_price: float | None = None,
    repo_root: Path | None = None,
    paper_epoch_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Snapshot shape compatible with ``PaperTraderEngine.snapshot``."""
    root = repo_root or ROOT
    epoch_id = paper_epoch_id or active_live1b_epoch_id(root)
    views: dict[str, dict[str, Any]] = {}
    opens: dict[str, dict[str, Any]] = {}
    trades_by_tf: dict[str, list[dict[str, Any]]] = {tf: [] for tf in timeframes}
    if epoch_id:
        books = root / "data/trading/intrabar_paper" / epoch_id / "books"
        opens = _latest_open_by_timeframe(books / "positions.jsonl")
        for row in _read_jsonl(books / "trades.jsonl"):
            tf = str(row.get("timeframe") or "").upper()
            if tf in trades_by_tf:
                trades_by_tf[tf].append(row)

    for tf in timeframes:
        open_row = opens.get(tf)
        trades = trades_by_tf.get(tf) or []
        realized = 0.0
        fees = 0.0
        slippage = 0.0
        for trade in trades:
            net = _sf(trade.get("realized_net_pnl_usd"))
            if net is None:
                net = _sf(trade.get("realized_pnl_usd"))
            if net is None:
                net = _sf(trade.get("net_pnl_usd"))
            if net is not None:
                realized += net
            fee = _sf(trade.get("fees_usd"))
            if fee is not None:
                fees += fee
            slip = _sf(trade.get("slippage_usd"))
            if slip is not None:
                slippage += slip

        open_risk = 0.0
        unrealized = 0.0
        open_position = None
        if open_row:
            open_risk = float(
                _sf(open_row.get("risk_amount_usd"))
                or _sf(open_row.get("risk_budget_usd"))
                or 0.0
            )
            qty = float(_sf(open_row.get("quantity")) or 0.0)
            entry = float(_sf(open_row.get("entry_price")) or 0.0)
            direction = str(open_row.get("side") or open_row.get("direction") or "").upper()
            if mark_price is not None and qty and entry:
                unrealized = (
                    (float(mark_price) - entry) * qty
                    if direction == "LONG"
                    else (entry - float(mark_price)) * qty
                )
            open_position = {
                "position_id": open_row.get("position_id"),
                "direction": direction,
                "quantity": _sf(open_row.get("quantity")),
                "entry_price": _sf(open_row.get("entry_price")),
                "opened_at": open_row.get("opened_at") or open_row.get("execution_timestamp"),
                "status": "OPEN",
                "stop_loss_price": _sf(open_row.get("stop_loss_price")),
                "take_profit_price": _sf(open_row.get("take_profit_price")),
                "entry_fee_usd": _sf(open_row.get("entry_fee_usd")),
                "risk_amount_usd": open_risk,
            }
        views[tf] = {
            "timeframe": tf,
            "open_position": open_position,
            "open_risk_usd": open_risk,
            "realized_pnl_usd": realized,
            "unrealized_pnl_usd": unrealized,
            "fees_paid_usd": fees,
            "slippage_paid_usd": slippage,
            "closed_trades": len(trades),
            "last_command_id": open_row.get("entry_command_id") if open_row else None,
            "last_result": "POSITION_OPEN" if open_position else "FLAT",
            "last_reason": "LIVE1B_EPOCH_BOOK",
            "cursor_evaluation_timestamp": None,
            "position_source": "live1b_epoch_books",
        }
    return views
