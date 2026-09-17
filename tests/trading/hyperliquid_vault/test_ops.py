from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from btc_ml.trading.hyperliquid_vault.bootstrap import bootstrap_plan, inspect_testnet, run_create_vault, run_smoke_order
from btc_ml.trading.hyperliquid_vault.client import FakeVaultClient, mid_px
from btc_ml.trading.hyperliquid_vault.config import load_hl_vault_config
from btc_ml.trading.hyperliquid_vault.ledger import VaultLedger
from btc_ml.trading.hyperliquid_vault.reconcile import pair_fills, summarize_pairs
from btc_ml.trading.hyperliquid_vault.soak import evaluate_soak_gates


def test_bootstrap_plan_is_testnet_only():
    cfg = load_hl_vault_config(repo_root=Path(__file__).resolve().parents[3])
    steps = bootstrap_plan(cfg)
    ids = [s["id"] for s in steps]
    assert ids == ["mainnet_deposit", "testnet_faucet", "create_vault", "approve_agent", "smoke_order"]


def test_bootstrap_inspect_and_smoke_with_fake():
    root = Path(__file__).resolve().parents[3]
    cfg = load_hl_vault_config(
        repo_root=root,
        environ={"HL_VAULT_ADDRESS": "0x1111111111111111111111111111111111111111"},
    )
    client = FakeVaultClient(account_value=500.0)
    report = inspect_testnet(cfg, client=client)
    assert report.ready is True
    created = run_create_vault(client, name="BTC ML Testnet Vault", description="S4.1 BTC-PERP verification vault", initial_usd=100)
    assert created["status"] == "ok"
    smoke = run_smoke_order(client, coin="BTC", size=0.0001, mid=mid_px(client.all_mids(), "BTC"))
    assert "placed" in smoke


def test_pair_fills_basis():
    paper = [
        {
            "manager_command_id": "c1",
            "action": "ENTRY",
            "paper_fill_price": 100_000.0,
            "timeframe": "M15",
        }
    ]
    hl = [
        {
            "manager_command_id": "c1",
            "action": "ENTRY",
            "avg_px": 100_050.0,
            "hl_mid": 100_040.0,
            "timeframe": "M15",
            "quantity": 0.001,
        }
    ]
    pairs = pair_fills(paper_fills=paper, hl_fills=hl)
    assert pairs[0]["paired"] is True
    assert abs(pairs[0]["basis_bps"] - 5.0) < 1e-6
    summary = summarize_pairs(pairs, attempted_commands=1)
    assert summary["paired_count"] == 1
    assert summary["fill_rate"] == 1.0


def test_soak_gates_no_go_then_go(tmp_path: Path):
    cfg = load_hl_vault_config(repo_root=Path(__file__).resolve().parents[3])
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    early = evaluate_soak_gates(
        soak=cfg.soak,
        started_at=(now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
        now=now,
        paired_fills=2,
        liquidations=0,
        fill_rate=1.0,
        median_abs_basis_bps=5.0,
        kill_switch_tested=True,
        public_testnet_enabled=True,
    )
    assert early["verdict"] == "NO_GO"
    ready = evaluate_soak_gates(
        soak=cfg.soak,
        started_at=(now - timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        now=now,
        paired_fills=40,
        liquidations=0,
        fill_rate=0.9,
        median_abs_basis_bps=12.0,
        kill_switch_tested=True,
        public_testnet_enabled=True,
    )
    assert ready["verdict"] == "GO"
    ledger = VaultLedger(tmp_path / "books")
    ledger.append("events", {"kind": "SOAK_START"})
    assert ledger.read_all("events")[0]["kind"] == "SOAK_START"
