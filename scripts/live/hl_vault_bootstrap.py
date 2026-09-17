#!/usr/bin/env python3
"""Hyperliquid testnet vault bootstrap. Dry-run by default; never touches mainnet."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.hyperliquid_vault.bootstrap import (  # noqa: E402
    inspect_testnet,
    run_create_vault,
    run_smoke_order,
)
from btc_ml.trading.hyperliquid_vault.client import FakeVaultClient, SdkVaultClient, mid_px  # noqa: E402
from btc_ml.trading.hyperliquid_vault.config import load_hl_vault_config  # noqa: E402
from btc_ml.trading.hyperliquid_vault.constants import ENV_AGENT_PK  # noqa: E402


def _client(cfg, *, fake: bool):
    if fake:
        return FakeVaultClient()
    pk = os.environ.get(ENV_AGENT_PK) or os.environ.get("HL_AGENT_PK")
    if not pk:
        raise SystemExit(f"missing {ENV_AGENT_PK} for --execute")
    return SdkVaultClient(
        api_url=cfg.api_url,
        vault_address=cfg.vault_address,
        account_address=cfg.account_address,
        agent_key=pk,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Hyperliquid testnet vault")
    parser.add_argument("--config", default=str(REPO / "config" / "hl_vault_testnet.json"))
    parser.add_argument("--execute", action="store_true", help="Call the testnet API (requires agent key)")
    parser.add_argument("--fake", action="store_true", help="Use in-memory client (tests / rehearsal)")
    parser.add_argument("--create-vault", action="store_true")
    parser.add_argument("--vault-name", default="BTC ML Testnet Vault")
    parser.add_argument("--vault-description", default="S4.1 BTC-PERP testnet vault for model verification")
    parser.add_argument("--initial-usd", type=float, default=100.0)
    parser.add_argument("--smoke-order", action="store_true")
    parser.add_argument("--smoke-size", type=float, default=0.0001)
    args = parser.parse_args()

    cfg = load_hl_vault_config(args.config, repo_root=REPO)
    if not cfg.is_testnet:
        print(json.dumps({"error": "bootstrap is testnet-only"}, indent=2))
        return 2

    report = inspect_testnet(cfg, client=_client(cfg, fake=True) if args.fake else None)
    payload = report.to_dict()
    if not args.execute:
        payload["mode"] = "dry_run"
        payload["next"] = [
            "Complete the manual faucet/vault steps if checks are incomplete",
            f"export {ENV_AGENT_PK} and HL_ACCOUNT_ADDRESS (Master) or HL_VAULT_ADDRESS",
            "Re-run with --execute --fake for a local rehearsal, or --execute --smoke-order on testnet",
        ]
        print(json.dumps(payload, indent=2))
        return 0

    client = _client(cfg, fake=args.fake)
    actions: dict[str, object] = {}
    if args.create_vault:
        actions["create_vault"] = run_create_vault(
            client,
            name=args.vault_name,
            description=args.vault_description,
            initial_usd=args.initial_usd,
        )
    if args.smoke_order:
        mids = client.all_mids()
        actions["smoke_order"] = run_smoke_order(
            client,
            coin=cfg.coin,
            size=args.smoke_size,
            mid=mid_px(mids, cfg.coin),
        )
    payload["mode"] = "execute"
    payload["fake"] = bool(args.fake)
    payload["actions"] = actions
    payload["ready"] = inspect_testnet(cfg, client=client).ready or bool(actions)
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
