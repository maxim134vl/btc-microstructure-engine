"""Intrabar paper execution engine: context events → causal BBO fills."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bbo import CausalBBOStore, fill_price_for, resolve_context_entry_price
from .books import EpochBooks
from .config import IntrabarPaperConfig
from .consumer import (
    ENTRY_EVENTS,
    EXIT_EVENTS,
    ContextEventConsumer,
    idempotency_key,
)
from .economics import closed_trade_economics, resolve_risk_sizing
from .entry_eligibility import replay_entry_block_reason, stale_entry_block_reason
from btc_ml.live.intrabar.context_event_freshness import entry_freshness_block_reason
from .epoch import PaperEpoch
from .sleeves import SleeveLedger


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _occurrence_timestamp(event: dict[str, Any], event_timestamp: str | None) -> str | None:
    """Context occurrence clock for provenance; never used as opened_at."""
    for key in (
        "context_occurrence_timestamp",
        "context_origin_timestamp",
        "original_context_timestamp",
    ):
        val = event.get(key)
        if val is not None and str(val).strip():
            return str(val)
    if event_timestamp is not None and str(event_timestamp).strip():
        return str(event_timestamp)
    return None


@dataclass
class OpenPosition:
    position_id: str
    timeframe: str
    side: str
    quantity: float
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    risk_amount_usd: float
    lifecycle_episode_id: str | None
    context_event_id: str
    entry_fill_id: str
    entry_command_id: str
    entry_monotonic_ns: int
    traded_episode_ids: set[str] = field(default_factory=set)


@dataclass
class PendingExit:
    timeframe: str
    reason: str
    context_event_id: str
    command_monotonic_ns: int
    trigger_type: str
    trigger_event_id: str
    trigger_timestamp: str | None
    trigger_price: float | None
    flip_to_side: str | None = None
    episode_id: str | None = None
    event: dict[str, Any] | None = None


class IntrabarPaperEngine:
    """Per-timeframe single-position paper engine with causal BBO fills."""

    def __init__(
        self,
        *,
        cfg: IntrabarPaperConfig,
        epoch: PaperEpoch,
        books: EpochBooks | None = None,
        consumer: ContextEventConsumer | None = None,
        activation_monotonic_ns: int | None = None,
    ) -> None:
        self.cfg = cfg
        self.epoch = epoch
        self.equity = float(epoch.initial_equity_usd)
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        epoch_root = cfg.books_root / epoch.paper_epoch_id
        self.epoch_root = epoch_root
        self.books = books or EpochBooks(epoch_root / "books", paper_epoch_id=epoch.paper_epoch_id)
        ck_path = epoch_root / "context_consumer_checkpoint.json"
        act_mono = activation_monotonic_ns
        if act_mono is None:
            act_mono = epoch.activated_at_monotonic_ns
        self.consumer = consumer or ContextEventConsumer(
            journal_root=cfg.context_journal_root,
            checkpoint_path=ck_path,
            paper_epoch_id=epoch.paper_epoch_id,
            activated_at_monotonic_ns=act_mono,
            activated_at_iso=epoch.activated_at,
        )
        self.bbo = CausalBBOStore()
        self.positions: dict[str, OpenPosition] = {}
        self.traded_episodes: set[str] = set()
        self.pending_exits: dict[str, PendingExit] = {}
        self.blocked_commands = 0
        self.last_command: dict[str, Any] | None = None
        self.last_fill: dict[str, Any] | None = None
        self.last_context_event: dict[str, Any] | None = None
        self.errors: list[str] = []
        self._command_seq = 0
        self.execution_market: Any | None = None
        self.health_path = epoch_root / "health.json"
        self.last_health_write_error: str | None = None
        self.trading_contract = self._load_trading_contract(epoch_root)
        self.sleeves = SleeveLedger.load(epoch_root)
        self.capital_model = str(
            ((self.trading_contract or {}).get("capital") or {}).get("capital_model")
            or ("PER_TIMEFRAME_REALIZED_EQUITY" if self.sleeves is not None else "SHARED_MASTER_REALIZED_EQUITY")
        )
        self._restore_open_positions()
        if self.sleeves is not None:
            self.sleeves.sync_open_from_positions(self.books.open_positions())
            master = self.sleeves.master_snapshot()
            self.equity = float(master["master_current_equity_usd"])
            self.realized_pnl = float(master["master_realized_net_pnl_usd"])

    @staticmethod
    def _load_trading_contract(epoch_root: Path) -> dict[str, Any] | None:
        path = Path(epoch_root) / "trading_contract.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(raw, dict) and isinstance(raw.get("trading_contract_manifest"), dict):
            return raw["trading_contract_manifest"]
        return raw if isinstance(raw, dict) else None

    def _uses_sleeves(self) -> bool:
        return self.sleeves is not None and self.capital_model == "PER_TIMEFRAME_REALIZED_EQUITY"

    def _restore_open_positions(self) -> None:
        for row in self.books.open_positions():
            tf = str(row["timeframe"])
            ep = row.get("lifecycle_episode_id")
            pos = OpenPosition(
                position_id=str(row["position_id"]),
                timeframe=tf,
                side=str(row["side"]).upper(),
                quantity=float(row["quantity"]),
                entry_price=float(row["entry_price"]),
                stop_loss_price=float(row["stop_loss_price"]),
                take_profit_price=float(row["take_profit_price"]),
                risk_amount_usd=float(row.get("risk_amount_usd") or self.cfg.max_risk_per_trade_usd),
                lifecycle_episode_id=str(ep) if ep else None,
                context_event_id=str(row.get("entry_context_event_id") or ""),
                entry_fill_id=str(row.get("entry_fill_id") or ""),
                entry_command_id=str(row.get("entry_command_id") or ""),
                entry_monotonic_ns=int(row.get("entry_monotonic_ns") or 0),
            )
            if ep:
                self.traded_episodes.add(str(ep))
                pos.traded_episode_ids.add(str(ep))
            self.positions[tf] = pos
        if self._uses_sleeves():
            # Sleeve ledger is the equity source of truth; only recover episode locks.
            for t in self.books.closed_trades():
                ep = t.get("lifecycle_episode_id")
                if ep:
                    self.traded_episodes.add(str(ep))
            return
        for t in self.books.closed_trades():
            self.realized_pnl += float(t.get("net_pnl_usd") or 0.0)
            ep = t.get("lifecycle_episode_id")
            if ep:
                self.traded_episodes.add(str(ep))
        self.equity = float(self.epoch.initial_equity_usd) + self.realized_pnl

    def execution_market_ready_for_entry(self) -> bool:
        if self.execution_market is None:
            return True
        return bool(self.execution_market.execution_market_ready_for_entry())

    def attach_execution_market(self, processor: Any) -> None:
        self.execution_market = processor

    def update_bbo_from_market(
        self,
        *,
        best_bid: float,
        best_ask: float,
        receive_monotonic_ns: int,
        receive_timestamp: str | None = None,
        book_update_id: str | None = None,
        source_event_id: str | None = None,
        market_provenance: dict[str, Any] | None = None,
    ) -> None:
        self.bbo.update_from_book_ticker(
            best_bid=best_bid,
            best_ask=best_ask,
            receive_monotonic_ns=receive_monotonic_ns,
            receive_timestamp=receive_timestamp,
            book_update_id=book_update_id,
            source_event_id=source_event_id,
            domain="local",
        )

    def update_from_trade(
        self,
        *,
        price: float,
        receive_monotonic_ns: int,
        receive_timestamp: str | None = None,
        source_event_id: str | None = None,
        market_provenance: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._check_tp_sl_on_market(
            trigger_monotonic_ns=receive_monotonic_ns,
            trigger_event_id=source_event_id or f"trade_{receive_monotonic_ns}",
            trigger_timestamp=receive_timestamp,
            trade_price=float(price),
            use_local_bbo=True,
            market_provenance=market_provenance,
        )

    def process_context_event(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Process one context journal event; returns list of actions taken."""
        actions: list[dict[str, Any]] = []
        self.last_context_event = {
            "context_event_id": event.get("context_event_id") or event.get("event_id"),
            "event_type": event.get("event_type") or event.get("type"),
            "timeframe": event.get("timeframe"),
            "side": event.get("side") or event.get("direction") or event.get("context_side"),
            "event_monotonic_ns": event.get("event_monotonic_ns"),
        }
        self.bbo.update_from_context_event(event)
        # Retry pending exits first (causal BBO may now be available)
        for tf in list(self.pending_exits.keys()):
            done = self._try_pending_exit(tf)
            if done:
                actions.extend(done if isinstance(done, list) else [done])

        etype = str(event.get("event_type") or event.get("type") or "").upper()
        tf = str(event.get("timeframe") or "").upper()
        if tf not in self.cfg.timeframes:
            return actions
        side = self._event_side(event)
        mono = int(event.get("event_monotonic_ns") or 0)
        eid = str(event.get("context_event_id") or event.get("event_id") or _new_id("cev"))
        episode = event.get("lifecycle_episode_id") or event.get("episode_id")

        if etype == "CONTEXT_FLIP":
            pos = self.positions.get(tf)
            if self._is_foreign_lifecycle_episode(episode, pos):
                return actions
            flip_from = self._context_to_side(
                event.get("from_side") or event.get("flip_from") or event.get("previous_context")
            )
            flip_to = self._context_to_side(
                event.get("to_side") or event.get("flip_to") or event.get("new_context") or side
            )
            # Close existing if opposite
            if pos and (not flip_from or pos.side == flip_from):
                if flip_to and flip_to != pos.side:
                    exit_act = self._exit_position(
                        tf=tf,
                        trigger_type="CONTEXT_FLIP",
                        trigger_event_id=eid,
                        trigger_timestamp=event.get("event_timestamp"),
                        trigger_monotonic_ns=mono,
                        trigger_price=event.get("context_event_price") or event.get("price"),
                        context_event_id=eid,
                        flip_to_side=flip_to,
                        episode_id=str(episode) if episode else None,
                        event=event,
                    )
                    if exit_act:
                        actions.append(exit_act)
            # Open new side after exit (strict ordering: exit mono < entry mono)
            if flip_to in {"LONG", "SHORT"}:
                entry_mono = mono + 1
                entry_act = self._enter_position(
                    tf=tf,
                    side=flip_to,
                    event_type="CONTEXT_FLIP",
                    context_event_id=eid,
                    event_monotonic_ns=entry_mono,
                    event_timestamp=event.get("event_timestamp"),
                    context_event_price=event.get("context_event_price") or event.get("price"),
                    episode_id=str(episode) if episode else None,
                    event=event,
                )
                if entry_act:
                    actions.append(entry_act)
            return actions

        if etype == "CONTEXT_START" and side in {"LONG", "SHORT"}:
            entry_act = self._enter_position(
                tf=tf,
                side=side,
                event_type="CONTEXT_START",
                context_event_id=eid,
                event_monotonic_ns=mono,
                event_timestamp=event.get("event_timestamp"),
                context_event_price=event.get("context_event_price") or event.get("price"),
                episode_id=str(episode) if episode else None,
                event=event,
            )
            if entry_act:
                actions.append(entry_act)
            return actions

        if etype == "CONTEXT_END":
            pos = self.positions.get(tf)
            if self._is_foreign_lifecycle_episode(episode, pos):
                return actions
            if pos and (not side or side == pos.side or side in {"OBSERVE", "STAND_ASIDE", ""}):
                # END for matching side (or end of episode)
                end_side = side if side in {"LONG", "SHORT"} else pos.side
                if end_side == pos.side:
                    exit_act = self._exit_position(
                        tf=tf,
                        trigger_type="CONTEXT_END",
                        trigger_event_id=eid,
                        trigger_timestamp=event.get("event_timestamp"),
                        trigger_monotonic_ns=mono,
                        trigger_price=event.get("context_event_price") or event.get("price"),
                        context_event_id=eid,
                        episode_id=str(episode) if episode else None,
                        event=event,
                    )
                    if exit_act:
                        actions.append(exit_act)
            return actions

        # OBSERVE / STAND_ASIDE / unknown — no entry
        return actions

    def poll_context_journal(self) -> list[dict[str, Any]]:
        all_actions: list[dict[str, Any]] = []
        for ev in self.consumer.iter_new_events(
            max_entry_signal_age_seconds=self.cfg.context_event_max_age_seconds,
        ):
            actions = self.process_context_event(ev)
            eid = str(ev.get("context_event_id") or ev.get("event_id") or "")
            mono = int(ev.get("event_monotonic_ns") or 0)
            # Mark consumption of the event itself (even if no trade)
            consume_key = idempotency_key(
                paper_epoch_id=self.epoch.paper_epoch_id,
                context_event_id=eid,
                timeframe=str(ev.get("timeframe") or "NA"),
                action="CONSUME",
            )
            if not self.consumer.already_processed(consume_key):
                self.consumer.mark_processed(
                    key=consume_key,
                    context_event_id=eid,
                    event_monotonic_ns=mono,
                    path=ev.get("_journal_path"),
                    offset=ev.get("_journal_offset"),
                )
            self.consumer.save()
            all_actions.extend(actions)
        return all_actions

    @staticmethod
    def _context_to_side(value: Any) -> str:
        u = str(value or "").upper()
        if u in {"LONG", "LONG_CONTEXT"}:
            return "LONG"
        if u in {"SHORT", "SHORT_CONTEXT"}:
            return "SHORT"
        if u in {"OBSERVE", "STAND_ASIDE"}:
            return u
        return ""

    def _event_side(self, event: dict[str, Any]) -> str:
        for k in ("side", "direction", "context_side", "to_side", "new_context"):
            side = self._context_to_side(event.get(k))
            if side:
                return side
        return ""

    @staticmethod
    def _is_foreign_lifecycle_episode(episode: Any, pos: OpenPosition | None) -> bool:
        """True when an identified event episode must not touch a different open position."""
        event_episode_id = str(episode).strip() if episode else ""
        if not event_episode_id or pos is None:
            return False
        position_episode_id = str(pos.lifecycle_episode_id or "").strip()
        return event_episode_id != position_episode_id

    def _next_command_mono(self, base: int) -> int:
        self._command_seq += 1
        return int(base) + self._command_seq

    def _enter_position(
        self,
        *,
        tf: str,
        side: str,
        event_type: str,
        context_event_id: str,
        event_monotonic_ns: int,
        event_timestamp: str | None,
        context_event_price: Any,
        episode_id: str | None,
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        action = "ENTRY"
        key = idempotency_key(
            paper_epoch_id=self.epoch.paper_epoch_id,
            context_event_id=context_event_id,
            timeframe=tf,
            action=f"{action}_{side}",
        )
        if self.consumer.already_processed(key):
            return {"status": "DUPLICATE_PREVENTED", "key": key}
        if side not in {"LONG", "SHORT"}:
            return None
        if event_type not in ENTRY_EVENTS:
            return None
        replay_reason = replay_entry_block_reason(event)
        if replay_reason:
            self._block(replay_reason, tf, context_event_id, side, event=event)
            self.consumer.mark_processed(
                key=key,
                context_event_id=context_event_id,
                event_monotonic_ns=event_monotonic_ns,
            )
            return {"status": replay_reason, "timeframe": tf, "context_event_id": context_event_id}
        freshness_reason = entry_freshness_block_reason(
            event,
            max_age_seconds=self.cfg.context_event_max_age_seconds,
        )
        if freshness_reason:
            self._block(freshness_reason, tf, context_event_id, side, event=event)
            self.consumer.mark_processed(
                key=key,
                context_event_id=context_event_id,
                event_monotonic_ns=event_monotonic_ns,
            )
            return {"status": freshness_reason, "timeframe": tf, "context_event_id": context_event_id}
        stale_reason = stale_entry_block_reason(
            event,
            max_age_seconds=self.cfg.context_event_max_age_seconds,
        )
        if stale_reason:
            self._block(stale_reason, tf, context_event_id, side, event=event)
            self.consumer.mark_processed(
                key=key,
                context_event_id=context_event_id,
                event_monotonic_ns=event_monotonic_ns,
            )
            return {"status": stale_reason, "timeframe": tf, "context_event_id": context_event_id}
        if tf in self.positions:
            self._block("ENTRY_BLOCKED_ACTIVE_POSITION", tf, context_event_id, side)
            return None
        if not self.execution_market_ready_for_entry():
            self._block("ENTRY_BLOCKED_EXECUTION_MARKET_NOT_READY", tf, context_event_id, side, event=event)
            return {"status": "ENTRY_BLOCKED_EXECUTION_MARKET_NOT_READY", "timeframe": tf}
        # Episode lock applies to CONTEXT_START re-entry, not FLIP close→open.
        if event_type == "CONTEXT_START" and episode_id and episode_id in self.traded_episodes:
            self._block("ENTRY_BLOCKED_EPISODE_ALREADY_TRADED", tf, context_event_id, side)
            return None

        occurrence_px = resolve_context_entry_price(event, context_event_price)
        bbo, reason, age_ms, bbo_domain = self.bbo.resolve_execution_entry_bbo(
            command_monotonic_ns=event_monotonic_ns,
            max_age_ms=self.cfg.max_bbo_age_ms,
        )
        if bbo is None:
            self._block(reason or "ENTRY_BLOCKED_NO_CAUSAL_BBO", tf, context_event_id, side)
            self.consumer.mark_processed(
                key=key,
                context_event_id=context_event_id,
                event_monotonic_ns=event_monotonic_ns,
            )
            return {"status": reason, "timeframe": tf}

        fill_px = fill_price_for(side=side, action="ENTRY", bbo=bbo)
        entry_price_source = (
            "execution_market_bbo" if bbo_domain == "local" else "causal_bbo_entry"
        )

        equity_at_entry = float(self.equity)
        risk_pct_at_entry = float(self.cfg.max_risk_per_trade_pct)
        risk_budget_usd: float | None = None
        if self._uses_sleeves() and self.sleeves is not None:
            sleeve = self.sleeves.get(tf)
            equity_at_entry = float(sleeve.current_equity_usd)
            risk_pct_at_entry = float(sleeve.risk_pct_per_trade)
            risk_budget_usd = float(sleeve.next_risk_budget_usd)
            sizing = resolve_risk_sizing(
                cfg=self.cfg,
                side=side,
                entry_price=fill_px,
                equity_usd=equity_at_entry,
                risk_budget_usd=risk_budget_usd,
            )
        else:
            sizing = resolve_risk_sizing(
                cfg=self.cfg, side=side, entry_price=fill_px, equity_usd=self.equity
            )
            risk_budget_usd = float(sizing.risk_amount_usd)
        if not sizing.ok or sizing.quantity is None:
            self._block(sizing.block_reason or "ENTRY_BLOCKED_RISK", tf, context_event_id, side)
            self.consumer.mark_processed(
                key=key,
                context_event_id=context_event_id,
                event_monotonic_ns=event_monotonic_ns,
            )
            return {"status": sizing.block_reason, "timeframe": tf}

        cmd_id = _new_id("cmd")
        order_id = _new_id("ord")
        fill_id = _new_id("fill")
        pos_id = _new_id("pos")
        signal_id = _new_id("sig")
        execution_ts = _utc_iso()
        occurrence_ts = _occurrence_timestamp(event, event_timestamp)
        decision_available_at = event.get("decision_available_at")
        materialized_timestamp = event.get("materialized_timestamp") or event.get("ingested_at")
        cmd_mono = event_monotonic_ns
        stop_distance_usd = float(sizing.stop_distance or 0.0)
        notional_usd = float(sizing.entry_notional or 0.0)
        capital_snap = {
            "equity_at_entry_usd": equity_at_entry,
            "risk_pct_at_entry": risk_pct_at_entry,
            "risk_budget_usd": float(risk_budget_usd or sizing.risk_amount_usd),
            "stop_distance_usd": stop_distance_usd,
            "notional_usd": notional_usd,
        }
        provenance_snap = {
            "context_event_price": occurrence_px,
            "context_occurrence_timestamp": occurrence_ts,
            "decision_available_at": decision_available_at,
            "materialized_timestamp": materialized_timestamp,
            "execution_timestamp": execution_ts,
            "entry_price_source": entry_price_source,
            "execution_bbo_domain": bbo_domain,
        }
        price_snap = {
            "paper_fill_price": fill_px,
            "execution_price": fill_px,
            "best_bid": bbo.best_bid,
            "best_ask": bbo.best_ask,
            "book_update_id": bbo.book_update_id,
            "bbo_receive_timestamp": bbo.receive_timestamp,
            "bbo_receive_monotonic_ns": bbo.receive_monotonic_ns,
            "bbo_age_ms": age_ms,
            **provenance_snap,
        }

        signal = self.books.append(
            "signals",
            {
                "signal_id": signal_id,
                "timeframe": tf,
                "side": side,
                "event_type": event_type,
                "context_event_id": context_event_id,
                "lifecycle_episode_id": episode_id,
                "ts": execution_ts,
                "event_monotonic_ns": event_monotonic_ns,
                "quantity": sizing.quantity,
                "entry_price": fill_px,
                "execution_price": fill_px,
                "execution_timestamp": execution_ts,
                **capital_snap,
                **provenance_snap,
            },
        )
        command = self.books.append(
            "commands",
            {
                "command_id": cmd_id,
                "signal_id": signal_id,
                "timeframe": tf,
                "side": side,
                "action": "ENTRY",
                "context_event_id": context_event_id,
                "command_monotonic_ns": cmd_mono,
                "ts": execution_ts,
                "quantity": sizing.quantity,
                **price_snap,
                **capital_snap,
            },
        )
        self.books.append(
            "orders",
            {
                "order_id": order_id,
                "command_id": cmd_id,
                "timeframe": tf,
                "side": side,
                "action": "ENTRY",
                "quantity": sizing.quantity,
                "status": "FILLED",
                "ts": execution_ts,
                **capital_snap,
            },
        )
        fill = self.books.append(
            "fills",
            {
                "fill_id": fill_id,
                "order_id": order_id,
                "command_id": cmd_id,
                "timeframe": tf,
                "side": side,
                "action": "ENTRY",
                "gross_entry_price": fill_px,
                "quantity": sizing.quantity,
                "entry_fee_bps": self.cfg.entry_fee_bps,
                "entry_slippage_bps": self.cfg.entry_slippage_bps,
                "ts": execution_ts,
                "fill_monotonic_ns": cmd_mono,
                **price_snap,
                **capital_snap,
            },
        )
        pos_row = self.books.append(
            "positions",
            {
                "position_id": pos_id,
                "timeframe": tf,
                "side": side,
                "status": "OPEN",
                "quantity": sizing.quantity,
                "entry_price": fill_px,
                "stop_loss_price": sizing.stop_loss_price,
                "take_profit_price": sizing.take_profit_price,
                "risk_amount_usd": sizing.risk_amount_usd,
                "lifecycle_episode_id": episode_id,
                "entry_context_event_id": context_event_id,
                "context_event_age_seconds": event.get("event_age_seconds"),
                "entry_fill_id": fill_id,
                "entry_command_id": cmd_id,
                "entry_monotonic_ns": cmd_mono,
                "opened_at": execution_ts,
                "execution_timestamp": execution_ts,
                "execution_price": fill_px,
                **capital_snap,
                **provenance_snap,
            },
        )
        self.positions[tf] = OpenPosition(
            position_id=pos_id,
            timeframe=tf,
            side=side,
            quantity=float(sizing.quantity),
            entry_price=fill_px,
            stop_loss_price=float(sizing.stop_loss_price or 0.0),
            take_profit_price=float(sizing.take_profit_price or 0.0),
            risk_amount_usd=float(sizing.risk_amount_usd),
            lifecycle_episode_id=episode_id,
            context_event_id=context_event_id,
            entry_fill_id=fill_id,
            entry_command_id=cmd_id,
            entry_monotonic_ns=cmd_mono,
        )
        if self._uses_sleeves() and self.sleeves is not None:
            self.sleeves.mark_open(tf, pos_id, float(sizing.risk_amount_usd))
        if episode_id:
            self.traded_episodes.add(episode_id)
        self.consumer.mark_processed(
            key=key,
            context_event_id=context_event_id,
            event_monotonic_ns=event_monotonic_ns,
        )
        self.last_command = command
        self.last_fill = fill
        return {"status": "ENTERED", "position": pos_row, "fill": fill, "signal": signal}

    def _exit_position(
        self,
        *,
        tf: str,
        trigger_type: str,
        trigger_event_id: str,
        trigger_timestamp: str | None,
        trigger_monotonic_ns: int,
        trigger_price: Any,
        context_event_id: str,
        flip_to_side: str | None = None,
        episode_id: str | None = None,
        use_local_bbo: bool = False,
        market_provenance: dict[str, Any] | None = None,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        pos = self.positions.get(tf)
        if not pos:
            return None
        action = "EXIT"
        key = idempotency_key(
            paper_epoch_id=self.epoch.paper_epoch_id,
            context_event_id=context_event_id,
            timeframe=tf,
            action=f"{action}_{pos.side}_{trigger_type}",
        )
        if self.consumer.already_processed(key):
            return {"status": "DUPLICATE_PREVENTED", "key": key}

        trigger_u = str(trigger_type).upper()

        protective_level: float | None = None
        if trigger_u in {"SL", "STOP", "STOP_LOSS"}:
            protective_level = float(pos.stop_loss_price)
        elif trigger_u in {"TP", "TAKE_PROFIT"}:
            protective_level = float(pos.take_profit_price)

        if protective_level is not None:
            event_price = (
                float(trigger_price)
                if trigger_price is not None
                else protective_level
            )
            return self._complete_exit(
                pos=pos,
                key=key,
                bbo=None,
                age_ms=None,
                trigger_type=trigger_type,
                trigger_event_id=trigger_event_id,
                trigger_timestamp=trigger_timestamp,
                trigger_monotonic_ns=trigger_monotonic_ns,
                trigger_price=event_price,
                context_event_id=context_event_id,
                episode_id=episode_id or pos.lifecycle_episode_id,
                execution_price_override=event_price,
                market_provenance=market_provenance,
            )

        if use_local_bbo:
            bbo, reason, age_ms = self.bbo.resolve_local(
                command_monotonic_ns=trigger_monotonic_ns,
                max_age_ms=self.cfg.max_bbo_age_ms,
            )
            bbo_domain = "local"
        else:
            bbo, reason, age_ms, bbo_domain = self.bbo.resolve_execution_entry_bbo(
                command_monotonic_ns=trigger_monotonic_ns,
                max_age_ms=self.cfg.max_bbo_age_ms,
            )
            if reason == "ENTRY_BLOCKED_NO_CAUSAL_BBO":
                reason = "EXIT_PENDING_NO_CAUSAL_BBO"
        if bbo is None:
            self.pending_exits[tf] = PendingExit(
                timeframe=tf,
                reason=reason or "EXIT_PENDING_NO_CAUSAL_BBO",
                context_event_id=context_event_id,
                command_monotonic_ns=trigger_monotonic_ns,
                trigger_type=trigger_type,
                trigger_event_id=trigger_event_id,
                trigger_timestamp=trigger_timestamp,
                trigger_price=float(trigger_price) if trigger_price is not None else None,
                flip_to_side=flip_to_side,
                episode_id=episode_id,
                event=event,
            )
            self.blocked_commands += 1
            return {"status": reason, "timeframe": tf}

        return self._complete_exit(
            pos=pos,
            key=key,
            bbo=bbo,
            age_ms=age_ms,
            trigger_type=trigger_type,
            trigger_event_id=trigger_event_id,
            trigger_timestamp=trigger_timestamp,
            trigger_monotonic_ns=trigger_monotonic_ns,
            trigger_price=trigger_price,
            context_event_id=context_event_id,
            episode_id=episode_id or pos.lifecycle_episode_id,
            market_provenance=market_provenance,
            event=event,
            bbo_domain=bbo_domain,
        )

    def _try_pending_exit(self, tf: str) -> list[dict[str, Any]] | None:
        pend = self.pending_exits.get(tf)
        pos = self.positions.get(tf)
        if not pend or not pos:
            return None
        bbo, reason, age_ms, bbo_domain = self.bbo.resolve_execution_entry_bbo(
            command_monotonic_ns=pend.command_monotonic_ns,
            max_age_ms=self.cfg.max_bbo_age_ms,
        )
        if bbo is None:
            return None
        key = idempotency_key(
            paper_epoch_id=self.epoch.paper_epoch_id,
            context_event_id=pend.context_event_id,
            timeframe=tf,
            action=f"EXIT_{pos.side}_{pend.trigger_type}",
        )
        del self.pending_exits[tf]
        exit_act = self._complete_exit(
            pos=pos,
            key=key,
            bbo=bbo,
            age_ms=age_ms,
            trigger_type=pend.trigger_type,
            trigger_event_id=pend.trigger_event_id,
            trigger_timestamp=pend.trigger_timestamp,
            trigger_monotonic_ns=pend.command_monotonic_ns,
            trigger_price=pend.trigger_price,
            context_event_id=pend.context_event_id,
            episode_id=pend.episode_id or pos.lifecycle_episode_id,
            event=pend.event,
            bbo_domain=bbo_domain,
        )
        actions = [exit_act]
        if pend.flip_to_side in {"LONG", "SHORT"} and pend.event is not None:
            entry_act = self._enter_position(
                tf=tf,
                side=pend.flip_to_side,
                event_type="CONTEXT_FLIP",
                context_event_id=pend.context_event_id,
                event_monotonic_ns=pend.command_monotonic_ns + 1,
                event_timestamp=pend.trigger_timestamp,
                context_event_price=pend.trigger_price,
                episode_id=pend.episode_id,
                event=pend.event,
            )
            if entry_act:
                actions.append(entry_act)
        return actions

    def _complete_exit(
        self,
        *,
        pos: OpenPosition,
        key: str,
        bbo: Any,
        age_ms: float | None,
        trigger_type: str,
        trigger_event_id: str,
        trigger_timestamp: str | None,
        trigger_monotonic_ns: int,
        trigger_price: Any,
        context_event_id: str,
        episode_id: str | None,
        execution_price_override: float | None = None,
        market_provenance: dict[str, Any] | None = None,
        event: dict[str, Any] | None = None,
        bbo_domain: str | None = None,
    ) -> dict[str, Any]:
        fill_px = (
            float(execution_price_override)
            if execution_price_override is not None
            else fill_price_for(side=pos.side, action="EXIT", bbo=bbo)
        )
        trigger_u = str(trigger_type).upper()
        protective_level: float | None = None
        if trigger_u in {"SL", "STOP", "STOP_LOSS"}:
            protective_level = float(pos.stop_loss_price)
        elif trigger_u in {"TP", "TAKE_PROFIT"}:
            protective_level = float(pos.take_profit_price)
        protective_slippage = (
            fill_px - protective_level
            if protective_level is not None
            else None
        )
        econ = closed_trade_economics(
            cfg=self.cfg,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=fill_px,
            quantity=pos.quantity,
            risk_amount_usd=pos.risk_amount_usd,
            exit_reason=trigger_type,
        )
        now = _utc_iso()
        execution_ts = now
        event = event or {}
        occurrence_px = resolve_context_entry_price(event, trigger_price)
        occurrence_ts = _occurrence_timestamp(event, trigger_timestamp)
        provenance_snap = {
            "context_event_price": occurrence_px,
            "context_occurrence_timestamp": occurrence_ts,
            "decision_available_at": event.get("decision_available_at"),
            "materialized_timestamp": event.get("materialized_timestamp") or event.get("ingested_at"),
            "execution_timestamp": execution_ts,
            "execution_price": fill_px,
            "execution_bbo_domain": bbo_domain,
        }
        cmd_id = _new_id("cmd")
        order_id = _new_id("ord")
        fill_id = _new_id("fill")
        trade_id = _new_id("trd")
        command_payload: dict[str, Any] = {
            "command_id": cmd_id,
            "timeframe": pos.timeframe,
            "side": pos.side,
            "action": "EXIT",
            "trigger_type": trigger_type,
            "trigger_event_id": trigger_event_id,
            "trigger_timestamp": trigger_timestamp,
            "trigger_monotonic_ns": trigger_monotonic_ns,
            "trigger_price": trigger_price,
            "context_event_id": context_event_id,
            "command_monotonic_ns": trigger_monotonic_ns,
            "book_update_id": (bbo.book_update_id if bbo is not None else None),
            "best_bid": (bbo.best_bid if bbo is not None else None),
            "best_ask": (bbo.best_ask if bbo is not None else None),
            "bbo_receive_timestamp": (bbo.receive_timestamp if bbo is not None else None),
            "bbo_receive_monotonic_ns": (bbo.receive_monotonic_ns if bbo is not None else None),
            "bbo_age_ms": age_ms,
            "fill_bid": (bbo.best_bid if bbo is not None else None),
            "fill_ask": (bbo.best_ask if bbo is not None else None),
            "paper_fill_price": fill_px,
            "ts": now,
            **provenance_snap,
        }
        if protective_level is not None:
            command_payload.update(
                protective_level=protective_level,
                protective_slippage=protective_slippage,
            )
        if market_provenance:
            command_payload.update(market_provenance)
        command = self.books.append("commands", command_payload)
        self.books.append(
            "orders",
            {
                "order_id": order_id,
                "command_id": cmd_id,
                "timeframe": pos.timeframe,
                "side": pos.side,
                "action": "EXIT",
                "quantity": pos.quantity,
                "status": "FILLED",
                "ts": now,
                "execution_timestamp": execution_ts,
            },
        )
        fill_payload: dict[str, Any] = {
            "fill_id": fill_id,
            "order_id": order_id,
            "command_id": cmd_id,
            "timeframe": pos.timeframe,
            "side": pos.side,
            "action": "EXIT",
            "gross_exit_price": fill_px,
            "paper_fill_price": fill_px,
            "quantity": pos.quantity,
            "fill_bid": (bbo.best_bid if bbo is not None else None),
            "fill_ask": (bbo.best_ask if bbo is not None else None),
            "trigger_type": trigger_type,
            "trigger_event_id": trigger_event_id,
            "trigger_timestamp": trigger_timestamp,
            "trigger_monotonic_ns": trigger_monotonic_ns,
            "trigger_price": trigger_price,
            "ts": now,
            "fill_monotonic_ns": trigger_monotonic_ns,
            **provenance_snap,
        }
        if protective_level is not None:
            fill_payload.update(
                protective_level=protective_level,
                protective_slippage=protective_slippage,
            )
        if market_provenance:
            fill_payload.update(market_provenance)
        fill = self.books.append("fills", fill_payload)
        trade_payload: dict[str, Any] = {
            "trade_id": trade_id,
            "position_id": pos.position_id,
            "timeframe": pos.timeframe,
            "side": pos.side,
            "quantity": pos.quantity,
            "entry_price": pos.entry_price,
            "exit_price": fill_px,
            "gross_pnl_usd": econ["gross_pnl_usd"],
            "net_pnl_usd": econ["net_pnl_usd"],
            "fees_usd": econ["fees_usd"],
            "slippage_usd": econ["slippage_usd"],
            "entry_fee_usd": econ["entry_fee_usd"],
            "exit_fee_usd": econ["exit_fee_usd"],
            "risk_amount_usd": pos.risk_amount_usd,
            "exit_reason": trigger_type,
            "lifecycle_episode_id": episode_id,
            "entry_ts": None,
            "exit_ts": now,
            "status": "CLOSED",
            **provenance_snap,
        }
        if protective_level is not None:
            trade_payload.update(
                trigger_price=float(trigger_price) if trigger_price is not None else None,
                protective_level=protective_level,
                protective_slippage=protective_slippage,
                stop_loss_price=pos.stop_loss_price,
                take_profit_price=pos.take_profit_price,
            )
        trade = self.books.append("trades", trade_payload)
        # Mark position closed via append of closed row (open filter uses status)
        closed_position_payload: dict[str, Any] = {
            "position_id": pos.position_id,
            "timeframe": pos.timeframe,
            "side": pos.side,
            "status": "CLOSED",
            "quantity": pos.quantity,
            "entry_price": pos.entry_price,
            "exit_price": fill_px,
            "closed_at": now,
            "exit_reason": trigger_type,
            "lifecycle_episode_id": episode_id,
            **provenance_snap,
        }
        if protective_level is not None:
            closed_position_payload.update(
                protective_level=protective_level,
                protective_slippage=protective_slippage,
                stop_loss_price=pos.stop_loss_price,
                take_profit_price=pos.take_profit_price,
            )
        self.books.append("positions", closed_position_payload)
        del self.positions[pos.timeframe]
        if self._uses_sleeves() and self.sleeves is not None:
            sleeve = self.sleeves.apply_realized_net_pnl(
                pos.timeframe, float(econ["net_pnl_usd"]), at=now
            )
            master = self.sleeves.master_snapshot()
            self.realized_pnl = float(master["master_realized_net_pnl_usd"])
            self.equity = float(master["master_current_equity_usd"])
            sleeve_equity = float(sleeve.current_equity_usd)
        else:
            self.realized_pnl += float(econ["net_pnl_usd"])
            self.equity = float(self.epoch.initial_equity_usd) + self.realized_pnl
            sleeve_equity = self.equity
        self.books.append(
            "equity_snapshots",
            {
                "ts": now,
                "equity_usd": self.equity,
                "realized_pnl_usd": self.realized_pnl,
                "unrealized_pnl_usd": 0.0,
                "trade_id": trade_id,
                "timeframe": pos.timeframe,
                "timeframe_equity_usd": sleeve_equity,
                "timeframe_net_pnl_usd": float(econ["net_pnl_usd"]),
            },
        )
        self.consumer.mark_processed(
            key=key,
            context_event_id=context_event_id,
            event_monotonic_ns=trigger_monotonic_ns,
        )
        self.last_command = command
        self.last_fill = fill
        return {"status": "EXITED", "trade": trade, "fill": fill}

    def _check_tp_sl_on_market(
        self,
        *,
        trigger_monotonic_ns: int,
        trigger_event_id: str,
        trigger_timestamp: str | None,
        trade_price: float | None,
        use_local_bbo: bool = False,
        market_provenance: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Protective TP/SL is triggered by the market trade price only."""
        actions: list[dict[str, Any]] = []
        if trade_price is None:
            return actions

        px = float(trade_price)

        for tf, pos in list(self.positions.items()):
            if pos.side == "LONG":
                hit_tp = px >= pos.take_profit_price
                hit_sl = px <= pos.stop_loss_price
            else:
                hit_tp = px <= pos.take_profit_price
                hit_sl = px >= pos.stop_loss_price

            if hit_tp and hit_sl:
                d_tp = abs(px - pos.take_profit_price)
                d_sl = abs(px - pos.stop_loss_price)
                trigger = "TP" if d_tp <= d_sl else "SL"
            elif hit_tp:
                trigger = "TP"
            elif hit_sl:
                trigger = "SL"
            else:
                continue

            act = self._exit_position(
                tf=tf,
                trigger_type=trigger,
                trigger_event_id=trigger_event_id,
                trigger_timestamp=trigger_timestamp,
                trigger_monotonic_ns=trigger_monotonic_ns,
                trigger_price=px,
                context_event_id=trigger_event_id,
                use_local_bbo=False,
                market_provenance=market_provenance,
            )
            if act:
                actions.append(act)
        return actions

    def _block(
        self,
        reason: str,
        tf: str,
        context_event_id: str,
        side: str,
        *,
        event: dict[str, Any] | None = None,
    ) -> None:
        self.blocked_commands += 1
        payload: dict[str, Any] = {
            "ts": _utc_iso(),
            "reason": reason,
            "timeframe": tf,
            "context_event_id": context_event_id,
            "side": side,
        }
        if event:
            payload["decision_available_at"] = event.get("decision_available_at")
            payload["event_timestamp"] = event.get("event_timestamp")
            payload["ingested_at"] = event.get("ingested_at")
            payload["evaluation_mode"] = event.get("evaluation_mode")
            payload["restart_backfill"] = event.get("restart_backfill")
            payload["materialization_class"] = event.get("materialization_class")
            payload["lifecycle_episode_id"] = event.get("lifecycle_episode_id")
        self.books.append("blocked", payload)

    def health(self) -> dict[str, Any]:
        import os

        bbo = self.bbo.latest
        age = None
        local = self.bbo._latest_local
        current_bbo = None
        if local is not None:
            age = max(0.0, (time.monotonic_ns() - local.receive_monotonic_ns) / 1_000_000.0)
            current_bbo = {
                "best_bid": local.best_bid,
                "best_ask": local.best_ask,
                "bbo_receive_timestamp": local.receive_timestamp,
                "book_update_id": local.book_update_id,
                "source_event_id": local.source_event_id,
                "source": "manager_local_book_ticker",
                "freshness_ms": age,
            }
        elif bbo is not None and bbo.receive_timestamp:
            age = None  # context-domain mono not comparable to wall clock
        manager_alive = True
        lanes = {tf: "ACTIVE" for tf in self.cfg.timeframes}
        consumer_status = "CONNECTED"
        ck = self.consumer.checkpoint
        payload: dict[str, Any] = {
            "service": "intrabar_paper_manager",
            "pid": os.getpid(),
            "alive": manager_alive,
            "paper_epoch_id": self.epoch.paper_epoch_id,
            "mode": "paper_only",
            "paper_only": True,
            "real_execution_enabled": False,
            "manager_status": "CONNECTED",
            "context_consumer_status": consumer_status,
            "execution_lanes": lanes,
            "last_consumed_context_event_id": ck.last_consumed_context_event_id,
            "last_event_monotonic_ns": ck.last_event_monotonic_ns,
            "context_consumer_lag_events": None,
            "last_command": self.last_command,
            "last_fill": self.last_fill,
            "last_context_event": self.last_context_event,
            "active_positions_by_timeframe": {
                tf: {"side": p.side, "quantity": p.quantity, "entry_price": p.entry_price}
                for tf, p in self.positions.items()
            },
            "trades_count": self.books.count("trades"),
            "signals_count": self.books.count("signals"),
            "orders_count": self.books.count("orders"),
            "fills_count": self.books.count("fills"),
            "equity_usd": self.equity,
            "realized_pnl_usd": self.realized_pnl,
            "unrealized_pnl_usd": self.unrealized_pnl,
            "bbo_freshness_ms": age,
            "current_bbo": current_bbo,
            "max_bbo_age_ms": self.cfg.max_bbo_age_ms,
            "blocked_commands": self.blocked_commands,
            "duplicate_events_prevented": ck.duplicate_events_prevented,
            "errors": list(self.errors),
            "entry_fee_bps": self.cfg.entry_fee_bps,
            "exit_fee_bps": self.cfg.exit_fee_bps,
            "entry_slippage_bps": self.cfg.entry_slippage_bps,
            "exit_slippage_bps": self.cfg.exit_slippage_bps,
            "max_risk_per_trade_usd": self.cfg.max_risk_per_trade_usd,
            "initial_equity_usd": self.epoch.initial_equity_usd,
            "capital_model": self.capital_model,
            "updated_at": _utc_iso(),
            "health_write_error": self.last_health_write_error,
        }
        if self.execution_market is not None:
            payload["execution_market"] = self.execution_market.snapshot()
        if self._uses_sleeves() and self.sleeves is not None:
            master = self.sleeves.master_snapshot()
            payload.update(
                {
                    "sleeves": {tf: s.to_dict() for tf, s in self.sleeves.sleeves.items()},
                    "master_initial_equity_usd": master["master_initial_equity_usd"],
                    "master_current_equity_usd": master["master_current_equity_usd"],
                    "master_realized_net_pnl_usd": master["master_realized_net_pnl_usd"],
                    "master_unrealized_pnl_usd": master["master_unrealized_pnl_usd"],
                    "master_open_risk_usd": master["master_open_risk_usd"],
                    "master_risk_capacity_usd": master["master_risk_capacity_usd"],
                    "master_available_risk_usd": master["master_available_risk_usd"],
                    "equity_usd": master["master_current_equity_usd"],
                    "realized_pnl_usd": master["master_realized_net_pnl_usd"],
                    "initial_equity_usd": master["master_initial_equity_usd"],
                }
            )
        return payload

    def write_health(self) -> Path:
        payload = self.health()
        encoded = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
        failures: list[str] = []
        for target in (self.health_path, Path("data/runtime/intrabar_paper_health.json")):
            tmp = target.with_suffix(".tmp")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(encoded, encoding="utf-8")
                tmp.replace(target)
            except OSError as exc:
                failures.append(f"{target}:{type(exc).__name__}:{exc}")
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        self.last_health_write_error = "; ".join(failures) or None
        return self.health_path
