from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.trading.hyperliquid_vault.config import HlVaultConfigError, load_hl_vault_config
from btc_ml.trading.hyperliquid_vault.constants import MAINNET_API_URL, TESTNET_API_URL, PAPER_FORBIDDEN_HL_ENV
from btc_ml.trading.hyperliquid_vault.kill_switch import evaluate_kill
from btc_ml.trading.hyperliquid_vault.mainnet import (
    MainnetPromotionError,
    assert_private_run_before_public,
    mainnet_creation_budget,
    max_public_tvl_usd,
    tvl_cap_status,
)


def test_testnet_config_loads(tmp_path: Path):
    cfg = load_hl_vault_config(repo_root=Path(__file__).resolve().parents[3])
    assert cfg.network == "testnet"
    assert cfg.api_url == TESTNET_API_URL
    assert "BTC" == cfg.coin
    assert cfg.timeframes == ("M15", "M30", "H1", "H4")


def test_mainnet_config_refused_without_flag():
    root = Path(__file__).resolve().parents[3]
    with pytest.raises(HlVaultConfigError, match="HL_MAINNET_ENABLED"):
        load_hl_vault_config(root / "config" / "hl_vault_mainnet.json", repo_root=root, environ={})


def test_mainnet_config_loads_with_flag():
    root = Path(__file__).resolve().parents[3]
    cfg = load_hl_vault_config(
        root / "config" / "hl_vault_mainnet.json",
        repo_root=root,
        environ={"HL_MAINNET_ENABLED": "true"},
    )
    assert cfg.network == "mainnet"
    assert cfg.api_url == MAINNET_API_URL
    assert cfg.mainnet.creation_fee_usd == 10_000
    assert cfg.mainnet.promotion == "private_run"


def test_env_vault_address_override(tmp_path: Path):
    root = Path(__file__).resolve().parents[3]
    cfg = load_hl_vault_config(
        repo_root=root,
        environ={"HL_VAULT_ADDRESS": "0x1111111111111111111111111111111111111111"},
    )
    assert cfg.vault_address == "0x1111111111111111111111111111111111111111"


def test_env_master_account_without_vault():
    root = Path(__file__).resolve().parents[3]
    cfg = load_hl_vault_config(
        repo_root=root,
        environ={"HL_ACCOUNT_ADDRESS": "0x2222222222222222222222222222222222222222"},
    )
    assert cfg.vault_address is None
    assert cfg.account_address == "0x2222222222222222222222222222222222222222"


def test_env_timeframes_m15_only():
    root = Path(__file__).resolve().parents[3]
    cfg = load_hl_vault_config(repo_root=root, environ={"HL_TIMEFRAMES": "M15"})
    assert cfg.timeframes == ("M15",)


def test_paper_forbidden_hl_env_covers_agent_keys():
    text = (Path(__file__).resolve().parents[3] / "deploy/vps/entrypoints/paper_only_guard.py").read_text()
    for name in PAPER_FORBIDDEN_HL_ENV:
        assert name in text


def test_kill_switch_margin_and_flag(tmp_path: Path):
    root = Path(__file__).resolve().parents[3]
    cfg = load_hl_vault_config(repo_root=root)
    flag = tmp_path / "KILL"
    cfg = cfg.__class__(**{**cfg.__dict__, "kill_flag_path": flag})
    idle = evaluate_kill(
        cfg=cfg,
        user_state={"marginSummary": {"accountValue": "500", "totalMarginUsed": "10"}},
        consecutive_errors=0,
        already_tripped=False,
        flag_present=False,
    )
    assert not idle.tripped
    hot = evaluate_kill(
        cfg=cfg,
        user_state={"marginSummary": {"accountValue": "100", "totalMarginUsed": "80"}},
        consecutive_errors=0,
        already_tripped=False,
        flag_present=False,
    )
    assert hot.tripped and hot.reason == "MARGIN_USAGE"
    flag.write_text("stop\n")
    flagged = evaluate_kill(
        cfg=cfg,
        user_state=None,
        consecutive_errors=0,
        already_tripped=False,
        flag_present=True,
    )
    assert flagged.reason == "KILL_FLAG"


def test_tvl_cap_and_private_run():
    assert max_public_tvl_usd(10_000) == 200_000
    ok = tvl_cap_status(leader_equity_usd=10_000, vault_tvl_usd=50_000, incoming_deposit_usd=10_000)
    assert ok["allowed"] is True
    blocked = tvl_cap_status(leader_equity_usd=10_000, vault_tvl_usd=190_000, incoming_deposit_usd=20_000)
    assert blocked["allowed"] is False
    budget = mainnet_creation_budget(leader_seed_usd=10_000)
    assert budget["total_cash_required_usd"] == 20_000
    assert budget["announce"] is False
    from btc_ml.trading.hyperliquid_vault.config import HlVaultMainnetPolicy

    policy = HlVaultMainnetPolicy(10_000, 100, 5.0, "private_run")
    with pytest.raises(MainnetPromotionError):
        assert_private_run_before_public(policy)
