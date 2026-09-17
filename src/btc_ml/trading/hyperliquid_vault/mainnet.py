"""Mainnet vault promotion policy: 10k fee, 5% leader share, TVL cap."""

from __future__ import annotations

from typing import Any

from .config import HlVaultMainnetPolicy
from .constants import MAINNET_VAULT_CREATION_FEE_USD, MIN_LEADER_SHARE_PCT, MIN_VAULT_DEPOSIT_USD


ALLOWED_PROMOTIONS = ("private_run", "public_open")


class MainnetPromotionError(ValueError):
    """Unsafe mainnet promotion request."""


def max_public_tvl_usd(leader_equity_usd: float, *, min_leader_share_pct: float = MIN_LEADER_SHARE_PCT) -> float:
    share = float(min_leader_share_pct) / 100.0
    if share <= 0:
        raise MainnetPromotionError("min_leader_share_pct must be > 0")
    return float(leader_equity_usd) / share


def leader_share_pct(leader_equity_usd: float, vault_tvl_usd: float) -> float:
    if vault_tvl_usd <= 0:
        return 100.0
    return 100.0 * float(leader_equity_usd) / float(vault_tvl_usd)


def tvl_cap_status(
    *,
    leader_equity_usd: float,
    vault_tvl_usd: float,
    incoming_deposit_usd: float = 0.0,
    min_leader_share_pct: float = MIN_LEADER_SHARE_PCT,
) -> dict[str, Any]:
    projected = float(vault_tvl_usd) + float(incoming_deposit_usd)
    cap = max_public_tvl_usd(leader_equity_usd, min_leader_share_pct=min_leader_share_pct)
    share = leader_share_pct(leader_equity_usd, projected)
    allowed = share + 1e-9 >= float(min_leader_share_pct)
    return {
        "allowed": allowed,
        "projected_tvl_usd": projected,
        "max_tvl_usd": cap,
        "leader_share_pct": share,
        "min_leader_share_pct": float(min_leader_share_pct),
        "headroom_usd": cap - projected,
    }


def assert_private_run_before_public(policy: HlVaultMainnetPolicy) -> None:
    if policy.promotion not in ALLOWED_PROMOTIONS:
        raise MainnetPromotionError(f"unknown promotion={policy.promotion!r}")
    if policy.promotion == "public_open":
        return
    raise MainnetPromotionError("mainnet vault stays private_run until soak GO and explicit promotion")


def mainnet_creation_budget(*, leader_seed_usd: float, policy: HlVaultMainnetPolicy | None = None) -> dict[str, Any]:
    fee = float(policy.creation_fee_usd) if policy else MAINNET_VAULT_CREATION_FEE_USD
    min_deposit = float(policy.min_leader_deposit_usd) if policy else MIN_VAULT_DEPOSIT_USD
    seed = float(leader_seed_usd)
    return {
        "creation_fee_usd": fee,
        "min_leader_deposit_usd": min_deposit,
        "leader_seed_usd": seed,
        "total_cash_required_usd": fee + max(seed, min_deposit),
        "max_public_tvl_usd": max_public_tvl_usd(max(seed, min_deposit)),
        "announce": False,
        "note": "Create privately, run small, promote only after soak GO.",
    }
