#!/usr/bin/env python3
"""Void non-canonical current-epoch fills (anti-saw and/or strength floor).

Both path-density anti-saw and process_strength are live. Trades that would
not have opened under those gates are restated VOID and excluded from
strategy PnL. Sleeve realized PnL is rebuilt from remaining canonical trades.

Keep set is the per-TF chart ordinal of currently eligible CLOSED trades
(sorted by opened_at / entry_ts), matching the 16.09→17.09 audit:

  M15_3, M15_5, H1_1, H1_2, H4_1, H4_4, H4_6, H4_8
"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_ml.trading.intrabar_paper.books import EpochBooks
from btc_ml.trading.intrabar_paper.performance_eligibility import (
    INVALIDATION_REASON_SYSTEM_BUG,
    counts_toward_strategy_performance,
    filter_superseded_trades,
    is_void_position_row,
)
from btc_ml.trading.intrabar_paper.sleeves import TIMEFRAMES, SleeveLedger

DEFAULT_EPOCH = "PER_TF_EQUITY_1PCT_V1_VPS_20260916_061956"
VOID_CLASS = "SAW_OR_STRENGTH_NON_CANONICAL"
VOID_STATUS = "VOID_SAW_OR_STRENGTH_NON_CANONICAL"
VOID_DETAIL = (
    "Entry would not have opened with path-density anti-saw and process_strength "
    "floor both enabled. Restated VOID and excluded from strategy PnL."
)
KEEP_ORDINALS: dict[str, frozenset[int]] = {
    "M15": frozenset({3, 5}),
    "M30": frozenset(),
    "H1": frozenset({1, 2}),
    "H4": frozenset({1, 4, 6, 8}),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    tmp.replace(path)


def _sort_key(row: dict[str, Any]) -> str:
    return str(row.get("entry_ts") or row.get("opened_at") or row.get("exit_ts") or "")


def _eligible_trades(books: EpochBooks) -> list[dict[str, Any]]:
    rows = filter_superseded_trades(books.read_all("trades"))
    return [row for row in rows if counts_toward_strategy_performance(row)]


def _public_label(tf: str, ordinal: int) -> str:
    return f"{tf}_{ordinal}"


def classify_trades(books: EpochBooks) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    keep: list[dict[str, Any]] = []
    void: list[dict[str, Any]] = []
    by_tf: dict[str, list[dict[str, Any]]] = {tf: [] for tf in TIMEFRAMES}
    for row in _eligible_trades(books):
        tf = str(row.get("timeframe") or "").upper()
        if tf in by_tf:
            by_tf[tf].append(row)
    for tf, rows in by_tf.items():
        rows.sort(key=_sort_key)
        keep_set = KEEP_ORDINALS.get(tf, frozenset())
        for idx, row in enumerate(rows, start=1):
            labeled = dict(row)
            labeled["_public_number"] = _public_label(tf, idx)
            labeled["_ordinal"] = idx
            if idx in keep_set:
                keep.append(labeled)
            else:
                void.append(labeled)
    return keep, void


def backup_epoch(epoch_root: Path, backup_root: Path) -> None:
    backup_root.mkdir(parents=True, exist_ok=True)
    for name in ("books", "sleeves.json", "health.json"):
        src = epoch_root / name
        if not src.exists():
            continue
        dst = backup_root / name
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def _trade_brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "public_number": row.get("_public_number"),
        "trade_id": row.get("trade_id"),
        "position_id": row.get("position_id"),
        "timeframe": row.get("timeframe"),
        "side": row.get("side"),
        "entry_ts": row.get("entry_ts") or row.get("opened_at"),
        "exit_ts": row.get("exit_ts") or row.get("closed_at"),
        "net_pnl_usd": round(float(row.get("net_pnl_usd") or 0.0), 4),
        "exit_reason": row.get("exit_reason"),
    }


def void_noncanonical_trades(
    *,
    epoch_root: Path,
    dry_run: bool = False,
    backup: bool = True,
) -> dict[str, Any]:
    epoch_id = epoch_root.name
    books = EpochBooks(epoch_root / "books", paper_epoch_id=epoch_id)
    now = _utc_now()
    keep, to_void = classify_trades(books)
    void_trade_ids = {str(row.get("trade_id") or "") for row in to_void if row.get("trade_id")}
    void_position_ids = {str(row.get("position_id") or "") for row in to_void if row.get("position_id")}

    latest = books.latest_positions()
    positions_to_void = [
        row
        for pid, row in latest.items()
        if pid in void_position_ids and not is_void_position_row(row)
    ]

    pnl_by_tf: dict[str, float] = {tf: 0.0 for tf in TIMEFRAMES}
    for row in to_void:
        tf = str(row.get("timeframe") or "").upper()
        if tf in pnl_by_tf:
            pnl_by_tf[tf] += float(row.get("net_pnl_usd") or 0.0)
    keep_pnl_by_tf: dict[str, float] = {tf: 0.0 for tf in TIMEFRAMES}
    for row in keep:
        tf = str(row.get("timeframe") or "").upper()
        if tf in keep_pnl_by_tf:
            keep_pnl_by_tf[tf] += float(row.get("net_pnl_usd") or 0.0)

    summary: dict[str, Any] = {
        "epoch_id": epoch_id,
        "voided_at": now,
        "void_class": VOID_CLASS,
        "keep_public_numbers": [row["_public_number"] for row in keep],
        "void_public_numbers": [row["_public_number"] for row in to_void],
        "keep_trades": [_trade_brief(row) for row in keep],
        "void_trades": [_trade_brief(row) for row in to_void],
        "keep_count": len(keep),
        "void_count": len(to_void),
        "positions_to_void": [p.get("position_id") for p in positions_to_void],
        "pnl_removed_by_tf": {k: round(v, 6) for k, v in pnl_by_tf.items()},
        "pnl_removed_total": round(sum(pnl_by_tf.values()), 6),
        "canonical_pnl_by_tf": {k: round(v, 6) for k, v in keep_pnl_by_tf.items()},
        "canonical_pnl_total": round(sum(keep_pnl_by_tf.values()), 6),
        "dry_run": dry_run,
    }
    if dry_run:
        return summary

    backup_root = None
    if backup:
        backup_root = epoch_root / "backups" / f"saw_strength_void_{_utc_stamp()}"
        backup_epoch(epoch_root, backup_root)
        summary["backup_root"] = str(backup_root)

    trades = books.read_all("trades")
    with books.exclusive():
        rewritten: list[dict[str, Any]] = []
        for row in trades:
            tid = str(row.get("trade_id") or "")
            if tid not in void_trade_ids:
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

        for row in to_void:
            original_id = str(row.get("trade_id") or "").strip()
            void_row = dict(row)
            void_row.pop("_public_number", None)
            void_row.pop("_ordinal", None)
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
                    "original_status": str(row.get("status") or "CLOSED"),
                    "paper_epoch_id": epoch_id,
                }
            )
            books.append("positions", void_pos)

        books.append(
            "metrics",
            {
                "metric_type": "EPOCH_SAW_STRENGTH_CANONICAL_VOID",
                "void_class": VOID_CLASS,
                "invalidated_at": now,
                "invalidation_reason": INVALIDATION_REASON_SYSTEM_BUG,
                "invalidation_detail": VOID_DETAIL,
                "trades_voided": len(to_void),
                "positions_voided": len(positions_to_void),
                "keep_public_numbers": [row["_public_number"] for row in keep],
                "void_public_numbers": [row["_public_number"] for row in to_void],
                "pnl_removed_by_tf": {k: round(v, 6) for k, v in pnl_by_tf.items()},
                "pnl_removed_total": round(sum(pnl_by_tf.values()), 6),
                "canonical_pnl_total": round(sum(keep_pnl_by_tf.values()), 6),
                "strategy_pnl_included": False,
                "statistics_included": False,
            },
        )

        remaining = books.closed_trades()
        remaining_by_tf: dict[str, list[dict[str, Any]]] = {tf: [] for tf in TIMEFRAMES}
        for row in remaining:
            tf = str(row.get("timeframe") or "").upper()
            if tf in remaining_by_tf:
                remaining_by_tf[tf].append(row)

        sleeves = SleeveLedger.load(epoch_root)
        if sleeves is not None:
            for tf, sleeve in sleeves.sleeves.items():
                kept_rows = remaining_by_tf.get(tf, [])
                sleeve.cumulative_realized_net_pnl_usd = sum(
                    float(t.get("net_pnl_usd") or 0.0) for t in kept_rows
                )
                sleeve.closed_trades_count = len(kept_rows)
                sleeve.open_position_id = None
                sleeve.open_position_risk_usd = 0.0
                sleeve.last_realized_update_at = now
            sleeves.save()
            master = sleeves.master_snapshot()
            summary["sleeves_rebuilt"] = True
            summary["master_realized_after"] = master["master_realized_net_pnl_usd"]
            summary["master_equity_after"] = master["master_current_equity_usd"]
            summary["sleeve_closed_trades_after"] = {
                tf: sleeves.sleeves[tf].closed_trades_count for tf in TIMEFRAMES if tf in sleeves.sleeves
            }
            books.append(
                "equity_snapshots",
                {
                    "snapshot_ts": now,
                    "equity_usd": master["master_current_equity_usd"],
                    "realized_pnl_usd": master["master_realized_net_pnl_usd"],
                    "unrealized_pnl_usd": 0.0,
                    "note": "SAW_STRENGTH_CANONICAL_VOID_REBUILD",
                },
            )
        else:
            summary["sleeves_rebuilt"] = False

    eligible = books.closed_trades()
    summary["eligible_trades_after"] = len(eligible)
    summary["eligible_pnl_after"] = round(
        sum(float(t.get("net_pnl_usd") or 0.0) for t in eligible), 6
    )
    summary["eligible_after_public"] = [
        {
            "timeframe": t.get("timeframe"),
            "trade_id": t.get("trade_id"),
            "side": t.get("side"),
            "entry_ts": t.get("entry_ts"),
            "net_pnl_usd": round(float(t.get("net_pnl_usd") or 0.0), 4),
        }
        for t in sorted(eligible, key=_sort_key)
    ]
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-id", default=DEFAULT_EPOCH)
    parser.add_argument("--epoch-root", default="")
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    epoch_root = Path(args.epoch_root) if args.epoch_root else (
        Path(args.data_root) / "trading" / "intrabar_paper" / args.epoch_id
    )
    if not epoch_root.exists():
        raise SystemExit(f"epoch root missing: {epoch_root}")

    summary = void_noncanonical_trades(
        epoch_root=epoch_root,
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
