"""Map S4.1 OPEN/CLOSE into Hyperliquid vault IOC + native TP/SL."""

from __future__ import annotations

from typing import Any

from .client import (
    VaultExchange,
    account_value_usd,
    mid_px,
    parse_fill_or_raise,
    signed_position_size,
    sz_decimals_for,
)
from .config import HlVaultConfig
from .kill_switch import evaluate_kill, kill_flag_present, kill_record
from .ledger import VaultLedger, utc_now
from .orders import (
    aggressive_limit_px,
    ioc_limit_order,
    parse_order_result,
    protective_side,
    round_px_to_tick,
    trigger_tpsl_order,
)
from .sizing import resolve_vault_sizing


class VaultExecutor:
    def __init__(self, cfg: HlVaultConfig, client: VaultExchange, ledger: VaultLedger) -> None:
        self.cfg = cfg
        self.client = client
        self.ledger = ledger
        self.consecutive_errors = 0
        self.health: dict[str, Any] = {"ok": True, "updated_at": utc_now()}

    def query_address(self) -> str:
        addr = self.cfg.vault_address or self.cfg.account_address
        if not addr:
            raise RuntimeError("vault_address or account_address required")
        return addr

    def _state(self) -> dict[str, Any]:
        return self.ledger.load_state()

    def _save(self, state: dict[str, Any]) -> None:
        self.ledger.save_state(state)

    def _trip(self, state: dict[str, Any], reason: str, *, flatten: bool) -> dict[str, Any]:
        state["kill"] = kill_record(reason)
        self._save(state)
        self.ledger.append("events", {"kind": "KILL", "reason": reason})
        flatten_result = None
        if flatten:
            flatten_result = self.flatten(reason=reason)
        self.health = {"ok": False, "kill": reason, "updated_at": utc_now()}
        return {"status": "KILLED", "reason": reason, "flatten": flatten_result}

    def maybe_kill(self, user_state: dict[str, Any] | None = None) -> dict[str, Any] | None:
        state = self._state()
        already = bool((state.get("kill") or {}).get("tripped"))
        decision = evaluate_kill(
            cfg=self.cfg,
            user_state=user_state,
            consecutive_errors=self.consecutive_errors,
            already_tripped=already,
            flag_present=kill_flag_present(self.cfg.kill_flag_path),
        )
        if decision.tripped and not already:
            return self._trip(state, decision.reason or "KILL", flatten=decision.flatten)
        if already:
            return {"status": "KILLED", "reason": (state.get("kill") or {}).get("reason")}
        return None

    def flatten(self, *, reason: str) -> dict[str, Any]:
        address = self.query_address()
        cancels = self.client.cancel_all(address, self.cfg.coin)
        user_state = self.client.user_state(address)
        szi = signed_position_size(user_state, self.cfg.coin)
        close = None
        if abs(szi) > 0:
            is_buy = szi < 0
            mid = mid_px(self.client.all_mids(), self.cfg.coin)
            px = aggressive_limit_px(
                side="LONG" if is_buy else "SHORT",
                mid=mid,
                ioc_slippage_bps=self.cfg.ioc_slippage_bps,
            )
            close = self.client.place_order(
                self.cfg.coin,
                ioc_limit_order(is_buy=is_buy, size=abs(szi), limit_px=px, reduce_only=True),
            )
        state = self._state()
        for tf, pos in list((state.get("positions") or {}).items()):
            pos["status"] = "FLAT"
            pos["flatten_reason"] = reason
            state["positions"][tf] = pos
        self._save(state)
        self.ledger.append("events", {"kind": "FLATTEN", "reason": reason, "szi_before": szi})
        return {"cancels": cancels, "close": close, "szi_before": szi}

    def _ensure_leverage(self, state: dict[str, Any]) -> None:
        if state.get("leverage_set"):
            return
        self.client.update_leverage(self.cfg.coin, self.cfg.leverage, self.cfg.is_cross)
        state["leverage_set"] = True
        self._save(state)

    def apply_command(self, command: dict[str, Any]) -> dict[str, Any]:
        intent = str(command.get("intent") or "").upper()
        tf = str(command.get("timeframe") or "").upper()
        command_id = str(command.get("command_id") or "").strip()
        if tf not in self.cfg.timeframes or not command_id:
            return {"status": "REJECTED_BAD_COMMAND", "command_id": command_id, "timeframe": tf}
        try:
            user_state = self.client.user_state(self.query_address())
        except Exception as exc:  # noqa: BLE001
            self.consecutive_errors += 1
            killed = self.maybe_kill()
            return killed or {"status": "EXCHANGE_ERROR", "error": str(exc), "command_id": command_id}
        killed = self.maybe_kill(user_state)
        if killed is not None:
            if intent == "CLOSE":
                return {**killed, "note": "already_killed"}
            return killed
        self.consecutive_errors = 0
        if intent in {"OPEN_LONG", "OPEN_SHORT"} and command.get("action_allowed"):
            return self._open(command, user_state)
        if intent == "CLOSE" and command.get("action_allowed"):
            return self._close(command)
        return {"status": "IGNORED", "intent": intent, "command_id": command_id, "timeframe": tf}

    def _open(self, command: dict[str, Any], user_state: dict[str, Any]) -> dict[str, Any]:
        tf = str(command["timeframe"]).upper()
        command_id = str(command["command_id"])
        state = self._state()
        existing = (state.get("positions") or {}).get(tf) or {}
        if str(existing.get("status") or "") == "OPEN":
            return {"status": "ENTRY_BLOCKED_ACTIVE_POSITION", "command_id": command_id, "timeframe": tf}
        if abs(signed_position_size(user_state, self.cfg.coin)) > 1e-12:
            return {"status": "ENTRY_BLOCKED_EXCHANGE_POSITION", "command_id": command_id, "timeframe": tf}
        try:
            mids = self.client.all_mids()
            mid = mid_px(mids, self.cfg.coin)
            meta = self.client.meta()
        except Exception as exc:  # noqa: BLE001
            self.consecutive_errors += 1
            return {"status": "EXCHANGE_ERROR", "error": str(exc), "command_id": command_id}
        side = "LONG" if str(command["intent"]).upper() == "OPEN_LONG" else "SHORT"
        equity = account_value_usd(user_state)
        sizing = resolve_vault_sizing(
            side=side,
            entry_price=mid,
            vault_equity_usd=equity,
            max_risk_per_trade_pct=self.cfg.max_risk_per_trade_pct,
            max_risk_per_trade_usd=self.cfg.max_risk_per_trade_usd,
            stop_loss_bps=self.cfg.stop_loss_bps,
            take_profit_bps=self.cfg.take_profit_bps,
            hard_cap_order_btc=self.cfg.hard_cap_order_btc,
            sz_decimals=sz_decimals_for(meta, self.cfg.coin),
        )
        if not sizing.ok or sizing.quantity is None:
            return {"status": sizing.block_reason, "command_id": command_id, "timeframe": tf}
        self._ensure_leverage(state)
        limit_px = aggressive_limit_px(side=side, mid=mid, ioc_slippage_bps=self.cfg.ioc_slippage_bps)
        order = ioc_limit_order(is_buy=side == "LONG", size=sizing.quantity, limit_px=limit_px)
        try:
            raw = self.client.place_order(self.cfg.coin, order)
            avg_px, filled_sz, oid = parse_fill_or_raise(raw)
        except Exception as exc:  # noqa: BLE001
            self.consecutive_errors += 1
            self.ledger.append(
                "orders",
                {"command_id": command_id, "timeframe": tf, "status": "REJECTED", "error": str(exc), "order": order},
            )
            killed = self.maybe_kill()
            return killed or {"status": "ORDER_REJECTED", "error": str(exc), "command_id": command_id}
        self.consecutive_errors = 0
        pos = {
            "status": "OPEN",
            "timeframe": tf,
            "side": side,
            "quantity": filled_sz,
            "entry_price": avg_px,
            "stop_loss_price": sizing.stop_price,
            "take_profit_price": sizing.take_price,
            "entry_oid": oid,
            "sl_oid": None,
            "tp_oid": None,
            "manager_command_id": command_id,
            "vault_equity_usd": equity,
            "mid_at_entry": mid,
        }
        state.setdefault("positions", {})[tf] = pos
        self._save(state)
        self.ledger.append("commands", {"command_id": command_id, "intent": command.get("intent"), "timeframe": tf})
        self.ledger.append("orders", {"command_id": command_id, "timeframe": tf, "status": "FILLED", "oid": oid, **order})
        fill = self.ledger.append(
            "fills",
            {
                "manager_command_id": command_id,
                "timeframe": tf,
                "side": side,
                "action": "ENTRY",
                "quantity": filled_sz,
                "avg_px": avg_px,
                "hl_mid": mid,
                "oid": oid,
                "notional_usd": filled_sz * avg_px,
                "risk_usd": sizing.risk_usd,
            },
        )
        sl_oid = None
        tp_oid = None
        try:
            sl = trigger_tpsl_order(
                is_buy=protective_side(side) == "LONG",
                size=filled_sz,
                trigger_px=round_px_to_tick(float(sizing.stop_price)),
                tpsl="sl",
            )
            tp = trigger_tpsl_order(
                is_buy=protective_side(side) == "LONG",
                size=filled_sz,
                trigger_px=round_px_to_tick(float(sizing.take_price)),
                tpsl="tp",
            )
            sl_res = parse_order_result(self.client.place_order(self.cfg.coin, sl))
            tp_res = parse_order_result(self.client.place_order(self.cfg.coin, tp))
            sl_oid = sl_res.oid
            tp_oid = tp_res.oid
            if not sl_res.ok or not tp_res.ok:
                pos["tpsl_error"] = sl_res.error or tp_res.error
                self.ledger.append("events", {"kind": "TPSL_FAILED", "command_id": command_id, "error": pos["tpsl_error"]})
        except Exception as exc:  # noqa: BLE001
            pos["tpsl_error"] = str(exc)
            self.ledger.append("events", {"kind": "TPSL_FAILED", "command_id": command_id, "error": str(exc)})
        pos["sl_oid"] = sl_oid
        pos["tp_oid"] = tp_oid
        state["positions"][tf] = pos
        self._save(state)
        self.ledger.append("positions", dict(pos))
        self.health = {"ok": True, "last_fill": fill, "updated_at": utc_now()}
        return {"status": "FILLED", "fill": fill, "sl": sl_oid, "tp": tp_oid}

    def _close(self, command: dict[str, Any]) -> dict[str, Any]:
        tf = str(command["timeframe"]).upper()
        command_id = str(command["command_id"])
        state = self._state()
        pos = (state.get("positions") or {}).get(tf) or {}
        if str(pos.get("status") or "") != "OPEN":
            return {"status": "CLOSE_NO_POSITION", "command_id": command_id, "timeframe": tf}
        for oid_key in ("sl_oid", "tp_oid"):
            oid = pos.get(oid_key)
            if oid is not None:
                try:
                    self.client.cancel(self.cfg.coin, int(oid))
                except Exception:  # noqa: BLE001
                    pass
        side = str(pos["side"]).upper()
        qty = float(pos["quantity"])
        close_side = protective_side(side)
        mid = mid_px(self.client.all_mids(), self.cfg.coin)
        limit_px = aggressive_limit_px(side=close_side, mid=mid, ioc_slippage_bps=self.cfg.ioc_slippage_bps)
        order = ioc_limit_order(is_buy=close_side == "LONG", size=qty, limit_px=limit_px, reduce_only=True)
        try:
            raw = self.client.place_order(self.cfg.coin, order)
            avg_px, filled_sz, oid = parse_fill_or_raise(raw)
        except Exception as exc:  # noqa: BLE001
            self.consecutive_errors += 1
            killed = self.maybe_kill()
            return killed or {"status": "ORDER_REJECTED", "error": str(exc), "command_id": command_id}
        pos["status"] = "CLOSED"
        pos["exit_price"] = avg_px
        pos["exit_oid"] = oid
        pos["exit_command_id"] = command_id
        state["positions"][tf] = pos
        self._save(state)
        fill = self.ledger.append(
            "fills",
            {
                "manager_command_id": command_id,
                "entry_manager_command_id": pos.get("manager_command_id"),
                "timeframe": tf,
                "side": side,
                "action": "EXIT",
                "quantity": filled_sz,
                "avg_px": avg_px,
                "hl_mid": mid,
                "oid": oid,
            },
        )
        self.ledger.append("positions", dict(pos))
        return {"status": "CLOSED", "fill": fill}
