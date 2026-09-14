#!/usr/bin/env python3
"""Void pre-canonical paper trades and reset sleeve PnL (append-only).

Operator migration after cognition→S4.1→execution cutover on 2026-09-14.
All CLOSED trades opened before the cutover are restated VOID and excluded
from strategy PnL / chart overlays. Sleeves reset to initial equity.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_ml.trading.intrabar_paper.books import EpochBooks
from btc_ml.trading.intrabar_paper.performance_eligibility import (
    INVALIDATION_REASON_SYSTEM_BUG,
    POSITION_STATUS_VOID,
    counts_toward_strategy_performance,
    is_void_position_row,
)
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger

DEFAULT_EPOCH = "PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442"
DEFAULT_CUTOVER = "2026-09-14T09:00:00Z"
VOID_CLASS = "PRE_COGNITION_CANONICAL_EXECUTION"
VOID_STATUS = "VOID_PRE_COGNITION_CANONICAL_EXECUTION"
VOID_DETAIL = (
    "Pre-canonical execution: trades before cognition→S4.1→LIVE1B cutover "
    "(OBSERVE-hold + opposite-through-OBSERVE). Excluded from strategy PnL."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _before_cutover(row: dict[str, Any], *, cutover: datetime) -> bool:
    for key in ("entry_ts", "exit_ts", "opened_at", "closed_at"):
        stamp = _ts(row.get(key))
        if stamp is not None:
            return stamp < cutover
    return True


def void_epoch_trades(
    *,
    epoch_root: Path,
    cutover_iso: str = DEFAULT_CUTOVER,
    dry_run: bool = False,
) -> dict[str, Any]:
    epoch_id = epoch_root.name
    books = EpochBooks(epoch_root / "books", paper_epoch_id=epoch_id)
    cutover = _ts(cutover_iso)
    if cutover is None:
        raise ValueError(f"bad cutover: {cutover_iso}")
    if cutover.tzinfo is None:
        cutover = cutover.replace(tzinfo=timezone.utc)

    now = _utc_now()
    trades = books.read_all("trades")
    to_void = [
        row
        for row in trades
        if counts_toward_strategy_performance(row) and _before_cutover(row, cutover=cutover)
    ]

    latest_positions = books.latest_positions()
    positions_to_void = [
        row
        for row in latest_positions.values()
        if not is_void_position_row(row)
        and str(row.get("status") or "").upper() in {"CLOSED", "OPEN", ""}
        and _before_cutover(row, cutover=cutover)
    ]

    pnl_by_tf: dict[str, float] = {"M15": 0.0, "M30": 0.0, "H1": 0.0, "H4": 0.0}
    for row in to_void:
        tf = str(row.get("timeframe") or "").upper()
        if tf in pnl_by_tf:
            pnl_by_tf[tf] += float(row.get("net_pnl_usd") or 0.0)

    summary = {
        "epoch_id": epoch_id,
        "cutover": cutover_iso,
        "voided_at": now,
        "trades_to_void": len(to_void),
        "positions_to_void": len(positions_to_void),
        "pnl_removed_by_tf": {k: round(v, 6) for k, v in pnl_by_tf.items()},
        "pnl_removed_total": round(sum(pnl_by_tf.values()), 6),
        "dry_run": dry_run,
    }
    if dry_run:
        return summary

    with books.exclusive():
        for row in to_void:
            original_id = str(row.get("trade_id") or "").strip()
            void_row = dict(row)
            void_row.update(
                {
                    "trade_id": f"void_{uuid.uuid4().hex[:16]}",
                    "supersedes_trade_id": original_id or None,
                    "status": VOID_STATUS,
                    "void_status": VOID_STATUS,
                    "void_class": VOID_CLASS,
                    "invalidated_at": now,
                    "invalidation_reason": INVALIDATION_REASON_SYSTEM_BUG,
                    "invalidation_detail": VOID_DETAIL,
                    "strategy_pnl_included": False,
                    "statistics_included": False,
                    "original_trade_id": original_id,
                    "original_status": str(row.get("status") or "CLOSED"),
                    "paper_epoch_id": epoch_id,
                }
            )
            books.append("trades", void_row)

        for row in positions_to_void:
            void_pos = dict(row)
            void_pos.update(
                {
                    "status": VOID_STATUS,
                    "void_status": VOID_STATUS,
                    "void_class": VOID_CLASS,
                    "invalidated_at": now,
                    "invalidation_reason": INVALIDATION_REASON_SYSTEM_BUG,
                    "invalidation_detail": VOID_DETAIL,
                    "strategy_pnl_included": False,
                    "statistics_included": False,
                    "original_status": str(row.get("status") or ""),
                    "paper_epoch_id": epoch_id,
                }
            )
            books.append("positions", void_pos)

        books.append(
            "metrics",
            {
                "metric_type": "EPOCH_PRE_CANONICAL_VOID",
                "void_class": VOID_CLASS,
                "invalidated_at": now,
                "invalidation_reason": INVALIDATION_REASON_SYSTEM_BUG,
                "invalidation_detail": VOID_DETAIL,
                "trades_voided": len(to_void),
                "positions_voided": len(positions_to_void),
                "pnl_removed_by_tf": pnl_by_tf,
                "pnl_removed_total": sum(pnl_by_tf.values()),
                "cutover": cutover_iso,
                "strategy_pnl_included": False,
                "statistics_included": False,
            },
        )

        sleeves = SleeveLedger.load(epoch_root)
        if sleeves is not None:
            for tf, sleeve in sleeves.sleeves.items():
                sleeve.cumulative_realized_net_pnl_usd = 0.0
                sleeve.closed_trades_count = 0
                sleeve.open_position_id = None
                sleeve.open_position_risk_usd = 0.0
                sleeve.last_realized_update_at = now
            sleeves.save()
            master = sleeves.master_snapshot()
            summary["sleeves_reset"] = True
            summary["master_realized_after"] = master["master_realized_net_pnl_usd"]
            summary["master_equity_after"] = master["master_current_equity_usd"]
            books.append(
                "equity_snapshots",
                {
                    "snapshot_ts": now,
                    "equity_usd": master["master_current_equity_usd"],
                    "realized_pnl_usd": 0.0,
                    "unrealized_pnl_usd": 0.0,
                    "note": "PRE_CANONICAL_VOID_RESET",
                },
            )
        else:
            summary["sleeves_reset"] = False

    eligible = books.closed_trades()
    summary["eligible_trades_after"] = len(eligible)
    summary["eligible_pnl_after"] = round(
        sum(float(t.get("net_pnl_usd") or 0.0) for t in eligible), 6
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-root", type=Path, required=True)
    parser.add_argument("--cutover", default=DEFAULT_CUTOVER)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = void_epoch_trades(
        epoch_root=args.epoch_root.resolve(),
        cutover_iso=args.cutover,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
