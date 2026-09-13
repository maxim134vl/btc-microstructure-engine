from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.trading.binance_kz.client import (
    EndpointForbidden,
    FakePapiClient,
    LivePapiClient,
    RecordingTransport,
    assert_allowed,
)
from btc_ml.trading.binance_kz.config import BinanceKzConfigError, load_binance_kz_config
from btc_ml.trading.binance_kz.constants import (
    ENV_LIVE_ENABLED,
    PAPER_FORBIDDEN_BINANCE_KZ_ENV,
    PAPI_REST_URL,
    UNKNOWN_ORDER_MESSAGE,
)
from btc_ml.trading.binance_kz.consumer import BinanceKzCommandConsumer
from btc_ml.trading.binance_kz.executor import BinanceKzExecutor
from btc_ml.trading.binance_kz.guard import evaluate_start
from btc_ml.trading.binance_kz.kill_switch import can_open, evaluate_kill
from btc_ml.trading.binance_kz.ledger import BinanceKzLedger
from btc_ml.trading.binance_kz.orders import CLIENT_ORDER_ID_RE, client_order_id_for
from btc_ml.trading.binance_kz.reconcile import place_or_reconcile
from btc_ml.trading.binance_kz.signing import hmac_sha256_hex, signed_query
from btc_ml.trading.binance_kz.sizing import resolve_live_sizing
from btc_ml.trading.command_bus import COMMAND_COLUMNS, CommandBus, CommandBusPaths


ROOT = Path(__file__).resolve().parents[3]


def _cfg(tmp_path: Path):
    cfg = load_binance_kz_config(repo_root=ROOT, environ={})
    return cfg.__class__(
        **{
            **cfg.__dict__,
            "books_root": tmp_path / "binance_kz",
            "paper_books_root": tmp_path / "intrabar_paper",
            "paper_epochs_root": tmp_path / "paper_epochs",
            "kill_flag_path": tmp_path / "KILL",
        }
    )


def _open_cmd(tf: str = "M15", command_id: str = "cmd-open-1", episode: str = "M15:1") -> dict:
    return {
        "command_id": command_id,
        "timeframe": tf,
        "intent": "OPEN_LONG",
        "action_allowed": True,
        "evaluation_timestamp": "2026-09-13T00:00:00Z",
        "lifecycle_episode_id": episode,
    }


def test_hmac_matches_binance_official_example():
    secret = "2b5eb11e18796d12d88f13dc27dbbd02c2cc51ff7059765ed9821957d82bb4d9"
    payload = (
        "symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=1&price=9000&timeInForce=GTC"
        "&recvWindow=5000&timestamp=1591702613943"
    )
    assert hmac_sha256_hex(secret, payload) == "3c661234138461fcc7a7d8746c6558c9842d4e10870d2ecbedf7777cad694af9"


def test_signed_query_keeps_signature_last():
    query = signed_query(
        {"symbol": "BTCUSDT", "side": "BUY"},
        timestamp_ms=1,
        recv_window_ms=5000,
        hmac_secret="secret",
    )
    assert query.endswith(query.split("&signature=")[-1])
    assert "signature=" in query
    assert "secret" not in query.split("&signature=")[0]


def test_client_order_id_is_deterministic_and_legal():
    a = client_order_id_for("cmd-open-1")
    b = client_order_id_for("cmd-open-1")
    c = client_order_id_for("cmd-open-2")
    assert a == b != c
    assert len(a) == 36
    assert CLIENT_ORDER_ID_RE.match(a)


def test_config_loads_unarmed_and_refuses_wrong_host(tmp_path: Path):
    cfg = load_binance_kz_config(repo_root=ROOT, environ={})
    assert cfg.real_execution_enabled is False
    assert cfg.papi_url == PAPI_REST_URL
    assert cfg.leverage == 2
    assert cfg.timeframes == ("M15",)
    bad = json.loads((ROOT / "config" / "binance_kz_live.json").read_text())
    bad["papi_url"] = "https://fapi.binance.com"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(BinanceKzConfigError, match="papi_url"):
        load_binance_kz_config(path, repo_root=ROOT, environ={})


