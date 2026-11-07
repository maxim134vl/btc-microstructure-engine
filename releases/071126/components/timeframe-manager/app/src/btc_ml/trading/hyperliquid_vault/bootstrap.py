"""Testnet vault bootstrap checklist + optional signed actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .client import VaultExchange, account_value_usd, post_info
from .config import HlVaultConfig
from .constants import (
    MIN_VAULT_DEPOSIT_USD,
    TESTNET_APP_URL,
    TESTNET_FAUCET_URL,
    TESTNET_FAUCET_USDC,
)


MANUAL_STEPS = (
    {
        "id": "mainnet_deposit",
        "title": "Deposit USDC on Hyperliquid mainnet with the same EOA",
        "why": "Testnet faucet requires a prior mainnet deposit on this address",
        "url": "https://app.hyperliquid.xyz",
    },
    {
        "id": "testnet_faucet",
        "title": "Claim mock USDC from the testnet faucet",
        "why": f"Faucet grants about {TESTNET_FAUCET_USDC:.0f} mock USDC",
        "url": TESTNET_FAUCET_URL,
    },
    {
        "id": "create_vault",
        "title": "Create a legacy HyperCore vault on testnet",
        "why": "Name/description are immutable; seed at least 100 mock USDC",
        "url": f"{TESTNET_APP_URL}/vaults",
    },
    {
        "id": "approve_agent",
        "title": "Approve a named API agent (TTL <= 180 days)",
        "why": "VPS stores only the agent key; never the master key",
        "url": TESTNET_APP_URL,
    },
    {
        "id": "smoke_order",
        "title": "Place and cancel a tiny BTC limit on the vault",
        "why": "Confirms vaultAddress signing before the executor is attached",
        "url": TESTNET_APP_URL,
    },
)


@dataclass
class BootstrapReport:
    network: str
    ready: bool
    steps: list[dict[str, Any]] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "ready": self.ready,
            "steps": self.steps,
            "checks": self.checks,
            "errors": self.errors,
        }


def bootstrap_plan(cfg: HlVaultConfig) -> list[dict[str, Any]]:
    if not cfg.is_testnet:
        return [
            {
                "id": "refuse_mainnet_bootstrap",
                "title": "Refuse: bootstrap is testnet-only",
                "why": "Mainnet vault creation costs 10k USDC and is a later gated step",
                "url": None,
            }
        ]
    return [dict(step) for step in MANUAL_STEPS]


def inspect_testnet(
    cfg: HlVaultConfig,
    *,
    client: VaultExchange | None = None,
    info_post=post_info,
) -> BootstrapReport:
    report = BootstrapReport(network=cfg.network, ready=False, steps=bootstrap_plan(cfg))
    if not cfg.is_testnet:
        report.errors.append("bootstrap_testnet_only")
        return report
    query_addr = cfg.vault_address or cfg.account_address
    report.checks["query_address"] = query_addr
    report.checks["api_url"] = cfg.api_url
    if query_addr is None:
        report.errors.append("missing_vault_or_account_address")
        return report
    try:
        state = (
            client.user_state(query_addr)
            if client is not None
            else info_post(cfg.api_url, {"type": "clearinghouseState", "user": query_addr})
        )
        equity = account_value_usd(state) if isinstance(state, dict) else 0.0
        report.checks["account_value_usd"] = equity
        report.checks["has_funds"] = equity > 0
        report.checks["meets_min_vault_deposit"] = equity >= MIN_VAULT_DEPOSIT_USD
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"user_state:{exc}")
        return report
    report.ready = bool(query_addr) and equity > 0
    report.checks["vault_address_set"] = bool(cfg.vault_address)
    report.checks["account_address_set"] = bool(cfg.account_address)
    report.checks["execution_mode"] = "vault" if cfg.vault_address else "master"
    return report


def run_create_vault(
    client: VaultExchange,
    *,
    name: str,
    description: str,
    initial_usd: float,
) -> dict[str, Any]:
    if initial_usd < MIN_VAULT_DEPOSIT_USD:
        raise ValueError(f"initial_usd must be >= {MIN_VAULT_DEPOSIT_USD}")
    if len(name) < 3 or len(name) > 50:
        raise ValueError("vault name must be 3-50 characters")
    if len(description) < 10 or len(description) > 250:
        raise ValueError("vault description must be 10-250 characters")
    return client.create_vault(name, description, initial_usd)


def run_smoke_order(client: VaultExchange, *, coin: str, size: float, mid: float) -> dict[str, Any]:
    from .orders import ioc_limit_order, parse_order_result

    placed = client.place_order(coin, ioc_limit_order(is_buy=True, size=size, limit_px=mid * 0.5))
    parsed = parse_order_result(placed)
    if parsed.oid is not None and not parsed.filled:
        cancelled = client.cancel(coin, parsed.oid)
        return {"placed": placed, "cancelled": cancelled, "mode": "resting_cancelled"}
    return {"placed": placed, "mode": "filled_or_rejected", "parsed": parsed.__dict__}
