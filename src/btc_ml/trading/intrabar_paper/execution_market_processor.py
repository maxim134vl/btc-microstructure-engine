"""Synchronous execution market processor: WS → WAL → continuity → engine."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .execution_market_backfill import FetchAggTradesFn, default_fetch_agg_trades, normalize_rest_agg_trade
from .execution_market_checkpoint import ExecutionMarketCheckpoint
from .execution_market_state import (
    PROTECTIVE_EXIT_DURABILITY_DEGRADED,
    ExecutionMarketState,
    ExecutionMarketStateMachine,
)
from .execution_market_wal import (
    EVENT_AGG_TRADE,
    EVENT_BOOK_TICKER,
    ExecutionMarketWAL,
    WalAppendResult,
)

if False:  # pragma: no cover - typing only
    from .engine import IntrabarPaperEngine


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_futures_agg_trade(
    data: dict[str, Any],
    *,
    symbol: str,
    connection_session_id: str,
    receive_monotonic_ns: int,
    receive_timestamp: str,
) -> dict[str, Any]:
    agg_id = int(data.get("a") or data.get("aggregateTradeId") or 0)
    return {
        "event_type": EVENT_AGG_TRADE,
        "symbol": symbol.upper(),
        "aggregate_trade_id": agg_id,
        "exchange_event_timestamp": data.get("E"),
        "exchange_trade_timestamp": data.get("T"),
        "price": str(data.get("p") or "0"),
        "quantity": str(data.get("q") or "0"),
        "buyer_is_market_maker": data.get("m"),
        "local_receive_timestamp": receive_timestamp,
        "local_receive_monotonic_ns": receive_monotonic_ns,
        "connection_session_id": connection_session_id,
        "source_event_id": f"agg_{agg_id}",
        "backfill": False,
    }


def normalize_futures_book_ticker(
    data: dict[str, Any],
    *,
    symbol: str,
    connection_session_id: str,
    receive_monotonic_ns: int,
    receive_timestamp: str,
) -> dict[str, Any]:
    update_id = data.get("u") or data.get("updateId")
    return {
        "event_type": EVENT_BOOK_TICKER,
        "symbol": symbol.upper(),
        "book_update_id": str(update_id) if update_id is not None else None,
        "best_bid": str(data.get("b") or data.get("bidPrice") or "0"),
        "best_ask": str(data.get("a") or data.get("askPrice") or "0"),
        "exchange_event_timestamp": data.get("E"),
        "local_receive_timestamp": receive_timestamp,
        "local_receive_monotonic_ns": receive_monotonic_ns,
        "connection_session_id": connection_session_id,
        "source_event_id": f"bbo_{update_id or receive_monotonic_ns}",
        "backfill": False,
    }


@dataclass
class ExecutionMarketProcessor:
    engine: Any
    wal: ExecutionMarketWAL
    checkpoint: ExecutionMarketCheckpoint
    state: ExecutionMarketStateMachine
    symbol: str = "BTCUSDT"
    fetch_agg_trades: FetchAggTradesFn = default_fetch_agg_trades
    public_connection_session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    market_connection_session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    reconnect_generation: int = 0
    dispatch_log: list[tuple[str, int | None]] = field(default_factory=list)
    wal_append_log: list[int | None] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        engine: Any,
        epoch_root: Path,
        paper_epoch_id: str,
        max_bbo_age_ms: float,
        max_agg_trade_age_ms: float,
        symbol: str = "BTCUSDT",
        fetch_agg_trades: FetchAggTradesFn | None = None,
    ) -> "ExecutionMarketProcessor":
        wal_root = epoch_root / "execution_market_wal"
        wal = ExecutionMarketWAL(wal_root, paper_epoch_id=paper_epoch_id)
        ck_path = epoch_root / "execution_market_checkpoint.json"
        checkpoint = ExecutionMarketCheckpoint.load(ck_path, paper_epoch_id=paper_epoch_id)
        state = ExecutionMarketStateMachine(
            max_bbo_age_ms=max_bbo_age_ms,
            max_agg_trade_age_ms=max_agg_trade_age_ms,
        )
        state.on_start()
        proc = cls(
            engine=engine,
            wal=wal,
            checkpoint=checkpoint,
            state=state,
            symbol=symbol,
            fetch_agg_trades=fetch_agg_trades or default_fetch_agg_trades,
        )
        proc.replay_from_checkpoint()
        if wal.last_confirmed_agg_trade_id is not None:
            state.last_confirmed_agg_trade_id = wal.last_confirmed_agg_trade_id
        return proc

    @property
    def checkpoint_path(self) -> Path:
        return Path(self.engine.epoch_root) / "execution_market_checkpoint.json"

    @property
    def connection_session_id(self) -> str:
        """Backward-compatible alias for PUBLIC route session id."""
        return self.public_connection_session_id

    def execution_market_ready_for_entry(self) -> bool:
        return self.state.execution_market_ready_for_entry()

    def on_public_websocket_connected(self) -> None:
        self.public_connection_session_id = str(uuid.uuid4())
        self.reconnect_generation += 1
        self.state.on_public_connected()

    def on_public_websocket_disconnected(self) -> None:
        self.state.on_public_disconnected()

    def on_market_websocket_connected(self) -> None:
        self.market_connection_session_id = str(uuid.uuid4())
        self.reconnect_generation += 1
        self.state.on_market_connected()

    def on_market_websocket_disconnected(self) -> None:
        self.state.on_market_disconnected()

    def on_websocket_connected(self) -> None:
        self.public_connection_session_id = str(uuid.uuid4())
        self.market_connection_session_id = str(uuid.uuid4())
        self.reconnect_generation += 1
        self.state.on_websocket_connected()

    def on_websocket_disconnected(self) -> None:
        self.state.on_websocket_disconnected()

    def handle_public_ws_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data") or payload
        stream = str(payload.get("stream") or "")
        if "bookTicker" not in stream and not self._looks_like_book_ticker(data):
            return []
        mono = time.monotonic_ns()
        ts = _utc_iso()
        event = normalize_futures_book_ticker(
            data,
            symbol=self.symbol,
            connection_session_id=self.public_connection_session_id,
            receive_monotonic_ns=mono,
            receive_timestamp=ts,
        )
        return [self._process_book_ticker(event)]

    def handle_market_ws_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data") or payload
        stream = str(payload.get("stream") or "")
        if "aggTrade" not in stream and data.get("e") != "aggTrade":
            return []
        mono = time.monotonic_ns()
        ts = _utc_iso()
        event = normalize_futures_agg_trade(
            data,
            symbol=self.symbol,
            connection_session_id=self.market_connection_session_id,
            receive_monotonic_ns=mono,
            receive_timestamp=ts,
        )
        return self._process_agg_trade_live(event)

    def handle_ws_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        actions.extend(self.handle_public_ws_payload(payload))
        actions.extend(self.handle_market_ws_payload(payload))
        return actions

    @staticmethod
    def _looks_like_book_ticker(data: dict[str, Any]) -> bool:
        return "bookTicker" in str(data.get("e") or "") or (
            "b" in data and "a" in data and "u" in data and data.get("e") != "aggTrade"
        )

    def _append_with_retry(self, event: dict[str, Any], *, allow_degraded_protective: bool = False) -> WalAppendResult:
        last = WalAppendResult(ok=False, error="unknown", retryable=True)
        for _ in range(2):
            last = self.wal.append(event)
            if last.ok:
                self.state.on_wal_append_success()
                if last.wal_offset is not None:
                    self.wal_append_log.append(last.wal_offset)
                return last
            self.state.on_wal_append_failure(retryable=bool(last.retryable))
        if allow_degraded_protective:
            return last
        return last

    def _process_book_ticker(self, event: dict[str, Any]) -> dict[str, Any]:
        append = self._append_with_retry(event)
        if not append.ok:
            return {"status": "WAL_APPEND_FAILED", "event_type": EVENT_BOOK_TICKER}
        bid = float(event["best_bid"])
        ask = float(event["best_ask"])
        if bid <= 0 or ask <= 0:
            return {"status": "INVALID_BBO"}
        self.state.note_book_ticker(receive_monotonic_ns=int(event["local_receive_monotonic_ns"]))
        self._dispatch_book_ticker(event, wal_offset=append.wal_offset)
        return {"status": "BOOK_TICKER_DISPATCHED", "wal_offset": append.wal_offset}

    def _process_agg_trade_live(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        agg_id = int(event["aggregate_trade_id"])
        if agg_id in self.checkpoint.processed_agg_trade_ids:
            return [{"status": "DUPLICATE_AGG_TRADE_SKIPPED", "aggregate_trade_id": agg_id}]
        expected = self.state.last_confirmed_agg_trade_id
        if expected is not None and agg_id > expected + 1:
            missing = list(range(expected + 1, agg_id))
            return self._recover_gap_then_process(event, missing_ids=missing)
        if expected is not None and agg_id <= expected:
            return [{"status": "DUPLICATE_AGG_TRADE_SKIPPED", "aggregate_trade_id": agg_id}]
        return [self._persist_and_dispatch_agg_trade(event)]

    def _recover_gap_then_process(self, live_event: dict[str, Any], *, missing_ids: list[int]) -> list[dict[str, Any]]:
        self.state.on_gap_detected()
        actions: list[dict[str, Any]] = []
        if not missing_ids:
            actions.append(self._persist_and_dispatch_agg_trade(live_event))
            return actions
        try:
            rows = self.fetch_agg_trades(self.symbol, missing_ids[0], missing_ids[-1])
        except Exception as exc:  # noqa: BLE001
            self.state.on_backfill_failed()
            return [{"status": "BACKFILL_FAILED", "error": str(exc)}]
        fetched_ids = sorted(int(r["a"]) for r in rows)
        if fetched_ids != missing_ids:
            self.state.on_backfill_failed()
            return [{"status": "BACKFILL_INCOMPLETE", "expected": missing_ids, "got": fetched_ids}]
        for row in rows:
            backfill_event = normalize_rest_agg_trade(
                row,
                symbol=self.symbol,
                connection_session_id=self.market_connection_session_id,
                receive_monotonic_ns=int(live_event["local_receive_monotonic_ns"]),
                receive_timestamp=str(live_event["local_receive_timestamp"]),
            )
            actions.append(self._persist_and_dispatch_agg_trade(backfill_event))
        actions.append(self._persist_and_dispatch_agg_trade(live_event))
        self.state.on_gap_resolved(last_confirmed=int(live_event["aggregate_trade_id"]))
        return actions

    def _persist_and_dispatch_agg_trade(self, event: dict[str, Any]) -> dict[str, Any]:
        agg_id = int(event["aggregate_trade_id"])
        protective = self._agg_trade_crosses_protective(float(event["price"]))
        append = self._append_with_retry(event, allow_degraded_protective=protective)
        if not append.ok:
            if protective:
                action = self._dispatch_agg_trade(
                    event,
                    wal_offset=None,
                    durability_degraded=True,
                )
                action["status"] = "PROTECTIVE_EXIT_DURABILITY_DEGRADED"
                return action
            return {"status": "WAL_APPEND_FAILED", "aggregate_trade_id": agg_id}
        if self.state.state == ExecutionMarketState.RECOVERING and not self.state.unresolved_gap:
            self.state.on_gap_resolved(last_confirmed=agg_id)
        return self._dispatch_agg_trade(event, wal_offset=append.wal_offset)

    def _agg_trade_crosses_protective(self, price: float) -> bool:
        for pos in self.engine.positions.values():
            if pos.side == "LONG":
                if price <= pos.stop_loss_price or price >= pos.take_profit_price:
                    return True
            else:
                if price >= pos.stop_loss_price or price <= pos.take_profit_price:
                    return True
        return False

    def _dispatch_book_ticker(self, event: dict[str, Any], *, wal_offset: int | None) -> None:
        self.dispatch_log.append((EVENT_BOOK_TICKER, wal_offset))
        self.engine.update_bbo_from_market(
            best_bid=float(event["best_bid"]),
            best_ask=float(event["best_ask"]),
            receive_monotonic_ns=int(event["local_receive_monotonic_ns"]),
            receive_timestamp=event.get("local_receive_timestamp"),
            book_update_id=event.get("book_update_id"),
            source_event_id=event.get("source_event_id"),
            market_provenance=self._provenance(event, wal_offset),
        )

    def _dispatch_agg_trade(
        self,
        event: dict[str, Any],
        *,
        wal_offset: int | None,
        durability_degraded: bool = False,
    ) -> dict[str, Any]:
        self.dispatch_log.append((EVENT_AGG_TRADE, wal_offset))
        provenance = self._provenance(event, wal_offset)
        if durability_degraded:
            provenance["durability_degraded"] = True
            provenance["durability_reason"] = PROTECTIVE_EXIT_DURABILITY_DEGRADED
        result = self.engine.update_from_trade(
            price=float(event["price"]),
            receive_monotonic_ns=int(event["local_receive_monotonic_ns"]),
            receive_timestamp=event.get("local_receive_timestamp"),
            source_event_id=event.get("source_event_id"),
            market_provenance=provenance,
        )
        agg_id = int(event["aggregate_trade_id"])
        self.checkpoint.last_processed_wal_offset = int(wal_offset or self.checkpoint.last_processed_wal_offset)
        self.checkpoint.last_processed_agg_trade_id = agg_id
        self.checkpoint.processed_agg_trade_ids.add(agg_id)
        self.checkpoint.save(self.checkpoint_path)
        self.state.note_agg_trade(
            aggregate_trade_id=agg_id,
            receive_monotonic_ns=int(event["local_receive_monotonic_ns"]),
        )
        return {"status": "AGG_TRADE_DISPATCHED", "wal_offset": wal_offset, "result": result}

    @staticmethod
    def _provenance(event: dict[str, Any], wal_offset: int | None) -> dict[str, Any]:
        prov = {
            "execution_market_source": "BINANCE_FUTURES",
            "source_event_id": event.get("source_event_id"),
            "connection_session_id": event.get("connection_session_id"),
            "exchange_event_timestamp": event.get("exchange_event_timestamp"),
            "exchange_trade_timestamp": event.get("exchange_trade_timestamp"),
        }
        if wal_offset is not None:
            prov["execution_market_wal_offset"] = wal_offset
        if event.get("event_type") == EVENT_AGG_TRADE:
            prov["aggregate_trade_id"] = event.get("aggregate_trade_id")
        if event.get("event_type") == EVENT_BOOK_TICKER:
            prov["book_update_id"] = event.get("book_update_id")
        return prov

    def replay_from_checkpoint(self) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for event in self.wal.iter_from_offset(self.checkpoint.last_processed_wal_offset):
            if event.get("event_type") == EVENT_BOOK_TICKER:
                self._dispatch_book_ticker(event, wal_offset=int(event.get("wal_offset") or 0))
                actions.append({"status": "REPLAY_BOOK_TICKER", "wal_offset": event.get("wal_offset")})
            elif event.get("event_type") == EVENT_AGG_TRADE:
                agg_id = int(event["aggregate_trade_id"])
                if agg_id in self.checkpoint.processed_agg_trade_ids:
                    continue
                actions.append(
                    self._dispatch_agg_trade(event, wal_offset=int(event.get("wal_offset") or 0))
                )
        return actions

    def snapshot(self) -> dict[str, Any]:
        return {
            "public_connection_session_id": self.public_connection_session_id,
            "market_connection_session_id": self.market_connection_session_id,
            "wal": {
                "root": str(self.wal.root),
                "last_offset": self.wal.last_offset,
                "last_confirmed_agg_trade_id": self.wal.last_confirmed_agg_trade_id,
            },
            "checkpoint": self.checkpoint.to_dict(),
            "state": self.state.snapshot(),
        }