def test_config_refuses_leverage_above_2(tmp_path: Path):
    raw = json.loads((ROOT / "config" / "binance_kz_live.json").read_text())
    raw["leverage"] = 5
    path = tmp_path / "lev.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(BinanceKzConfigError, match="leverage"):
        load_binance_kz_config(path, repo_root=ROOT, environ={})


def test_config_refuses_armed_live_without_env_flag(tmp_path: Path):
    raw = json.loads((ROOT / "config" / "binance_kz_live.json").read_text())
    raw["real_execution_enabled"] = True
    path = tmp_path / "armed.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(BinanceKzConfigError, match=ENV_LIVE_ENABLED):
        load_binance_kz_config(path, repo_root=ROOT, environ={})
    cfg = load_binance_kz_config(path, repo_root=ROOT, environ={ENV_LIVE_ENABLED: "true"})
    assert cfg.real_execution_enabled is True


def test_paper_only_guard_forbids_kz_credentials():
    text = (ROOT / "deploy/vps/entrypoints/paper_only_guard.py").read_text()
    for name in PAPER_FORBIDDEN_BINANCE_KZ_ENV:
        assert name in text


def test_paper_execution_stays_disarmed():
    paper = json.loads((ROOT / "config" / "intrabar_paper_execution.json").read_text())
    assert paper["paper_only"] is True
    assert paper["real_execution_enabled"] is False


def test_whitelist_blocks_withdraw_and_fapi_trade():
    with pytest.raises(EndpointForbidden):
        assert_allowed("POST", "/sapi/v1/capital/withdraw/apply")
    with pytest.raises(EndpointForbidden):
        assert_allowed("POST", "/fapi/v1/order")
    with pytest.raises(EndpointForbidden):
        assert_allowed("POST", "/papi/v1/cm/order")
    assert_allowed("POST", "/papi/v1/um/order")
    assert_allowed("GET", "/fapi/v1/time")


def test_live_client_refuses_unarmed():
    with pytest.raises(RuntimeError, match="not armed"):
        LivePapiClient(api_key="k", hmac_secret="s", armed=False)


def test_post_order_503_unknown_does_not_retry():
    transport = RecordingTransport(
        lambda method, path, call: (
            (503, {}, json.dumps({"msg": UNKNOWN_ORDER_MESSAGE}))
            if method == "POST" and path == "/papi/v1/um/order"
            else (200, {}, json.dumps({"status": "FILLED", "executedQty": "0.01", "avgPrice": "77000", "orderId": 7, "clientOrderId": "s41x"}))
        )
    )
    client = LivePapiClient(
        api_key="k",
        hmac_secret="s",
        armed=True,
        transport=transport,
    )
    result = place_or_reconcile(client, {"symbol": "BTCUSDT", "newClientOrderId": "s41x", "side": "BUY", "type": "LIMIT"})
    assert result["status"] == "FILLED"
    assert client.post_order_attempts == 1
    posts = [c for c in transport.calls if c["method"] == "POST"]
    gets = [c for c in transport.calls if c["method"] == "GET"]
    assert len(posts) == 1
    assert len(gets) == 1


def test_live_client_blocks_forbidden_path_before_transport():
    transport = RecordingTransport(lambda *args: (200, {}, "{}"))
    client = LivePapiClient(api_key="k", hmac_secret="s", armed=True, transport=transport)
    with pytest.raises(EndpointForbidden):
        client.request("POST", "/sapi/v1/capital/withdraw/apply", signed=True)
    assert transport.calls == []


