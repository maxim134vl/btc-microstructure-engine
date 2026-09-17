from __future__ import annotations

from pathlib import Path

from btc_ml.trading.command_bus import COMMAND_COLUMNS, CommandBus, CommandBusPaths
from btc_ml.trading.hyperliquid_vault.client import FakeVaultClient
from btc_ml.trading.hyperliquid_vault.config import load_hl_vault_config
from btc_ml.trading.hyperliquid_vault.consumer import VaultCommandConsumer
from btc_ml.trading.hyperliquid_vault.executor import VaultExecutor
from btc_ml.trading.hyperliquid_vault.ledger import VaultLedger
from btc_ml.trading.hyperliquid_vault.orders import aggressive_limit_px, ioc_limit_order, trigger_tpsl_order
from btc_ml.trading.hyperliquid_vault.sizing import resolve_vault_sizing


def _cfg(tmp_path: Path, *, vault: str = "0x1111111111111111111111111111111111111111"):
    root = Path(__file__).resolve().parents[3]
    cfg = load_hl_vault_config(repo_root=root, environ={"HL_VAULT_ADDRESS": vault})
    return cfg.__class__(
        **{
            **cfg.__dict__,
            "books_root": tmp_path / "books_root",
            "kill_flag_path": tmp_path / "KILL",
            "hard_cap_order_btc": 0.01,
            "max_risk_per_trade_usd": 10.0,
            "max_risk_per_trade_pct": 1.0,
        }
    )


def test_sizing_uses_vault_equity_not_paper_100k():
    small = resolve_vault_sizing(
        side="LONG",
        entry_price=100_000,
        vault_equity_usd=500,
        max_risk_per_trade_pct=1.0,
        max_risk_per_trade_usd=1_000,
        stop_loss_bps=100,
        take_profit_bps=150,
        hard_cap_order_btc=1.0,
    )
    paperish = resolve_vault_sizing(
        side="LONG",
        entry_price=100_000,
        vault_equity_usd=100_000,
        max_risk_per_trade_pct=1.0,
        max_risk_per_trade_usd=1_000,
        stop_loss_bps=100,
        take_profit_bps=150,
        hard_cap_order_btc=1.0,
    )
    assert small.ok and paperish.ok
    assert small.risk_usd == 5.0
    assert paperish.risk_usd == 1_000.0
    assert small.quantity < paperish.quantity


def test_hard_cap_clips_qty():
    sized = resolve_vault_sizing(
        side="LONG",
        entry_price=100_000,
        vault_equity_usd=100_000,
        max_risk_per_trade_pct=1.0,
        max_risk_per_trade_usd=1_000,
        stop_loss_bps=100,
        take_profit_bps=150,
        hard_cap_order_btc=0.001,
    )
    assert sized.ok
    assert sized.quantity == 0.001
    assert sized.capped_by_hard_cap is True


def test_unified_account_equity_uses_spot_usdc():
    from btc_ml.trading.hyperliquid_vault.client import account_value_usd, with_unified_equity

    merged = with_unified_equity(
        {"marginSummary": {"accountValue": "0.0", "totalMarginUsed": "0"}},
        spot_state={"balances": [{"coin": "USDC", "total": "964.5"}, {"coin": "HYPE", "total": "1.0"}]},
        abstraction="unifiedAccount",
    )
    assert account_value_usd(merged) == 964.5


def test_order_payloads():
    ioc = ioc_limit_order(is_buy=True, size=0.001, limit_px=aggressive_limit_px(side="LONG", mid=100_000, ioc_slippage_bps=10))
    assert ioc["order_type"] == {"limit": {"tif": "Ioc"}}
    assert abs(ioc["limit_px"] - 100_100.0) < 1e-6
    sl = trigger_tpsl_order(is_buy=False, size=0.001, trigger_px=99_000, tpsl="sl")
    assert sl["order_type"]["trigger"]["tpsl"] == "sl"
    assert sl["reduce_only"] is True
    # hyperliquid-python-sdk float_to_wire formats triggerPx with :.8f
    px = sl["order_type"]["trigger"]["triggerPx"]
    assert isinstance(px, float)
    rounded = f"{px:.8f}"
    assert abs(float(rounded) - px) < 1e-12


def _open_cmd(tf: str = "M15") -> dict:
    return {
        "command_id": "cmd-open-1",
        "timeframe": tf,
        "intent": "OPEN_LONG",
        "action_allowed": True,
        "evaluation_timestamp": "2026-09-06T00:00:00Z",
    }


