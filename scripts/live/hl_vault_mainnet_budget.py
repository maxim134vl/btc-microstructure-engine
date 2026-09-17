#!/usr/bin/env python3
"""Mainnet vault cash + 5% TVL cap calculator. Does not submit createVault."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.hyperliquid_vault.config import load_hl_vault_config  # noqa: E402
from btc_ml.trading.hyperliquid_vault.mainnet import (  # noqa: E402
    MainnetPromotionError,
    assert_private_run_before_public,
    mainnet_creation_budget,
    tvl_cap_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mainnet vault budget and TVL cap")
    parser.add_argument("--config", default=str(REPO / "config" / "hl_vault_mainnet.json"))
    parser.add_argument("--leader-seed-usd", type=float, required=True)
    parser.add_argument("--vault-tvl-usd", type=float, default=0.0)
    parser.add_argument("--incoming-deposit-usd", type=float, default=0.0)
    parser.add_argument("--allow-public", action="store_true")
    args = parser.parse_args()
    environ = dict(**{k: v for k, v in __import__("os").environ.items()})
    environ.setdefault("HL_MAINNET_ENABLED", "true")
    cfg = load_hl_vault_config(args.config, repo_root=REPO, environ=environ)
    budget = mainnet_creation_budget(leader_seed_usd=args.leader_seed_usd, policy=cfg.mainnet)
    cap = tvl_cap_status(
        leader_equity_usd=max(args.leader_seed_usd, cfg.mainnet.min_leader_deposit_usd),
        vault_tvl_usd=args.vault_tvl_usd,
        incoming_deposit_usd=args.incoming_deposit_usd,
        min_leader_share_pct=cfg.mainnet.min_leader_share_pct,
    )
    promotion_ok = True
    promotion_error = None
    if not args.allow_public:
        try:
            assert_private_run_before_public(cfg.mainnet)
        except MainnetPromotionError as exc:
            promotion_ok = False
            promotion_error = str(exc)
    out = {
        "network": cfg.network,
        "budget": budget,
        "tvl_cap": cap,
        "private_run_required": not args.allow_public,
        "promotion_ok": promotion_ok,
        "promotion_error": promotion_error,
        "announce": False,
    }
    print(json.dumps(out, indent=2))
    return 0 if cap["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