def test_sizing_uses_live_equity_not_paper_100k():
    live = resolve_live_sizing(
        side="LONG",
        entry_price=77_000,
        equity_usd=165_000,
        stop_loss_bps=100,
        take_profit_bps=150,
        leverage=2,
        catboost_mult=1.0,
    )
    paperish = resolve_live_sizing(
        side="LONG",
        entry_price=77_000,
        equity_usd=100_000,
        stop_loss_bps=100,
        take_profit_bps=150,
        leverage=2,
        catboost_mult=1.0,
    )
    assert live.ok and paperish.ok
    assert live.risk_usd == pytest.approx(1650.0)
    assert paperish.risk_usd == pytest.approx(1000.0)
    assert live.quantity is not None and paperish.quantity is not None
    assert live.quantity > paperish.quantity


def test_catboost_1_5_is_recapped_to_1_pct():
    base = resolve_live_sizing(
        side="LONG",
        entry_price=77_000,
        equity_usd=165_000,
        stop_loss_bps=100,
        take_profit_bps=150,
        leverage=2,
        catboost_mult=1.0,
    )
    hot = resolve_live_sizing(
        side="LONG",
        entry_price=77_000,
        equity_usd=165_000,
        stop_loss_bps=100,
        take_profit_bps=150,
        leverage=2,
        catboost_mult=1.5,
    )
    cool = resolve_live_sizing(
        side="LONG",
        entry_price=77_000,
        equity_usd=165_000,
        stop_loss_bps=100,
        take_profit_bps=150,
        leverage=2,
        catboost_mult=0.5,
    )
    assert base.ok and hot.ok and cool.ok
    assert hot.risk_usd == pytest.approx(base.risk_usd)
    assert cool.risk_usd == pytest.approx(base.risk_usd * 0.5)


def test_unimmr_gates():
    ok, reason = can_open(unimmr=2.0, min_unimmr_open=2.0)
    assert ok and reason is None
    blocked, reason = can_open(unimmr=1.9, min_unimmr_open=2.0)
    assert not blocked and reason == "ENTRY_BLOCKED_UNIMMR"
    kill = evaluate_kill(
        consecutive_errors=0,
        max_consecutive_errors=5,
        already_tripped=False,
        flag_present=False,
        account={"uniMMR": "1.4", "actualEquity": "165000"},
    )
    assert kill.tripped and kill.reason == "UNIMMR_KILL" and kill.flatten is True


def test_executor_open_close_and_native_tpsl(tmp_path: Path):
    cfg = _cfg(tmp_path)
    client = FakePapiClient()
    executor = BinanceKzExecutor(cfg, client, BinanceKzLedger(tmp_path / "ledger"))
    result = executor.apply_command(_open_cmd())
    assert result["status"] == "FILLED"
    types = [p.get("type") for p in client.posts]
    assert types == ["LIMIT", "STOP_MARKET", "TAKE_PROFIT_MARKET"]
    pos = executor.ledger.open_positions()["M15"]
    assert pos["side"] == "LONG"
    assert pos["sl_client_order_id"] and pos["tp_client_order_id"]
    closed = executor.apply_command(
        {"command_id": "cmd-close-1", "timeframe": "M15", "intent": "CLOSE", "action_allowed": True}
    )
    assert closed["status"] == "CLOSED"
    assert abs(client.positions.get("BTCUSDT", 0.0)) < 1e-12


def test_executor_rejects_non_m15_and_low_unimmr(tmp_path: Path):
    cfg = _cfg(tmp_path)
    client = FakePapiClient(uni_mmr=1.9)
    executor = BinanceKzExecutor(cfg, client, BinanceKzLedger(tmp_path / "ledger"))
    assert executor.apply_command(_open_cmd(tf="H1"))["status"] == "REJECTED_BAD_COMMAND"
    blocked = executor.apply_command(_open_cmd())
    assert blocked["status"] == "ENTRY_BLOCKED_UNIMMR"