def test_executor_open_places_ioc_and_native_tpsl(tmp_path: Path):
    cfg = _cfg(tmp_path)
    client = FakeVaultClient(account_value=500.0)
    executor = VaultExecutor(cfg, client, VaultLedger(tmp_path / "ledger"))
    result = executor.apply_command(_open_cmd())
    assert result["status"] == "FILLED"
    kinds = []
    for order in client.placed:
        ot = order["order_type"]
        if "limit" in ot:
            kinds.append("ioc")
        else:
            kinds.append(ot["trigger"]["tpsl"])
    assert kinds == ["ioc", "sl", "tp"]
    assert client.leverage_calls
    pos = executor.ledger.open_positions()["M15"]
    assert pos["side"] == "LONG"
    assert pos["sl_oid"] is not None and pos["tp_oid"] is not None


def test_open_does_not_scale_in_when_tpsl_raises(tmp_path: Path):
    cfg = _cfg(tmp_path)
    client = FakeVaultClient(account_value=500.0, fail_triggers=True)
    executor = VaultExecutor(cfg, client, VaultLedger(tmp_path / "ledger"))
    first = executor.apply_command(_open_cmd())
    assert first["status"] == "FILLED"
    size_after_first = abs(client.positions.get("BTC", 0.0))
    assert size_after_first > 0
    second = executor.apply_command(_open_cmd() | {"command_id": "cmd-open-2"})
    assert second["status"] in {"ENTRY_BLOCKED_ACTIVE_POSITION", "ENTRY_BLOCKED_EXCHANGE_POSITION"}
    assert abs(client.positions.get("BTC", 0.0)) == size_after_first


def test_open_blocks_if_exchange_already_has_size(tmp_path: Path):
    cfg = _cfg(tmp_path)
    client = FakeVaultClient(account_value=500.0, positions={"BTC": 0.001})
    executor = VaultExecutor(cfg, client, VaultLedger(tmp_path / "ledger"))
    result = executor.apply_command(_open_cmd())
    assert result["status"] == "ENTRY_BLOCKED_EXCHANGE_POSITION"
    assert abs(client.positions.get("BTC", 0.0) - 0.001) < 1e-12


def test_executor_close_reduce_only(tmp_path: Path):
    cfg = _cfg(tmp_path)
    client = FakeVaultClient(account_value=500.0)
    executor = VaultExecutor(cfg, client, VaultLedger(tmp_path / "ledger"))
    executor.apply_command(_open_cmd())
    result = executor.apply_command(
        {
            "command_id": "cmd-close-1",
            "timeframe": "M15",
            "intent": "CLOSE",
            "action_allowed": True,
        }
    )
    assert result["status"] == "CLOSED"
    assert abs(client.positions.get("BTC", 0.0)) < 1e-12


def test_kill_flag_flattens(tmp_path: Path):
    cfg = _cfg(tmp_path)
    client = FakeVaultClient(account_value=500.0)
    executor = VaultExecutor(cfg, client, VaultLedger(tmp_path / "ledger"))
    executor.apply_command(_open_cmd())
    cfg.kill_flag_path.write_text("stop\n")
    killed = executor.apply_command(_open_cmd() | {"command_id": "cmd-open-2"})
    assert killed["status"] == "KILLED"
    assert abs(client.positions.get("BTC", 0.0)) < 1e-12


def test_consumer_reads_command_bus(tmp_path: Path):
    cfg = _cfg(tmp_path)
    memory = tmp_path / "commands.parquet"
    paths = CommandBusPaths(
        memory=memory,
        latest=tmp_path / "latest.json",
        manager_state=tmp_path / "state.json",
        portfolio_summary=tmp_path / "port.json",
    )
    bus = CommandBus(paths)
    row = {col: None for col in COMMAND_COLUMNS}
    row.update(_open_cmd())
    row["schema_version"] = "timeframe_manager_command_v1"
    bus.append([row])
    executor = VaultExecutor(cfg, FakeVaultClient(account_value=500.0), VaultLedger(tmp_path / "ledger"))
    consumer = VaultCommandConsumer(
        executor,
        checkpoint_path=tmp_path / "cursor.json",
        consume_after=None,
        bus=bus,
    )
    actions = consumer.poll()
    assert any(a.get("status") == "FILLED" for a in actions)
    again = consumer.poll()
    assert again == []
