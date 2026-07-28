"""LIVE1B OPS adapter: prefer active INTRABAR_RULES_V1 epoch books over voided legacy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def load_active_paper_epoch(repo_root: Path | None = None) -> dict[str, Any] | None:
    root = repo_root or Path(__file__).resolve().parents[4]
    path = root / "data" / "trading" / "paper_epochs" / "active.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("epoch_status") or "").upper() != "ACTIVE":
        return None
    return payload


def legacy_void_marker(repo_root: Path | None = None) -> dict[str, Any] | None:
    root = repo_root or Path(__file__).resolve().parents[4]
    path = root / "data" / "trading" / "timeframe_traders" / "LEGACY_EPOCH_VOID.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def load_intrabar_epoch_books(
    *,
    paper_epoch_id: str,
    repo_root: Path | None = None,
) -> dict[str, dict[str, pd.DataFrame]]:
    """Load LIVE1B JSONL books shaped like TF parquet tables for truth adapter."""
    root = repo_root or Path(__file__).resolve().parents[4]
    books_dir = root / "data" / "trading" / "intrabar_paper" / paper_epoch_id / "books"
    trades = _read_jsonl(books_dir / "trades.jsonl")
    positions = _read_jsonl(books_dir / "positions.jsonl")
    fills = _read_jsonl(books_dir / "fills.jsonl")
    orders = _read_jsonl(books_dir / "orders.jsonl")
    signals = _read_jsonl(books_dir / "signals.jsonl")

    # Latest position status per id
    latest_pos: dict[str, dict[str, Any]] = {}
    for p in positions:
        pid = str(p.get("position_id") or "")
        if pid:
            latest_pos[pid] = p
    positions = list(latest_pos.values())

    out: dict[str, dict[str, pd.DataFrame]] = {}
    for tf in ("M15", "M30", "H1", "H4"):
        out[tf] = {
            "trades": pd.DataFrame([r for r in trades if str(r.get("timeframe")) == tf]),
            "positions": pd.DataFrame([r for r in positions if str(r.get("timeframe")) == tf]),
            "fills": pd.DataFrame([r for r in fills if str(r.get("timeframe")) == tf]),
            "orders": pd.DataFrame([r for r in orders if str(r.get("timeframe")) == tf]),
            "signals": pd.DataFrame([r for r in signals if str(r.get("timeframe")) == tf]),
        }
    return out


def build_intrabar_epoch_performance_summary(
    *,
    epoch: dict[str, Any],
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Minimal headline metrics for active intrabar epoch (legacy excluded)."""
    root = repo_root or Path(__file__).resolve().parents[4]
    eid = str(epoch["paper_epoch_id"])
    books_dir = root / "data" / "trading" / "intrabar_paper" / eid / "books"
    trades = _read_jsonl(books_dir / "trades.jsonl")
    positions_raw = _read_jsonl(books_dir / "positions.jsonl")
    latest: dict[str, dict[str, Any]] = {}
    for p in positions_raw:
        pid = str(p.get("position_id") or "")
        if pid:
            latest[pid] = p
    opens = [p for p in latest.values() if str(p.get("status") or "").upper() == "OPEN"]
    realized = sum(float(t.get("net_pnl_usd") or 0.0) for t in trades)
    initial = float(epoch.get("initial_equity_usd") or 100000.0)
    equity = initial + realized
    wins = sum(1 for t in trades if float(t.get("net_pnl_usd") or 0.0) > 0)
    losses = sum(1 for t in trades if float(t.get("net_pnl_usd") or 0.0) < 0)
    gross_win = sum(float(t.get("net_pnl_usd") or 0.0) for t in trades if float(t.get("net_pnl_usd") or 0.0) > 0)
    gross_loss = abs(
        sum(float(t.get("net_pnl_usd") or 0.0) for t in trades if float(t.get("net_pnl_usd") or 0.0) < 0)
    )
    return {
        "schema_version": "intrabar_paper_epoch_performance_v1",
        "paper_epoch_id": eid,
        "rule_contract_version": epoch.get("rule_contract_version"),
        "mode": "paper_only",
        "real_execution_enabled": False,
        "legacy_excluded": True,
        "legacy_void_status": "VOID_PRE_INTRABAR_RULE_CONTRACT",
        "initial_equity_usd": initial,
        "equity_usd": equity,
        "realized_pnl_usd": realized,
        "unrealized_pnl_usd": 0.0,
        "active_positions": len(opens),
        "positions_by_timeframe": {
            str(p.get("timeframe")): {"side": p.get("side"), "quantity": p.get("quantity")}
            for p in opens
        },
        "trades_count": len(trades),
        "win_rate": (wins / len(trades)) if trades else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "daily_return": None,
        "annualized_return": None,
        "drawdown": None,
        "sharpe": None,
        "calmar": None,
        "source_books": str(books_dir),
    }
