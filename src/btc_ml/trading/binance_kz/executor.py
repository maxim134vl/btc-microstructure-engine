"""S4.1 OPEN/CLOSE → PAPI UM BTCUSDT. Isolated from LIVE1B paper books."""

from __future__ import annotations

from typing import Any

from .client import OrderUnknownError, PortfolioMarginExchange
from .config import BinanceKzConfig
from .constants import ALLOWED_TIMEFRAMES, LEVERAGE, SYMBOL
from .kill_switch import (
    can_open,
    evaluate_kill,
    kill_flag_present,
    kill_record,
    parse_equity_usd,
    parse_unimmr,
)
from .ledger import BinanceKzLedger, utc_now
from .orders import (
    aggressive_limit_price,
    client_order_id_for,
    ioc_limit_order,
    stop_market_close,
    take_profit_market_close,
)
from .reconcile import place_or_reconcile
from .sizing import resolve_live_sizing


def _bbo_mid(ticker: dict[str, Any]) -> float:
    bid = float(ticker.get("bidPrice") or 0.0)
    ask = float(ticker.get("askPrice") or 0.0)
    if bid <= 0 or ask <= 0:
        raise RuntimeError("invalid BBO")
    return (bid + ask) / 2.0


def _signed_qty(rows: list[dict[str, Any]], symbol: str) -> float:
    total = 0.0
    for row in rows:
        if str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        total += float(row.get("positionAmt") or 0.0)
    return total


