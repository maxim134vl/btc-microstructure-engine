"""Read-only LIVE1B epoch open-position views for the S4.1 manager.

Used by hybrid mode: manager emits commands; LIVE1B owns books/capital/PnL.
"""

from __future__ import annotations

import json
import fcntl
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


class Live1BBooksUnavailable(RuntimeError):
    """No committed, mutually consistent execution snapshot is available."""



def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, 1):
                if not raw.strip():
                    continue
                item = json.loads(raw)
                if not isinstance(item, dict):
                    raise ValueError(f"NON_OBJECT_BOOK_ROW:{line_number}")
                rows.append(item)
    except (OSError, UnicodeError, ValueError) as exc:
        raise Live1BBooksUnavailable(f"LIVE1B_BOOKS_INPUT_UNAVAILABLE:{path.name}") from exc
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
            if tf in opens:
                raise Live1BBooksUnavailable("LIVE1B_BOOKS_DUPLICATE_OPEN_TIMEFRAME")
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
    active_epoch = active_live1b_epoch_id(root)
    epoch_id = paper_epoch_id or active_epoch
    if not active_epoch or epoch_id != active_epoch:
        raise Live1BBooksUnavailable("LIVE1B_ACTIVE_EPOCH_UNAVAILABLE_OR_CONFLICTING")
    views: dict[str, dict[str, Any]] = {}
    opens: dict[str, dict[str, Any]] = {}
    trades_by_tf: dict[str, list[dict[str, Any]]] = {tf: [] for tf in timeframes}
    sleeves_snapshot: dict[str, Any] = {}
    if epoch_id:
        books = root / "data/trading/intrabar_paper" / epoch_id / "books"
        pending = books.parent / "execution_commits_v1" / "pending.json"
        try:
            lock = (books / ".writer.lock").open("rb")
        except OSError as exc:
            raise Live1BBooksUnavailable("LIVE1B_BOOKS_LOCK_UNAVAILABLE") from exc
        with lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Live1BBooksUnavailable("LIVE1B_BOOKS_COMMIT_IN_PROGRESS") from exc
            try:
                if pending.exists():
                    raise Live1BBooksUnavailable("LIVE1B_BOOKS_UNCOMMITTED_INTENT")
                try:
                    from .intrabar_paper.execution_commit import verify_committed_head
                    committed_head = verify_committed_head(books.parent, epoch_id)
                except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                    raise Live1BBooksUnavailable("LIVE1B_" + str(exc)) from exc
                try:
                    sleeve_document = json.loads((books.parent / "sleeves.json").read_text())
                    if sleeve_document.get("epoch_id") != epoch_id:
                        raise ValueError("SLEEVE_EPOCH_MISMATCH")
                    sleeves_snapshot = sleeve_document["sleeves"]
                    for tf in timeframes:
                        row = sleeves_snapshot[tf]
                        if str(row["timeframe"]).upper() != tf:
                            raise ValueError("SLEEVE_TIMEFRAME_MISMATCH")
                        equity = float(row["current_equity_usd"])
                        pct = float(row["risk_pct_per_trade"])
                        if not math.isfinite(equity) or not math.isfinite(pct) or equity < 0 or pct <= 0:
                            raise ValueError("INVALID_SLEEVE_CAPITAL")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise Live1BBooksUnavailable("LIVE1B_SLEEVE_CONTRACT_UNAVAILABLE") from exc
                if active_live1b_epoch_id(root) != epoch_id:
                    raise Live1BBooksUnavailable("LIVE1B_ACTIVE_EPOCH_CHANGED")
                for row in _read_jsonl(books / "positions.jsonl"):
                    if row.get("paper_epoch_id") not in (None, epoch_id):
                        raise Live1BBooksUnavailable("LIVE1B_POSITION_EPOCH_CONFLICT")
                opens = _latest_open_by_timeframe(books / "positions.jsonl")
                for row in _read_jsonl(books / "trades.jsonl"):
                    if row.get("paper_epoch_id") not in (None, epoch_id):
                        raise Live1BBooksUnavailable("LIVE1B_TRADE_EPOCH_CONFLICT")
                    tf = str(row.get("timeframe") or "").upper()
                    if tf in trades_by_tf:
                        trades_by_tf[tf].append(row)
                # The committed ledger and append-only books describe the same
                # publication. Never turn lost exposure/history into a FLAT view.
                try:
                    for tf in timeframes:
                        sleeve = sleeves_snapshot[tf]
                        position = opens.get(tf)
                        if sleeve["open_position_id"] != (position or {}).get("position_id"):
                            raise ValueError("POSITION_ID_DISAGREES_WITH_SLEEVE")
                        book_risk = float((position or {}).get("risk_amount_usd") or (position or {}).get("risk_budget_usd") or 0.0)
                        ledger_risk = float(sleeve["open_position_risk_usd"])
                        if not math.isfinite(book_risk) or not math.isfinite(ledger_risk) or book_risk != ledger_risk:
                            raise ValueError("OPEN_RISK_DISAGREES_WITH_SLEEVE")
                        if int(sleeve["closed_trades_count"]) != len(trades_by_tf[tf]):
                            raise ValueError("CLOSED_COUNT_DISAGREES_WITH_SLEEVE")
                except (KeyError, TypeError, ValueError) as exc:
                    raise Live1BBooksUnavailable("LIVE1B_BOOKS_SLEEVE_MISMATCH") from exc
                if pending.exists():
                    raise Live1BBooksUnavailable("LIVE1B_BOOKS_UNCOMMITTED_INTENT")
                if active_live1b_epoch_id(root) != epoch_id:
                    raise Live1BBooksUnavailable("LIVE1B_ACTIVE_EPOCH_CHANGED")
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    from .intrabar_paper.execution_commit import open_authority
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
            "execution_authority": open_authority(committed_head, tf, sleeves_snapshot[tf]),
            "paper_epoch_id": epoch_id,
            "sleeve_current_equity_usd": (sleeves_snapshot.get(tf) or {}).get("current_equity_usd"),
            "sleeve_risk_pct_per_trade": (sleeves_snapshot.get(tf) or {}).get("risk_pct_per_trade"),
        }
    return views
