#!/usr/bin/env python3
"""Pair paper LIVE1B fills with Hyperliquid vault fills."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.hyperliquid_vault.config import load_hl_vault_config  # noqa: E402
from btc_ml.trading.hyperliquid_vault.ledger import VaultLedger  # noqa: E402
from btc_ml.trading.hyperliquid_vault.reconcile import reconcile_epoch  # noqa: E402
from btc_ml.trading.intrabar_paper.epoch import load_active_epoch  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile paper vs HL vault fills")
    parser.add_argument("--config", default=str(REPO / "config" / "hl_vault_testnet.json"))
    args = parser.parse_args()
    cfg = load_hl_vault_config(args.config, repo_root=REPO)
    epoch = load_active_epoch(cfg.paper_epochs_root)
    if epoch is None:
        print(json.dumps({"error": "no_active_paper_epoch"}))
        return 1
    paper_books = cfg.paper_books_root / epoch.paper_epoch_id / "books"
    ledger = VaultLedger(cfg.books_root / "books")
    result = reconcile_epoch(ledger=ledger, paper_epoch_books=paper_books)
    out = cfg.books_root / "reconcile.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"epoch": epoch.paper_epoch_id, **result["summary"], "pair_count": len(result["pairs"])}, indent=2) + "\n")
    print(json.dumps({"epoch": epoch.paper_epoch_id, **result["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
