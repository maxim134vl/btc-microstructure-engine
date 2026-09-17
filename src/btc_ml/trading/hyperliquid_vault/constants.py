"""Hyperliquid Vault network constants. Mainnet URLs are never the default."""

from __future__ import annotations

TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"
TESTNET_WS_URL = "wss://api.hyperliquid-testnet.xyz/ws"
TESTNET_APP_URL = "https://app.hyperliquid-testnet.xyz"
TESTNET_FAUCET_URL = "https://app.hyperliquid-testnet.xyz/drip"

MAINNET_API_URL = "https://api.hyperliquid.xyz"
MAINNET_WS_URL = "wss://api.hyperliquid.xyz/ws"
MAINNET_APP_URL = "https://app.hyperliquid.xyz"

ALLOWED_NETWORKS = ("testnet", "mainnet")
DEFAULT_COIN = "BTC"
DEFAULT_TIMEFRAMES = ("M15", "M30", "H1", "H4")

# Official faucet grant (mock USDC) after a prior mainnet deposit.
TESTNET_FAUCET_USDC = 1000.0
# Legacy HyperCore vault creation rules (mainnet). Testnet fee may be waived.
MAINNET_VAULT_CREATION_FEE_USD = 10_000.0
MIN_VAULT_DEPOSIT_USD = 100.0
MIN_LEADER_SHARE_PCT = 5.0
LEADER_PROFIT_SHARE_PCT = 10.0
DEPOSITOR_LOCKUP_DAYS = 1
AGENT_MAX_TTL_DAYS = 180

# initialUsd in Hyperliquid actions is USDC * 1e6.
USDC_MICRO = 1_000_000

ENV_AGENT_PK = "HL_TESTNET_AGENT_PK"
ENV_MAINNET_AGENT_PK = "HL_MAINNET_AGENT_PK"
ENV_VAULT_ADDRESS = "HL_VAULT_ADDRESS"
ENV_ACCOUNT_ADDRESS = "HL_ACCOUNT_ADDRESS"
ENV_MAINNET_ENABLED = "HL_MAINNET_ENABLED"

PAPER_FORBIDDEN_HL_ENV = (
    ENV_AGENT_PK,
    ENV_MAINNET_AGENT_PK,
    "HL_AGENT_PK",
    "HL_MASTER_PK",
)
