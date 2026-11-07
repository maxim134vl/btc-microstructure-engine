#!/usr/bin/env python3
"""Void leaky H1_1 / H1_2 paper trades and reset canonical-era PnL.

H1_1 (H1:95 LONG) filled on VOID-restart catch-up. H1_2 (H1:97 SHORT) filled
one H1 bar late, then flipped LONG without OBSERVE. Both are excluded from
strategy PnL. Equity curve keeps only CANONICAL_ERA_ORIGIN so OPS drawdown
does not inherit the Sep-7 epoch birth timestamp.
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
    counts_toward_strategy_performance,
    is_void_position_row,
)
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger

CANONICAL_ERA_ORIGIN_TRADE_ID = "CANONICAL_ERA_ORIGIN"

DEFAULT_EPOCH = "PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442"
DEFAULT_TRADE_IDS = (
    "trd_24671ac3bbb84bbe",  # H1_1 LONG H1:95, −$304
    "trd_8b002811aff64ab6",  # H1_2 SHORT H1:97, −$174
)
DEFAULT_OPEN_POSITION_IDS = (
    "pos_b16507e53a8242c2",  # H1 LONG opened after illegal SHORT→LONG flip
)
VOID_CLASS = "LEAKY_H1_PRE_CANONICAL_S41"
VOID_STATUS = "VOID_LEAKY_H1_PRE_CANONICAL_S41"
VOID_DETAIL = (
    "Leaky H1 before forming-bar + OBSERVE contract: H1_1 catch-up fill while "
    "paper-manager was stopped; H1_2 traded the next closed bar and flipped "
    "without OBSERVE. Excluded from strategy PnL."
)
ORIGIN_TS = "2026-09-14T10:04:36.267742Z"
ORIGIN_EQUITY = 400000.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    tmp.replace(path)


def void_leaky_h1(
    *,
    epoch_root: Path,
    trade_ids: tuple[str, ...] = DEFAULT_TRADE_IDS,
    open_position_ids: tuple[str, ...] = DEFAULT_OPEN_POSITION_IDS,
    dry_run: bool = False,
) -> dict[str, Any]:
    epoch_id = epoch_root.name
    books = EpochBooks(epoch_root / "books", paper_epoch_id=epoch_id)
    wanted = {str(tid) for tid in trade_ids}
    wanted_pos = {str(pid) for pid in open_position_ids}
    now = _utc_now()

    trades = books.read_all("trades")
    targets = [row for row in trades if str(row.get("trade_id") or "") in wanted]
    pnl_removed = sum(float(row.get("net_pnl_usd") or 0.0) for row in targets)

    latest = books.latest_positions()
    positions_to_void = []
    for row in latest.values():
        pid = str(row.get("position_id") or "")
        if is_void_position_row(row):
            continue
        if pid in wanted_pos:
            positions_to_void.append(row)
            continue
        if str(row.get("trade_id") or "") in wanted:
            positions_to_void.append(row)
            continue
        # Closed H1_1 / H1_2 positions keyed by the leaky trade ids.
        if any(str(t.get("position_id") or "") == pid for t in targets):
            positions_to_void.append(row)

    summary: dict[str, Any] = {
        "epoch_id": epoch_id,
        "voided_at": now,
        "trade_ids": sorted(wanted),
        "trades_matched": [t.get("trade_id") for t in targets],
        "pnl_removed": round(pnl_removed, 6),
        "positions_to_void": [p.get("position_id") for p in positions_to_void],
        "dry_run": dry_run,
    }
    if dry_run:
        return summary

    with books.exclusive():
        rewritten: list[dict[str, Any]] = []
        for row in trades:
            if str(row.get("trade_id") or "") not in wanted:
                rewritten.append(row)
                continue
            restated = dict(row)
            restated.update(
                {
                    "status": VOID_STATUS,
                    "void_status": VOID_STATUS,
                    "void_class": VOID_CLASS,
                    "invalidated_at": now,
                    "invalidation_reason": INVALIDATION_REASON_SYSTEM_BUG,
                    "invalidation_detail": VOID_DETAIL,
                    "strategy_pnl_included": False,
                    "statistics_included": False,
                    "original_status": str(row.get("status") or "CLOSED"),
                    "original_exit_ts": row.get("exit_ts") or row.get("original_exit_ts"),
                    "exit_ts": None,
                    "paper_epoch_id": epoch_id,
                }
            )
            rewritten.append(restated)
        _rewrite_jsonl(books.root / "trades.jsonl", rewritten)

        for row in targets:
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
                    "original_exit_ts": row.get("exit_ts"),
                    "exit_ts": None,
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
                    "original_exit_ts": row.get("closed_at") or row.get("exit_ts"),
                    "closed_at": None,
                    "exit_ts": None,
                    "paper_epoch_id": epoch_id,
                }
            )
            books.append("positions", void_pos)

        origin_row = {
            "trade_id": CANONICAL_ERA_ORIGIN_TRADE_ID,
            "ts": ORIGIN_TS,
            "equity_usd": ORIGIN_EQUITY,
            "realized_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
            "note": "CANONICAL_ERA_EQUITY_ORIGIN",
            "timeframe": None,
            "paper_epoch_id": epoch_id,
        }
        _rewrite_jsonl(books.root / "equity_snapshots.jsonl", [origin_row])

        books.append(
            "metrics",
            {
                "metric_type": "EPOCH_LEAKY_H1_VOID",
                "void_class": VOID_CLASS,
                "invalidated_at": now,
                "invalidation_reason": INVALIDATION_REASON_SYSTEM_BUG,
                "invalidation_detail": VOID_DETAIL,
                "trades_voided": [t.get("trade_id") for t in targets],
                "positions_voided": [p.get("position_id") for p in positions_to_void],
                "pnl_removed": pnl_removed,
                "strategy_pnl_included": False,
                "statistics_included": False,
            },
        )

        sleeves = SleeveLedger.load(epoch_root)
        if sleeves is not None:
            h1 = sleeves.sleeves.get("H1")
            if h1 is not None:
                h1.cumulative_realized_net_pnl_usd = 0.0
                h1.closed_trades_count = 0
                h1.open_position_id = None
                h1.open_position_risk_usd = 0.0
                h1.last_realized_update_at = now
            sleeves.save()
            master = sleeves.master_snapshot()
            summary["sleeves_reset"] = True
            summary["master_realized_after"] = master["master_realized_net_pnl_usd"]
            summary["master_equity_after"] = master["master_current_equity_usd"]
        else:
            summary["sleeves_reset"] = False

    eligible = books.closed_trades()
    summary["eligible_trades_after"] = [
        {"trade_id": t.get("trade_id"), "timeframe": t.get("timeframe"), "net_pnl_usd": t.get("net_pnl_usd")}
        for t in eligible
        if counts_toward_strategy_performance(t)
    ]
    summary["eligible_pnl_after"] = round(
        sum(float(t.get("net_pnl_usd") or 0.0) for t in eligible), 6
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = void_leaky_h1(epoch_root=args.epoch_root.resolve(), dry_run=args.dry_run)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
