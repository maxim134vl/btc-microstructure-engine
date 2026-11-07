#!/usr/bin/env python3
"""Recover one missed protective stop-loss close via append-only ledger writes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.intrabar_paper.books import EpochBooks
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.ops_adapter import build_intrabar_epoch_performance_summary, load_active_paper_epoch
from btc_ml.trading.intrabar_paper.position_invalidation import latest_position_row
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger
from btc_ml.trading.intrabar_paper.stop_loss_recovery import (
    RECOVERY_REASON_SYSTEM_BUG_STOP_LOSS,
    find_recovery_trade,
    recover_missed_stop_loss,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_epoch(epoch_root: Path, backup_root: Path) -> None:
    backup_root.mkdir(parents=True, exist_ok=True)
    for name in ("books", "sleeves.json"):
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover missed stop-loss close for one OPEN position")
    parser.add_argument("--epoch-id", required=True)
    parser.add_argument("--position-id", required=True)
    parser.add_argument("--exit-price", type=float, required=True)
    parser.add_argument("--skip-backup", action="store_true")
    args = parser.parse_args()

    cfg = load_intrabar_paper_config(repo_root=ROOT)
    epoch = load_active_paper_epoch(repo_root=ROOT)
    if epoch is None:
        print(json.dumps({"error": "no_active_epoch"}))
        return 2
    if str(epoch.get("paper_epoch_id")) != args.epoch_id:
        print(
            json.dumps(
                {
                    "error": "epoch_mismatch",
                    "active_epoch": epoch.get("paper_epoch_id"),
                    "requested_epoch": args.epoch_id,
                }
            )
        )
        return 3

    epoch_root = ROOT / "data" / "trading" / "intrabar_paper" / args.epoch_id
    books = EpochBooks(epoch_root / "books", paper_epoch_id=args.epoch_id)
    backup_root = epoch_root / "backups" / f"stop_loss_recovery_{args.position_id}_{_utc_stamp()}"

    if not args.skip_backup:
        _backup_epoch(epoch_root, backup_root)

    result = recover_missed_stop_loss(
        books,
        position_id=args.position_id,
        exit_price=float(args.exit_price),
        cfg=cfg,
        epoch_root=epoch_root,
        recovery_reason=RECOVERY_REASON_SYSTEM_BUG_STOP_LOSS,
    )

    latest = latest_position_row(books, args.position_id)
    trade = find_recovery_trade(books, args.position_id)
    sleeves = SleeveLedger.load(epoch_root)
    m30 = sleeves.get("M30").to_dict() if sleeves is not None else None
    summary = build_intrabar_epoch_performance_summary(epoch=epoch, repo_root=ROOT)

    payload = {
        "backup_root": str(backup_root) if not args.skip_backup else None,
        "recovery": result,
        "latest_position": latest,
        "recovery_trade": trade,
        "m30_sleeve": m30,
        "epoch_summary": summary,
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