class BinanceKzExecutor:
    def __init__(
        self,
        cfg: BinanceKzConfig,
        client: PortfolioMarginExchange,
        ledger: BinanceKzLedger,
        *,
        catboost_mult: float = 1.0,
    ) -> None:
        self.cfg = cfg
        self.client = client
        self.ledger = ledger
        self.catboost_mult = float(catboost_mult)
        self.consecutive_errors = 0
        self.health: dict[str, Any] = {"ok": True, "updated_at": utc_now()}
        self.ip_banned = False

    def _state(self) -> dict[str, Any]:
        return self.ledger.load_state()

    def _save(self, state: dict[str, Any]) -> None:
        self.ledger.save_state(state)

    def _trip(self, state: dict[str, Any], reason: str, *, flatten: bool) -> dict[str, Any]:
        state["kill"] = kill_record(reason)
        self._save(state)
        self.ledger.append("events", {"kind": "KILL", "reason": reason})
        flatten_result = self.flatten(reason=reason) if flatten else None
        self.health = {"ok": False, "kill": reason, "updated_at": utc_now()}
        return {"status": "KILLED", "reason": reason, "flatten": flatten_result}

    def maybe_kill(self, account: dict[str, Any] | None = None) -> dict[str, Any] | None:
        state = self._state()
        already = bool((state.get("kill") or {}).get("tripped"))
        venue_lev = None
        try:
            risk = self.client.um_position_risk(self.cfg.symbol)
            if risk:
                venue_lev = int(float(risk[0].get("leverage") or 0)) or None
        except Exception:  # noqa: BLE001
            venue_lev = None
        decision = evaluate_kill(
            consecutive_errors=self.consecutive_errors,
            max_consecutive_errors=self.cfg.max_consecutive_exchange_errors,
            already_tripped=already,
            flag_present=kill_flag_present(self.cfg.kill_flag_path),
            account=account,
            kill_unimmr=self.cfg.kill_unimmr,
            ip_banned=self.ip_banned,
            auto_borrow=bool((account or {}).get("autoBorrow")),
            venue_leverage=venue_lev,
            required_leverage=LEVERAGE,
        )
        if decision.tripped and not already:
            return self._trip(state, decision.reason or "KILL", flatten=decision.flatten)
        if already:
            return {"status": "KILLED", "reason": (state.get("kill") or {}).get("reason")}
        return None

    def flatten(self, *, reason: str) -> dict[str, Any]:
        cancels = self.client.cancel_all_um_orders(self.cfg.symbol)
        risk = self.client.um_position_risk(self.cfg.symbol)
        qty = _signed_qty(risk, self.cfg.symbol)
        close = None
        if abs(qty) > 0:
            side = "SHORT" if qty > 0 else "LONG"
            ticker = self.client.book_ticker(self.cfg.symbol)
            mid = _bbo_mid(ticker)
            px = aggressive_limit_price(
                side=side,
                mid=mid,
                ioc_slippage_bps=self.cfg.ioc_slippage_bps,
                tick_size=self.cfg.tick_size,
            )
            params = ioc_limit_order(
                symbol=self.cfg.symbol,
                side=side,
                quantity=abs(qty),
                price=px,
                client_order_id=client_order_id_for(f"flatten:{reason}:{utc_now()}"),
                reduce_only=True,
            )
            close = place_or_reconcile(self.client, params)
        state = self._state()
        for tf, pos in list((state.get("positions") or {}).items()):
            pos["status"] = "FLAT"
            pos["flatten_reason"] = reason
            state["positions"][tf] = pos
        self._save(state)
        self.ledger.append("events", {"kind": "FLATTEN", "reason": reason, "qty_before": qty})
        return {"cancels": cancels, "close": close, "qty_before": qty}

    def apply_command(self, command: dict[str, Any]) -> dict[str, Any]:
        intent = str(command.get("intent") or "").upper()
        tf = str(command.get("timeframe") or "").upper()
        command_id = str(command.get("command_id") or "").strip()
        if tf not in ALLOWED_TIMEFRAMES or tf not in self.cfg.timeframes or not command_id:
            return {"status": "REJECTED_BAD_COMMAND", "command_id": command_id, "timeframe": tf}
        try:
            account = self.client.account()
        except Exception as exc:  # noqa: BLE001
            self.consecutive_errors += 1
            killed = self.maybe_kill()
            return killed or {"status": "EXCHANGE_ERROR", "error": str(exc), "command_id": command_id}
        killed = self.maybe_kill(account)
        if killed is not None:
            if intent == "CLOSE":
                return {**killed, "note": "already_killed"}
            return killed
        self.consecutive_errors = 0
        if intent in {"OPEN_LONG", "OPEN_SHORT"} and command.get("action_allowed"):
            return self._open(command, account)
        if intent == "CLOSE" and command.get("action_allowed"):
            return self._close(command)
        return {"status": "IGNORED", "intent": intent, "command_id": command_id, "timeframe": tf}

    def _ensure_leverage(self, state: dict[str, Any]) -> None:
        self.client.set_um_leverage(self.cfg.symbol, LEVERAGE)
        state["leverage_set"] = True
        self._save(state)

    def _open(self, command: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
        tf = str(command["timeframe"]).upper()
        command_id = str(command["command_id"])
        state = self._state()
        existing = (state.get("positions") or {}).get(tf) or {}
        if str(existing.get("status") or "") == "OPEN":
            return {"status": "ENTRY_BLOCKED_ACTIVE_POSITION", "command_id": command_id, "timeframe": tf}
        last_ep = str(state.get("last_entry_episode_id") or "")
        episode = str(command.get("lifecycle_episode_id") or command.get("canonical_episode_id") or "")
        if episode and last_ep and episode == last_ep:
            return {"status": "ENTRY_BLOCKED_EPISODE_ALREADY_TRADED", "command_id": command_id, "timeframe": tf}
        uni = parse_unimmr(account)
        allowed, reason = can_open(unimmr=uni, min_unimmr_open=self.cfg.min_unimmr_open)
        if not allowed:
            return {"status": reason, "command_id": command_id, "timeframe": tf, "uniMMR": uni}
        risk_rows = self.client.um_position_risk(self.cfg.symbol)
        venue_qty = _signed_qty(risk_rows, self.cfg.symbol)
        if abs(venue_qty) > 0:
            return {"status": "ENTRY_BLOCKED_INVENTORY_SURPRISE", "command_id": command_id, "qty": venue_qty}
        try:
            ticker = self.client.book_ticker(self.cfg.symbol)
            mid = _bbo_mid(ticker)
        except Exception as exc:  # noqa: BLE001
            self.consecutive_errors += 1
            return {"status": "EXCHANGE_ERROR", "error": str(exc), "command_id": command_id}
        side = "LONG" if str(command["intent"]).upper() == "OPEN_LONG" else "SHORT"
        equity = parse_equity_usd(account)
        sizing = resolve_live_sizing(
            side=side,
            entry_price=mid,
            equity_usd=equity,
            stop_loss_bps=self.cfg.stop_loss_bps,
            take_profit_bps=self.cfg.take_profit_bps,
            leverage=self.cfg.leverage,
            catboost_mult=self.catboost_mult,
            qty_step=self.cfg.qty_step,
            risk_pct=self.cfg.max_risk_per_trade_pct,
        )
        if not sizing.ok or sizing.quantity is None:
            return {"status": sizing.block_reason, "command_id": command_id, "timeframe": tf}
        self._ensure_leverage(state)
        limit_px = aggressive_limit_price(
            side=side,
            mid=mid,
            ioc_slippage_bps=self.cfg.ioc_slippage_bps,
            tick_size=self.cfg.tick_size,
        )
        cid = client_order_id_for(command_id)
        order = ioc_limit_order(
            symbol=self.cfg.symbol,
            side=side,
            quantity=sizing.quantity,
            price=limit_px,
            client_order_id=cid,
        )
        try:
            raw = place_or_reconcile(self.client, order)
        except (OrderUnknownError, Exception) as exc:  # noqa: BLE001
            self.consecutive_errors += 1
            self.ledger.append("orders", {"command_id": command_id, "status": "REJECTED", "error": str(exc), "order": order})
            killed = self.maybe_kill(account)
            return killed or {"status": "ORDER_REJECTED", "error": str(exc), "command_id": command_id}
        filled_qty = float(raw.get("executedQty") or 0.0)
        avg_px = float(raw.get("avgPrice") or 0.0)
        if filled_qty <= 0 or avg_px <= 0:
            return {"status": "ENTRY_BLOCKED_IOC_NO_FILL", "command_id": command_id, "raw": raw}
        sl = stop_market_close(
            symbol=self.cfg.symbol,
            position_side=side,
            stop_price=float(sizing.stop_price),
            client_order_id=client_order_id_for(command_id + ":sl"),
        )
        tp = take_profit_market_close(
            symbol=self.cfg.symbol,
            position_side=side,
            take_price=float(sizing.take_price),
            client_order_id=client_order_id_for(command_id + ":tp"),
        )
        sl_raw = place_or_reconcile(self.client, sl)
        tp_raw = place_or_reconcile(self.client, tp)
        pos = {
            "status": "OPEN",
            "timeframe": tf,
            "side": side,
            "quantity": filled_qty,
            "entry_price": avg_px,
            "stop_loss_price": sizing.stop_price,
            "take_profit_price": sizing.take_price,
            "entry_client_order_id": cid,
            "sl_client_order_id": sl.get("newClientOrderId"),
            "tp_client_order_id": tp.get("newClientOrderId"),
            "manager_command_id": command_id,
            "lifecycle_episode_id": episode,
            "equity_usd": equity,
            "uniMMR": uni,
            "mid_at_entry": mid,
        }
        state.setdefault("positions", {})[tf] = pos
        if episode:
            state["last_entry_episode_id"] = episode
        self._save(state)
        self.ledger.append("commands", {"command_id": command_id, "intent": command.get("intent"), "timeframe": tf})
        self.ledger.append("orders", {"command_id": command_id, "status": "FILLED", **order})
        fill = self.ledger.append(
            "fills",
            {
                "manager_command_id": command_id,
                "timeframe": tf,
                "side": side,
                "action": "ENTRY",
                "quantity": filled_qty,
                "avg_px": avg_px,
                "notional_usd": filled_qty * avg_px,
                "risk_usd": sizing.risk_usd,
            },
        )
        self.ledger.append("positions", dict(pos))
        self.health = {"ok": True, "last_fill": fill, "updated_at": utc_now()}
        return {"status": "FILLED", "fill": fill, "sl": sl_raw.get("orderId"), "tp": tp_raw.get("orderId")}

    def _close(self, command: dict[str, Any]) -> dict[str, Any]:
        tf = str(command["timeframe"]).upper()
        command_id = str(command["command_id"])
        state = self._state()
        pos = (state.get("positions") or {}).get(tf) or {}
        if str(pos.get("status") or "") != "OPEN":
            return {"status": "CLOSE_NO_POSITION", "command_id": command_id, "timeframe": tf}
        for key in ("sl_client_order_id", "tp_client_order_id"):
            cid = pos.get(key)
            if cid:
                try:
                    self.client.cancel_um_order(orig_client_order_id=str(cid), symbol=self.cfg.symbol)
                except Exception:  # noqa: BLE001
                    pass
        side = str(pos["side"]).upper()
        qty = float(pos["quantity"])
        close_side = "SHORT" if side == "LONG" else "LONG"
        ticker = self.client.book_ticker(self.cfg.symbol)
        mid = _bbo_mid(ticker)
        px = aggressive_limit_price(
            side=close_side,
            mid=mid,
            ioc_slippage_bps=self.cfg.ioc_slippage_bps,
            tick_size=self.cfg.tick_size,
        )
        order = ioc_limit_order(
            symbol=self.cfg.symbol,
            side=close_side,
            quantity=qty,
            price=px,
            client_order_id=client_order_id_for(command_id),
            reduce_only=True,
        )
        try:
            raw = place_or_reconcile(self.client, order)
            avg_px = float(raw.get("avgPrice") or 0.0)
            filled_sz = float(raw.get("executedQty") or 0.0)
        except Exception as exc:  # noqa: BLE001
            self.consecutive_errors += 1
            killed = self.maybe_kill()
            return killed or {"status": "ORDER_REJECTED", "error": str(exc), "command_id": command_id}
        pos["status"] = "CLOSED"
        pos["exit_price"] = avg_px
        pos["exit_command_id"] = command_id
        pos["exit_reason"] = command.get("exit_reason")
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
            },
        )
        self.ledger.append("positions", dict(pos))
        return {"status": "CLOSED", "fill": fill}
