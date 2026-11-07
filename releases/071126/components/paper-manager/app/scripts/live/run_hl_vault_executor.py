#!/usr/bin/env python3
"""Detached Hyperliquid vault executor. Separate process from LIVE1B paper."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from btc_ml.trading.command_bus import CommandBus, CommandBusPaths  # noqa: E402
from btc_ml.trading.hyperliquid_vault.client import FakeVaultClient, SdkVaultClient  # noqa: E402
from btc_ml.trading.hyperliquid_vault.config import load_hl_vault_config  # noqa: E402
from btc_ml.trading.hyperliquid_vault.constants import ENV_AGENT_PK, ENV_MAINNET_AGENT_PK  # noqa: E402
from btc_ml.trading.hyperliquid_vault.consumer import VaultCommandConsumer  # noqa: E402
from btc_ml.trading.hyperliquid_vault.executor import VaultExecutor  # noqa: E402
from btc_ml.trading.hyperliquid_vault.ledger import VaultLedger, utc_now  # noqa: E402
from btc_ml.trading.trader_book import atomic_write_json  # noqa: E402

STOP = False


def _handle_stop(*_args: object) -> None:
    global STOP
    STOP = True


def _client(cfg, *, fake: bool):
    if fake:
        return FakeVaultClient(account_value=500.0)
    env_key = ENV_MAINNET_AGENT_PK if cfg.is_mainnet else ENV_AGENT_PK
    pk = os.environ.get(env_key) or os.environ.get("HL_AGENT_PK")
    if not pk:
        raise SystemExit(f"missing {env_key}")
    if not cfg.vault_address and not cfg.account_address:
        raise SystemExit("HL_VAULT_ADDRESS or HL_ACCOUNT_ADDRESS required")
    return SdkVaultClient(
        api_url=cfg.api_url,
        vault_address=cfg.vault_address,
        account_address=cfg.account_address,
        agent_key=pk,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="S4.1 → Hyperliquid vault executor")
    parser.add_argument("--config", default=str(REPO / "config" / "hl_vault_testnet.json"))
    parser.add_argument("--poll-ms", type=int, default=500)
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cfg = load_hl_vault_config(args.config, repo_root=REPO)
    if args.fake and not cfg.vault_address:
        cfg = replace(cfg, vault_address="0x1111111111111111111111111111111111111111")
    if cfg.s41_consume_commands_after is None:
        cfg = replace(cfg, s41_consume_commands_after=utc_now())
    ledger = VaultLedger(cfg.books_root / "books")
    bus = CommandBus(CommandBusPaths.production() if cfg.command_bus != "candidate" else CommandBusPaths.candidate())
    executor = VaultExecutor(cfg, _client(cfg, fake=args.fake), ledger)
    consumer = VaultCommandConsumer(
        executor,
        checkpoint_path=cfg.books_root / "s41_cursor.json",
        consume_after=cfg.s41_consume_commands_after,
        bus=bus,
    )
    health_path = cfg.books_root / "health.json"
    if not any(row.get("kind") == "SOAK_START" for row in ledger.read_all("events")):
        ledger.append("events", {"kind": "SOAK_START", "network": cfg.network})
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    while not STOP:
        try:
            actions = consumer.poll()
            killed = executor.maybe_kill()
            atomic_write_json(
                health_path,
                {
                    "ok": killed is None and executor.health.get("ok", True),
                    "network": cfg.network,
                    "vault_address": cfg.vault_address,
                    "account_address": cfg.account_address,
                    "execution_mode": "vault" if cfg.vault_address else "master",
                    "actions": len(actions),
                    "kill": None if killed is None else killed,
                    "updated_at": utc_now(),
                    "timeframes": list(cfg.timeframes),
                    "consume_after": cfg.s41_consume_commands_after,
                    "fake": bool(args.fake),
                },
            )
        except Exception as exc:  # noqa: BLE001
            atomic_write_json(
                health_path,
                {"ok": False, "error": str(exc), "updated_at": utc_now(), "network": cfg.network},
            )
        if args.once:
            break
        time.sleep(max(args.poll_ms, 50) / 1000.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
