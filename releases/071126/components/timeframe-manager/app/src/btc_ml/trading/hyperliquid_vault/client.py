"""Vault exchange adapter. Live SDK is optional; tests use FakeVaultClient."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .constants import TESTNET_API_URL
from .orders import parse_order_result


class VaultExchange(Protocol):
    def all_mids(self) -> dict[str, str]: ...
    def meta(self) -> dict[str, Any]: ...
    def user_state(self, address: str) -> dict[str, Any]: ...
    def open_orders(self, address: str) -> list[dict[str, Any]]: ...
    def update_leverage(self, coin: str, leverage: int, is_cross: bool) -> dict[str, Any]: ...
    def place_order(self, coin: str, order: dict[str, Any]) -> dict[str, Any]: ...
    def cancel(self, coin: str, oid: int) -> dict[str, Any]: ...
    def cancel_all(self, address: str, coin: str) -> list[dict[str, Any]]: ...
    def create_vault(self, name: str, description: str, initial_usd: float) -> dict[str, Any]: ...
    def approve_agent(self, name: str) -> dict[str, Any]: ...


def post_info(api_url: str, payload: dict[str, Any], *, timeout: float = 15.0) -> Any:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/info",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"info HTTP {exc.code}: {detail}") from exc


def sz_decimals_for(meta: dict[str, Any], coin: str) -> int:
    for asset in meta.get("universe") or []:
        if str(asset.get("name") or "").upper() == coin.upper():
            return int(asset.get("szDecimals") or 5)
    return 5


UNIFIED_MODES = frozenset({"unifiedAccount", "portfolioMargin"})


def spot_usdc_total(spot_state: dict[str, Any] | None) -> float:
    for row in (spot_state or {}).get("balances") or []:
        if str(row.get("coin") or "").upper() == "USDC":
            return float(row.get("total") or 0.0)
    return 0.0


def with_unified_equity(
    perp_state: dict[str, Any],
    *,
    spot_state: dict[str, Any],
    abstraction: str,
) -> dict[str, Any]:
    """Unified/portfolio accounts keep USDC in spot; perp accountValue is not meaningful."""
    state = dict(perp_state)
    state["userAbstraction"] = abstraction
    state["spotState"] = spot_state
    if str(abstraction) in UNIFIED_MODES:
        usdc = spot_usdc_total(spot_state)
        for key in ("marginSummary", "crossMarginSummary"):
            summary = dict(state.get(key) or {})
            summary["accountValue"] = str(usdc)
            state[key] = summary
    return state


def account_value_usd(state: dict[str, Any]) -> float:
    summary = state.get("marginSummary") or state.get("crossMarginSummary") or {}
    return float(summary.get("accountValue") or 0.0)


def margin_used_usd(state: dict[str, Any]) -> float:
    summary = state.get("marginSummary") or state.get("crossMarginSummary") or {}
    return float(summary.get("totalMarginUsed") or 0.0)


def signed_position_size(state: dict[str, Any], coin: str) -> float:
    for row in state.get("assetPositions") or []:
        pos = row.get("position") or {}
        if str(pos.get("coin") or "").upper() == coin.upper():
            return float(pos.get("szi") or 0.0)
    return 0.0


def mid_px(mids: dict[str, str], coin: str) -> float:
    raw = mids.get(coin) or mids.get(coin.upper()) or mids.get(coin.capitalize())
    if raw is None:
        raise RuntimeError(f"missing mid for {coin}")
    return float(raw)


@dataclass
class FakeVaultClient:
    """In-memory Hyperliquid stand-in. Never touches the network."""

    mids: dict[str, str] = field(default_factory=lambda: {"BTC": "100000.0"})
    account_value: float = 500.0
    margin_used: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)
    resting: list[dict[str, Any]] = field(default_factory=list)
    placed: list[dict[str, Any]] = field(default_factory=list)
    cancels: list[int] = field(default_factory=list)
    leverage_calls: list[dict[str, Any]] = field(default_factory=list)
    created_vaults: list[dict[str, Any]] = field(default_factory=list)
    approved_agents: list[str] = field(default_factory=list)
    fail_orders: bool = False
    fail_triggers: bool = False
    fail_error: str = "insufficient margin"
    next_oid: int = 1
    sz_decimals: int = 5
    vault_address: str = "0x1111111111111111111111111111111111111111"

    def all_mids(self) -> dict[str, str]:
        return dict(self.mids)

    def meta(self) -> dict[str, Any]:
        return {"universe": [{"name": "BTC", "szDecimals": self.sz_decimals}]}

    def user_state(self, address: str) -> dict[str, Any]:
        _ = address
        positions = []
        for coin, szi in self.positions.items():
            if abs(szi) > 0:
                positions.append({"position": {"coin": coin, "szi": str(szi), "unrealizedPnl": "0"}})
        return {
            "marginSummary": {
                "accountValue": str(self.account_value),
                "totalMarginUsed": str(self.margin_used),
            },
            "assetPositions": positions,
        }

    def open_orders(self, address: str) -> list[dict[str, Any]]:
        _ = address
        return list(self.resting)

    def update_leverage(self, coin: str, leverage: int, is_cross: bool) -> dict[str, Any]:
        self.leverage_calls.append({"coin": coin, "leverage": leverage, "is_cross": is_cross})
        return {"status": "ok"}

    def place_order(self, coin: str, order: dict[str, Any]) -> dict[str, Any]:
        payload = {"coin": coin, **order}
        self.placed.append(payload)
        if self.fail_orders:
            return {"status": "ok", "response": {"data": {"statuses": [{"error": self.fail_error}]}}}
        oid = self.next_oid
        self.next_oid += 1
        is_trigger = isinstance(order.get("order_type"), dict) and "trigger" in order["order_type"]
        if is_trigger:
            if self.fail_triggers:
                raise RuntimeError("trigger order rejected")
            self.resting.append({"oid": oid, "coin": coin, **order})
            return {"status": "ok", "response": {"data": {"statuses": [{"resting": {"oid": oid}}]}}}
        signed = float(order["sz"]) if order["is_buy"] else -float(order["sz"])
        current = self.positions.get(coin, 0.0)
        if order.get("reduce_only"):
            if current == 0:
                return {"status": "ok", "response": {"data": {"statuses": [{"error": "no position"}]}}}
            if current > 0:
                signed = -min(abs(signed), current)
            else:
                signed = min(abs(signed), abs(current))
        self.positions[coin] = current + signed
        avg = float(self.mids.get(coin, "0"))
        filled_sz = abs(signed)
        return {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [{"filled": {"totalSz": str(filled_sz), "avgPx": str(avg), "oid": oid}}]
                }
            },
        }

    def cancel(self, coin: str, oid: int) -> dict[str, Any]:
        _ = coin
        self.cancels.append(int(oid))
        self.resting = [row for row in self.resting if int(row.get("oid") or 0) != int(oid)]
        return {"status": "ok"}

    def cancel_all(self, address: str, coin: str) -> list[dict[str, Any]]:
        out = []
        for row in list(self.resting):
            if str(row.get("coin") or coin) == coin:
                out.append(self.cancel(coin, int(row["oid"])))
        return out

    def create_vault(self, name: str, description: str, initial_usd: float) -> dict[str, Any]:
        rec = {"name": name, "description": description, "initial_usd": initial_usd, "address": self.vault_address}
        self.created_vaults.append(rec)
        return {"status": "ok", "response": {"data": self.vault_address}}

    def approve_agent(self, name: str) -> dict[str, Any]:
        self.approved_agents.append(name)
        return {"status": "ok", "agentAddress": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}


class SdkVaultClient:
    """Thin wrapper around hyperliquid-python-sdk Exchange + Info."""

    def __init__(
        self,
        *,
        api_url: str,
        vault_address: str | None,
        account_address: str | None,
        agent_key: str,
    ) -> None:
        try:
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
        except ImportError as exc:  # pragma: no cover - exercised when extra is missing
            raise RuntimeError(
                "hyperliquid-python-sdk and eth-account are required for live vault trading; "
                "install requirements-hl-vault.txt"
            ) from exc
        wallet = Account.from_key(agent_key)
        self._api_url = api_url
        self._info = Info(api_url, skip_ws=True)
        self._exchange = Exchange(wallet, api_url, vault_address=vault_address, account_address=account_address)
        self._vault_address = vault_address
        self._account_address = account_address

    def _query_address(self) -> str:
        addr = self._vault_address or self._account_address
        if not addr:
            raise RuntimeError("vault_address or account_address required for queries")
        return addr

    def all_mids(self) -> dict[str, str]:
        return dict(self._info.all_mids())

    def meta(self) -> dict[str, Any]:
        return dict(self._info.meta())

    def user_state(self, address: str) -> dict[str, Any]:
        state = dict(self._info.user_state(address))
        try:
            abstraction = post_info(self._api_url, {"type": "userAbstraction", "user": address})
        except Exception:
            return state
        if not isinstance(abstraction, str) or abstraction not in UNIFIED_MODES:
            return state
        spot = dict(self._info.spot_user_state(address))
        return with_unified_equity(state, spot_state=spot, abstraction=abstraction)

    def open_orders(self, address: str) -> list[dict[str, Any]]:
        return list(self._info.open_orders(address))

    def update_leverage(self, coin: str, leverage: int, is_cross: bool) -> dict[str, Any]:
        return self._exchange.update_leverage(leverage, coin, is_cross)

    def place_order(self, coin: str, order: dict[str, Any]) -> dict[str, Any]:
        return self._exchange.order(
            coin,
            bool(order["is_buy"]),
            float(order["sz"]),
            float(order["limit_px"]),
            order["order_type"],
            reduce_only=bool(order.get("reduce_only")),
        )

    def cancel(self, coin: str, oid: int) -> dict[str, Any]:
        return self._exchange.cancel(coin, int(oid))

    def cancel_all(self, address: str, coin: str) -> list[dict[str, Any]]:
        out = []
        for row in self.open_orders(address):
            if str(row.get("coin") or "") == coin:
                out.append(self.cancel(coin, int(row["oid"])))
        return out

    def create_vault(self, name: str, description: str, initial_usd: float) -> dict[str, Any]:
        from hyperliquid.utils.signing import get_timestamp_ms, sign_l1_action

        timestamp = get_timestamp_ms()
        action = {
            "type": "createVault",
            "name": name,
            "description": description,
            "initialUsd": int(round(float(initial_usd) * 1_000_000)),
            "nonce": timestamp,
        }
        is_mainnet = not str(getattr(self._exchange, "base_url", TESTNET_API_URL)).endswith("testnet.xyz")
        signature = sign_l1_action(self._exchange.wallet, action, None, timestamp, None, is_mainnet)
        return self._exchange._post_action(action, signature, timestamp)

    def approve_agent(self, name: str) -> dict[str, Any]:
        return self._exchange.approve_agent(name)


def parse_fill_or_raise(payload: Any) -> tuple[float, float, int | None]:
    parsed = parse_order_result(payload)
    if not parsed.ok:
        raise RuntimeError(parsed.error or "order rejected")
    if not parsed.filled or parsed.avg_px is None or parsed.total_sz is None:
        raise RuntimeError("expected IOC fill, got resting or empty")
    return parsed.avg_px, parsed.total_sz, parsed.oid