def test_same_episode_second_open_blocked(tmp_path: Path):
    cfg = _cfg(tmp_path)
    executor = BinanceKzExecutor(cfg, FakePapiClient(), BinanceKzLedger(tmp_path / "ledger"))
    assert executor.apply_command(_open_cmd())["status"] == "FILLED"
    executor.apply_command({"command_id": "c2", "timeframe": "M15", "intent": "CLOSE", "action_allowed": True})
    again = executor.apply_command(_open_cmd(command_id="cmd-open-2", episode="M15:1"))
    assert again["status"] == "ENTRY_BLOCKED_EPISODE_ALREADY_TRADED"
    nxt = executor.apply_command(_open_cmd(command_id="cmd-open-3", episode="M15:2"))
    assert nxt["status"] == "FILLED"


def test_503_unknown_reconciles_without_second_post(tmp_path: Path):
    cfg = _cfg(tmp_path)
    client = FakePapiClient(fail_next_unknown=True, unknown_actually_accepted=True)
    executor = BinanceKzExecutor(cfg, client, BinanceKzLedger(tmp_path / "ledger"))
    result = executor.apply_command(_open_cmd())
    assert result["status"] == "FILLED"
    assert len(client.posts) == 3
    assert client.gets


def test_kill_flag_and_paper_isolation(tmp_path: Path):
    cfg = _cfg(tmp_path)
    paper_fills = cfg.paper_books_root / "fills.jsonl"
    client = FakePapiClient()
    executor = BinanceKzExecutor(cfg, client, BinanceKzLedger(cfg.books_root))
    assert executor.apply_command(_open_cmd())["status"] == "FILLED"
    assert not paper_fills.exists()
    assert (cfg.books_root / "fills.jsonl").is_file()
    cfg.kill_flag_path.write_text("stop\n")
    killed = executor.apply_command(_open_cmd(command_id="cmd-open-2", episode="M15:9"))
    assert killed["status"] == "KILLED"
    assert abs(client.positions.get("BTCUSDT", 0.0)) < 1e-12


def test_consumer_m15_only(tmp_path: Path):
    cfg = _cfg(tmp_path)
    memory = tmp_path / "commands.parquet"
    paths = CommandBusPaths(
        memory=memory,
        latest=tmp_path / "latest.json",
        manager_state=tmp_path / "state.json",
        portfolio_summary=tmp_path / "port.json",
    )
    bus = CommandBus(paths)

    def _row(command: dict) -> dict:
        row = {col: None for col in COMMAND_COLUMNS}
        row.update(command)
        row["schema_version"] = "timeframe_manager_command_v1"
        return row

    bus.append([_row(_open_cmd(tf="M30", command_id="m30-1")), _row(_open_cmd())])
    executor = BinanceKzExecutor(cfg, FakePapiClient(), BinanceKzLedger(tmp_path / "ledger"))
    consumer = BinanceKzCommandConsumer(
        executor,
        checkpoint_path=tmp_path / "cursor.json",
        consume_after=None,
        bus=bus,
    )
    actions = consumer.poll()
    assert any(a.get("status") == "FILLED" for a in actions)
    assert all(a.get("timeframe") != "M30" or a.get("status") != "FILLED" for a in actions)
    assert executor.ledger.open_positions()["M15"]["side"] == "LONG"
    again = consumer.poll()
    assert again == []


def test_guard_passes_unarmed_and_fails_armed_without_keys(tmp_path: Path):
    ok = evaluate_start(repo_root=ROOT, environ={}, contract_path=tmp_path / "contract.json")
    assert ok["status"] == "PASSED"
    assert ok["live_armed"] is False
    raw = json.loads((ROOT / "config" / "binance_kz_live.json").read_text())
    raw["real_execution_enabled"] = True
    path = tmp_path / "armed.json"
    path.write_text(json.dumps(raw))
    failed = evaluate_start(config_path=path, repo_root=ROOT, environ={ENV_LIVE_ENABLED: "true"})
    assert failed["status"] == "FAILED"
    assert failed["reason"] == "missing_api_key"
