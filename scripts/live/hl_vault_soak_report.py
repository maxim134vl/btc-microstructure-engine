#!/usr/bin/env python3
"""Evaluate Hyperliquid vault soak go/no-go gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.hyperliquid_vault.config import load_hl_vault_config  # noqa: E402
from btc_ml.trading.hyperliquid_vault.ledger import VaultLedger  # noqa: E402
from btc_ml.trading.hyperliquid_vault.reconcile import summarize_pairs  # noqa: E402
from btc_ml.trading.hyperliquid_vault.soak import evaluate_soak_gates  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="HL vault soak go/no-go report")
    parser.add_argument("--config", default=str(REPO / "config" / "hl_vault_testnet.json"))
    parser.add_argument("--started-at", default=None)
    parser.add_argument("--liquidations", type=int, default=0)
    parser.add_argument("--kill-switch-tested", action="store_true")
    parser.add_argument("--public-testnet", action="store_true", default=True)
    args = parser.parse_args()
    cfg = load_hl_vault_config(args.config, repo_root=REPO)
    ledger = VaultLedger(cfg.books_root / "books")
    pairs = ledger.read_all("pairs")
    summary = summarize_pairs(pairs)
    gates_meta = json.loads((REPO / "config" / "hl_vault_soak_gates.json").read_text(encoding="utf-8"))
    started = args.started_at
    if started is None:
        events = ledger.read_all("events")
        started = next((e.get("ts") for e in events if e.get("kind") == "SOAK_START"), None)
    report = evaluate_soak_gates(
        soak=cfg.soak,
        started_at=started,
        paired_fills=int(summary.get("paired_count") or 0),
        liquidations=args.liquidations,
        fill_rate=float(summary.get("fill_rate") or 0.0),
        median_abs_basis_bps=summary.get("median_abs_basis_bps"),
        kill_switch_tested=bool(args.kill_switch_tested),
        public_testnet_enabled=bool(args.public_testnet and gates_meta.get("public_testnet_vault")),
    )
    out = {
        "network": cfg.network,
        "promotion_after_go": gates_meta.get("promotion_after_go"),
        "summary": summary,
        **report,
    }
    dest = cfg.books_root / "soak_report.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
