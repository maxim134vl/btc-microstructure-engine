"""Explicit Hyperliquid Vault execution config. Testnet is the only implicit network."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    ALLOWED_NETWORKS,
    DEFAULT_COIN,
    DEFAULT_TIMEFRAMES,
    ENV_ACCOUNT_ADDRESS,
    ENV_MAINNET_ENABLED,
    ENV_VAULT_ADDRESS,
    MAINNET_API_URL,
    MAINNET_VAULT_CREATION_FEE_USD,
    MAINNET_WS_URL,
    MIN_LEADER_SHARE_PCT,
    MIN_VAULT_DEPOSIT_USD,
    TESTNET_API_URL,
    TESTNET_WS_URL,
)


class HlVaultConfigError(ValueError):
    """Invalid or unsafe vault execution config."""


@dataclass(frozen=True)
class HlVaultSoakConfig:
    min_days: int
    max_days: int
    min_paired_fills: int
    max_liquidations: int
    min_fill_rate: float
    max_median_abs_basis_bps: float
    require_kill_switch_tested: bool


@dataclass(frozen=True)
class HlVaultMainnetPolicy:
    creation_fee_usd: float
    min_leader_deposit_usd: float
    min_leader_share_pct: float
    promotion: str


@dataclass(frozen=True)
class HlVaultConfig:
    schema_version: str
    network: str
    coin: str
    vault_address: str | None
    account_address: str | None
    timeframes: tuple[str, ...]
    max_open_positions_per_timeframe: int
    stop_loss_bps: float
    take_profit_bps: float
    max_risk_per_trade_pct: float
    max_risk_per_trade_usd: float
    ioc_slippage_bps: float
    leverage: int
    is_cross: bool
    max_margin_usage_pct: float
    max_basis_vs_paper_bps: float
    max_consecutive_exchange_errors: int
    hard_cap_order_btc: float
    command_bus: str
    s41_consume_commands_after: str | None
    books_root: Path
    paper_books_root: Path
    paper_epochs_root: Path
    kill_flag_path: Path
    api_url: str
    ws_url: str
    soak: HlVaultSoakConfig
    mainnet: HlVaultMainnetPolicy
    raw: dict[str, Any]

    @property
    def is_testnet(self) -> bool:
        return self.network == "testnet"

    @property
    def is_mainnet(self) -> bool:
        return self.network == "mainnet"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def mainnet_explicitly_enabled(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return str(env.get(ENV_MAINNET_ENABLED, "")).strip().lower() in {"1", "true", "yes"}


def _require_network(network: str, *, environ: dict[str, str] | None) -> str:
    value = str(network or "").strip().lower()
    if value not in ALLOWED_NETWORKS:
        raise HlVaultConfigError(f"unsupported network={network!r}")
    if value == "mainnet" and not mainnet_explicitly_enabled(environ):
        raise HlVaultConfigError(
            "mainnet config refused: set HL_MAINNET_ENABLED=true to load a mainnet vault config"
        )
    return value


def _opt_addr(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    if not text.startswith("0x") or len(text) != 42:
        raise HlVaultConfigError(f"invalid address {text!r}")
    return text.lower()


def load_hl_vault_config(
    path: str | Path | None = None,
    *,
    repo_root: Path | None = None,
    environ: dict[str, str] | None = None,
) -> HlVaultConfig:
    root = repo_root or _repo_root()
    env = environ if environ is not None else dict(os.environ)
    cfg_path = Path(path) if path else root / "config" / "hl_vault_testnet.json"
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    network = _require_network(raw.get("network") or "testnet", environ=env)
    soak_raw = raw.get("soak") or {}
    mainnet_raw = raw.get("mainnet") or {}
    vault_address = _opt_addr(env.get(ENV_VAULT_ADDRESS) or raw.get("vault_address"))
    account_address = _opt_addr(env.get(ENV_ACCOUNT_ADDRESS) or raw.get("account_address"))
    after = raw.get("s41_consume_commands_after")
    tf_env = str(env.get("HL_TIMEFRAMES") or "").strip()
    timeframes = (
        tuple(str(x).upper() for x in tf_env.split(",") if str(x).strip())
        if tf_env
        else tuple(str(x).upper() for x in (raw.get("timeframes") or DEFAULT_TIMEFRAMES))
    )
    kill_rel = str(raw.get("kill_flag_relpath") or "data/trading/hyperliquid_vault/KILL")
    api_url = TESTNET_API_URL if network == "testnet" else MAINNET_API_URL
    ws_url = TESTNET_WS_URL if network == "testnet" else MAINNET_WS_URL
    if network == "testnet" and str(raw.get("api_url") or api_url) == MAINNET_API_URL:
        raise HlVaultConfigError("testnet config must not point at mainnet API")
    return HlVaultConfig(
        schema_version=str(raw["schema_version"]),
        network=network,
        coin=str(raw.get("coin") or DEFAULT_COIN).upper(),
        vault_address=vault_address,
        account_address=account_address,
        timeframes=timeframes,
        max_open_positions_per_timeframe=int(raw.get("max_open_positions_per_timeframe") or 1),
        stop_loss_bps=float(raw["stop_loss_bps"]),
        take_profit_bps=float(raw["take_profit_bps"]),
        max_risk_per_trade_pct=float(raw["max_risk_per_trade_pct"]),
        max_risk_per_trade_usd=float(raw["max_risk_per_trade_usd"]),
        ioc_slippage_bps=float(raw.get("ioc_slippage_bps") or 10.0),
        leverage=int(raw.get("leverage") or 5),
        is_cross=bool(raw.get("is_cross", True)),
        max_margin_usage_pct=float(raw.get("max_margin_usage_pct") or 50.0),
        max_basis_vs_paper_bps=float(raw.get("max_basis_vs_paper_bps") or 50.0),
        max_consecutive_exchange_errors=int(raw.get("max_consecutive_exchange_errors") or 5),
        hard_cap_order_btc=float(raw.get("hard_cap_order_btc") or 0.001),
        command_bus=str(raw.get("command_bus") or "production").strip().lower(),
        s41_consume_commands_after=None if after in (None, "") else str(after),
        books_root=(root / str(raw.get("books_root") or "data/trading/hyperliquid_vault")).resolve(),
        paper_books_root=(root / str(raw.get("paper_books_root") or "data/trading/intrabar_paper")).resolve(),
        paper_epochs_root=(root / str(raw.get("paper_epochs_root") or "data/trading/paper_epochs")).resolve(),
        kill_flag_path=(root / kill_rel).resolve(),
        api_url=api_url,
        ws_url=ws_url,
        soak=HlVaultSoakConfig(
            min_days=int(soak_raw.get("min_days") or 28),
            max_days=int(soak_raw.get("max_days") or 56),
            min_paired_fills=int(soak_raw.get("min_paired_fills") or 30),
            max_liquidations=int(soak_raw.get("max_liquidations") or 0),
            min_fill_rate=float(soak_raw.get("min_fill_rate") or 0.8),
            max_median_abs_basis_bps=float(soak_raw.get("max_median_abs_basis_bps") or 40.0),
            require_kill_switch_tested=bool(soak_raw.get("require_kill_switch_tested", True)),
        ),
        mainnet=HlVaultMainnetPolicy(
            creation_fee_usd=float(mainnet_raw.get("creation_fee_usd") or MAINNET_VAULT_CREATION_FEE_USD),
            min_leader_deposit_usd=float(mainnet_raw.get("min_leader_deposit_usd") or MIN_VAULT_DEPOSIT_USD),
            min_leader_share_pct=float(mainnet_raw.get("min_leader_share_pct") or MIN_LEADER_SHARE_PCT),
            promotion=str(mainnet_raw.get("promotion") or "private_run"),
        ),
        raw=raw,
    )
