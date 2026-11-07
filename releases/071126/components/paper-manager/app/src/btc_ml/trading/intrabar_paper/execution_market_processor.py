"""Synchronous execution market processor: WS → WAL → continuity → engine."""

from __future__ import annotations

import time
import os
import uuid
import threading
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
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


class ReplayInterrupted(RuntimeError):
    """Requested stop before replay completes; never admits live execution."""


class DeferredPublicPublication:
    """Process-local receive-only FIFO; economic publication retains MARKET order.

    Capacity 4096 matches the existing recovery action bound. Exhaustion is a
    restart-required fault, never quote eviction or an admission acknowledgment.
    The small condition protects only identity/queue bookkeeping, never I/O.
    """
    def __init__(self, boundary, capacity=4096):
        self.boundary = boundary
        self.processor = boundary.processor
        self.condition = threading.Condition(threading.Lock())
        self.queue = deque()
        self.capacity = capacity
        self.active = False
        self.revision = 0
        self.token = None
        self.fault = None
        self.metrics = {}

    def owns_convergence(self):
        return self.boundary.convergence_lock.owner == threading.get_ident()

    def stopped(self):
        stop = getattr(self.processor, "_stop_requested", None)
        event = getattr(self.boundary, "work_stop", None)
        return bool((stop and stop()) or (event and event.is_set()))

    def identity(self):
        p = self.processor
        return (self.revision, p.reconnect_generation,
                p.market_connection_session_id, p.public_connection_session_id)

    @contextmanager
    def session_change(self):
        # Preserve Stage1's pre-COMPLETE evidence callbacks. COMPLETE changes
        # under the same state lock; never acquire convergence while holding it.
        with self.boundary.lock:
            if not self.boundary.complete:
                yield
                return
        # Post-COMPLETE session mutation and commit serialize; enqueue does not.
        with self.boundary.convergence_lock:
            with self.condition:
                self.revision += 1
                yield

    def abort(self, reason):
        with self.condition:
            self.fault = reason
            self.processor._halted = True
            self.processor.entry_admission_enabled = False
            self.condition.notify_all()
        self.processor.state._set(ExecutionMarketState.UNSAFE, reason)
        return [{"status": "PUBLIC_DEFERRED_RESTART_REQUIRED", "reason": reason}]

    def begin(self):
        if not self.owns_convergence() or self.boundary.convergence_lock.depth != 1:
            raise RuntimeError("PUBLIC_DEFER_REQUIRES_SINGLE_CONVERGENCE_OWNER")
        with self.condition:
            if self.active or self.fault:
                raise RuntimeError("PUBLIC_DEFER_ALREADY_ACTIVE_OR_FAILED")
            self.active = True
            self.token = self.identity()  # immutable session/generation authority
            self.metrics = {"enqueue_ns": deque(maxlen=4096), "fetch_outside_ns": 0,
                            "deferred_count": 0, "drain_ns": 0}

    def valid(self):
        with self.condition:
            return (self.active and not self.fault and not self.processor._halted
                    and self.token == self.identity() and not self.stopped())

    @contextmanager
    def outside_fetch(self):
        if not self.owns_convergence() or self.boundary.convergence_lock.depth != 1:
            raise RuntimeError("PUBLIC_DEFER_FETCH_LOCK_DEPTH")
        self.boundary.convergence_lock.release()
        start = time.perf_counter_ns()
        try:
            yield
        finally:
            self.metrics["fetch_outside_ns"] += time.perf_counter_ns() - start
            self.boundary.convergence_lock.acquire()

    def receive(self, payload, session):
        start = time.perf_counter_ns()
        with self.condition:
            if self.fault or self.stopped():
                return [{"status": "PUBLIC_DEFERRED_RESTART_REQUIRED", "reason": self.fault or "shutdown"}]
            if self.active:
                if len(self.queue) >= self.capacity:
                    self.fault = "PUBLIC_DEFERRED_BUFFER_OVERFLOW"
                    self.processor._halted = True
                    self.processor.entry_admission_enabled = False
                    self.condition.notify_all()
                    return [{"status": self.fault, "capacity": self.capacity}]
                self.queue.append((session, self.processor.reconnect_generation,
                                   self.revision, deepcopy(payload)))
                self.metrics["deferred_count"] += 1
                self.metrics["enqueue_ns"].append(time.perf_counter_ns() - start)
                return [{"status": "PUBLIC_RECEIVED_DEFERRED", "session": session}]
        with self.boundary.convergence_lock:
            # A recovery may begin between the first check and lock acquisition.
            with self.condition:
                retry = self.active
                fault = self.fault
            if retry:
                return self.receive(payload, session)
            if fault or self.stopped():
                return [{"status": "PUBLIC_DEFERRED_RESTART_REQUIRED", "reason": fault or "shutdown"}]
            if session != self.processor.public_connection_session_id:
                return self.abort("PUBLIC_SESSION_CHANGED_BEFORE_PUBLICATION")
            return self.boundary._publish_public(payload, session)

    def market(self, payload, session):
        # First catch-up handoff already owns convergence. Other MARKET callers
        # wait OUTSIDE that lock while the owning recovery fetches/drains.
        if self.owns_convergence():
            if session and session != self.processor.market_connection_session_id:
                return self.abort("MARKET_SESSION_CHANGED_BEFORE_PROCESSING")
            return self.processor._handle_market_ws_payload_ordered(payload, session)
        while True:
            with self.condition:
                while self.active and not self.fault and not self.stopped():
                    self.condition.wait(timeout=.1)
                if self.fault or self.stopped():
                    return [{"status": "PROCESSOR_RESTART_REQUIRED"}]
            with self.boundary.convergence_lock:
                with self.condition:
                    if self.active:
                        continue
                if session and session != self.processor.market_connection_session_id:
                    return self.abort("MARKET_SESSION_CHANGED_BEFORE_PROCESSING")
                return self.processor._handle_market_ws_payload_ordered(payload, session)

    def drain(self):
        start = time.perf_counter_ns()
        while True:
            if not self.valid():
                return self.abort("PUBLIC_DEFER_RECOVERY_IDENTITY_INVALIDATED")
            with self.condition:
                if not self.queue:
                    self.active = False  # atomic empty-FIFO -> direct handoff
                    self.token = None
                    self.metrics["drain_ns"] = time.perf_counter_ns() - start
                    self.condition.notify_all()
                    return []
                session, generation, revision, payload = self.queue.popleft()
            if (session != self.processor.public_connection_session_id or
                    generation != self.processor.reconnect_generation or revision != self.revision):
                return self.abort("PUBLIC_DEFERRED_ITEM_IDENTITY_INVALIDATED")
            result = self.boundary._publish_public(payload, session)
            if not result or result[-1].get("status") != "BOOK_TICKER_DISPATCHED":
                return self.abort("PUBLIC_DEFERRED_PUBLICATION_FAILED")


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

    recovery_batch_size: int = 512
    recovery_action_limit: int = 4096
    economic_dispatch_enabled: bool = True
    entry_admission_enabled: bool = True
    _halted: bool = False
    recovery_barrier: Callable[[], Any] | None = None

    def _bounded_append(self, target, item):
        target.append(item)
        if len(target) > self.recovery_action_limit:
            del target[:len(target) - self.recovery_action_limit]

    def _sync_engine_outputs(self):
        # Successful effects precede market checkpoint. Only changed files need
        # another sync. Mid-operation atomicity remains a separate protocol.
        signatures = getattr(self, "_output_signatures", {})
        paths = []
        books = getattr(self.engine, "books", None)
        if books is not None:
            paths.extend(books._path(table) for table in books.TABLES)
        sleeves = getattr(self.engine, "sleeves", None)
        if sleeves is not None and sleeves.path is not None and sleeves.path.exists():
            paths.append(sleeves.path)
        parents = set()
        for path in paths:
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            if stat.st_size and signatures.get(str(path)) != signature:
                with path.open("rb") as fh:
                    os.fsync(fh.fileno())
                parents.add(path.parent)
            signatures[str(path)] = signature
        for parent in parents:
            fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        self._output_signatures = signatures

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
        enable_segmented_wal: bool = False,
        wal_segment_max_bytes: int = 64 * 1024 * 1024,
        wal_archive_batch_rows: int = 65_536,
        wal_delete_verified_plaintext: bool = False,
        wal_plaintext_retention_hours: float = 0.0,
        wal_warning_size_bytes: int = 10 * 1024**3,
        wal_critical_size_bytes: int = 20 * 1024**3,
        stop_requested: Callable[[], bool] | None = None,
        defer_economic_dispatch: bool = False,
    ) -> "ExecutionMarketProcessor":
        wal_root = epoch_root / "execution_market_wal"
        wal = ExecutionMarketWAL(
            wal_root,
            paper_epoch_id=paper_epoch_id,
            enable_segmented_storage=enable_segmented_wal,
            segment_max_bytes=wal_segment_max_bytes,
            archive_batch_rows=wal_archive_batch_rows,
            delete_verified_plaintext=wal_delete_verified_plaintext,
            plaintext_retention_hours=wal_plaintext_retention_hours,
            warning_size_bytes=wal_warning_size_bytes,
            critical_size_bytes=wal_critical_size_bytes,
        )
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
        proc.economic_dispatch_enabled = not defer_economic_dispatch
        proc.entry_admission_enabled = not defer_economic_dispatch
        proc._stop_requested = stop_requested
        proc._checkpoint_path = ck_path
        if not defer_economic_dispatch:
            proc.replay_from_checkpoint(stop_requested=stop_requested)
        wal.start_background_compaction()
        if checkpoint.last_processed_agg_trade_id is not None:
            state.last_confirmed_agg_trade_id = checkpoint.last_processed_agg_trade_id
        return proc

    @property
    def checkpoint_path(self) -> Path:
        return getattr(self, "_checkpoint_path", Path(self.engine.epoch_root) / "execution_market_checkpoint.json")

    @property
    def connection_session_id(self) -> str:
        """Backward-compatible alias for PUBLIC route session id."""
        return self.public_connection_session_id

    def execution_market_ready_for_entry(self) -> bool:
        if not self.entry_admission_enabled:
            return False
        boundary = getattr(self, "fresh_live_boundary", None)
        return self.state.execution_market_ready_for_entry() and (boundary is None or boundary.entry_ready())

    def on_public_websocket_connected(self) -> None:
        gate = self._public_defer_gate()
        if gate is not None:
            with gate.session_change():
                return self._on_public_websocket_connected_ordered()
        return self._on_public_websocket_connected_ordered()

    def _on_public_websocket_connected_ordered(self) -> None:
        self.public_connection_session_id = str(uuid.uuid4())
        self.reconnect_generation += 1
        self.state.on_public_connected()

    def on_public_websocket_disconnected(self) -> None:
        gate = self._public_defer_gate()
        if gate is not None:
            with gate.session_change():
                return self._on_public_websocket_disconnected_ordered()
        return self._on_public_websocket_disconnected_ordered()

    def _on_public_websocket_disconnected_ordered(self) -> None:
        self.state.on_public_disconnected()

    def on_market_websocket_connected(self) -> None:
        gate = self._public_defer_gate()
        if gate is not None:
            with gate.session_change():
                return self._on_market_websocket_connected_ordered()
        return self._on_market_websocket_connected_ordered()

    def _on_market_websocket_connected_ordered(self) -> None:
        self.market_connection_session_id = str(uuid.uuid4())
        self.reconnect_generation += 1
        self.state.on_market_connected()

    def on_market_websocket_disconnected(self) -> None:
        gate = self._public_defer_gate()
        if gate is not None:
            with gate.session_change():
                return self._on_market_websocket_disconnected_ordered()
        return self._on_market_websocket_disconnected_ordered()

    def _on_market_websocket_disconnected_ordered(self) -> None:
        self.state.on_market_disconnected()

    def on_websocket_connected(self) -> None:
        gate = self._public_defer_gate()
        if gate is not None:
            with gate.session_change():
                return self._on_websocket_connected_ordered()
        return self._on_websocket_connected_ordered()

    def _on_websocket_connected_ordered(self) -> None:
        self.public_connection_session_id = str(uuid.uuid4())
        self.market_connection_session_id = str(uuid.uuid4())
        self.reconnect_generation += 1
        self.state.on_websocket_connected()

    def on_websocket_disconnected(self) -> None:
        gate = self._public_defer_gate()
        if gate is not None:
            with gate.session_change():
                return self._on_websocket_disconnected_ordered()
        return self._on_websocket_disconnected_ordered()

    def _on_websocket_disconnected_ordered(self) -> None:
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

    def _public_defer_gate(self):
        boundary = getattr(self, "fresh_live_boundary", None)
        return getattr(boundary, "public_defer", None)

    def handle_market_ws_payload(self, payload, connection_session_id=None):
        gate = self._public_defer_gate()
        if gate is not None and gate.boundary.complete:
            return gate.market(payload, connection_session_id)
        return self._handle_market_ws_payload_ordered(payload, connection_session_id)

    def _handle_market_ws_payload_ordered(
        self,
        payload: dict[str, Any],
        connection_session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        data = payload.get("data") or payload
        stream = str(payload.get("stream") or "")
        if "aggTrade" not in stream and data.get("e") != "aggTrade":
            return []
        mono = time.monotonic_ns()
        ts = _utc_iso()
        event = normalize_futures_agg_trade(
            data,
            symbol=self.symbol,
            connection_session_id=connection_session_id or self.market_connection_session_id,
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

    def _append_with_retry(
        self,
        event: dict[str, Any],
        *,
        allow_degraded_protective: bool = False,
        fsync: bool = True,
        update_state: bool = True,
    ) -> WalAppendResult:
        last = WalAppendResult(ok=False, error="unknown", retryable=True)
        for _ in range(2):
            last = self.wal.append(event, fsync=fsync, update_state=update_state)
            if last.ok:
                self.state.on_wal_append_success()
                if last.wal_offset is not None:
                    self._bounded_append(self.wal_append_log, last.wal_offset)
                return last
            self.state.on_wal_append_failure(retryable=bool(last.retryable))
        if allow_degraded_protective:
            return last
        return last

    def _process_book_ticker(self, event: dict[str, Any]) -> dict[str, Any]:
        if not self.economic_dispatch_enabled:
            raise RuntimeError("RESUME_ECONOMIC_DISPATCH_NOT_ADMITTED")
        # Phase C: soft durability for BBO ticks. Fill pricing uses in-memory
        # BBO updated below; trade volume lives on AGG_TRADE (hard fsync).
        append = self._append_with_retry(event, fsync=False, update_state=False)
        if not append.ok:
            return {"status": "WAL_APPEND_FAILED", "event_type": EVENT_BOOK_TICKER}
        bid = float(event["best_bid"])
        ask = float(event["best_ask"])
        if bid <= 0 or ask <= 0:
            return {"status": "INVALID_BBO"}
        self.state.note_book_ticker(receive_monotonic_ns=int(event["local_receive_monotonic_ns"]))
        self._dispatch_book_ticker(event, wal_offset=append.wal_offset)
        self.wal.maybe_periodic_flush(
            now_mono_ns=int(event["local_receive_monotonic_ns"])
        )
        return {"status": "BOOK_TICKER_DISPATCHED", "wal_offset": append.wal_offset}

    def _process_agg_trade_live(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.economic_dispatch_enabled:
            raise RuntimeError("RESUME_ECONOMIC_DISPATCH_NOT_ADMITTED")
        if self._halted:
            return [{"status": "PROCESSOR_RESTART_REQUIRED"}]
        agg_id = int(event["aggregate_trade_id"])
        if agg_id in self.checkpoint.processed_agg_trade_ids:
            return [{"status": "DUPLICATE_AGG_TRADE_SKIPPED", "aggregate_trade_id": agg_id}]
        expected = self.state.last_confirmed_agg_trade_id
        if expected is not None and agg_id > expected + 1:
            return self._recover_gap_then_process(
                event,
                first_missing_id=expected + 1,
                last_missing_id=agg_id - 1,
            )
        if expected is not None and agg_id <= expected:
            return [{"status": "DUPLICATE_AGG_TRADE_SKIPPED", "aggregate_trade_id": agg_id}]
        return [self._persist_and_dispatch_agg_trade(event)]

    def _recover_gap_then_process(self, live_event, *, first_missing_id, last_missing_id):
        gate = self._public_defer_gate()
        if gate is None or not gate.boundary.complete:
            return self._recover_gap_then_process_ordered(live_event,
                first_missing_id=first_missing_id, last_missing_id=last_missing_id)
        gate.begin()
        try:
            result = self._recover_gap_then_process_ordered(live_event,
                first_missing_id=first_missing_id, last_missing_id=last_missing_id)
            if not gate.valid():
                return gate.abort("PUBLIC_DEFER_RECOVERY_IDENTITY_INVALIDATED")
            if self.state.unresolved_gap or result[-1].get("status") != "AGG_TRADE_DISPATCHED":
                return result + gate.abort("PUBLIC_DEFER_RECOVERY_FAILED")
            failure = gate.drain()
            return result + failure
        except BaseException:
            gate.abort("PUBLIC_DEFER_RECOVERY_EXCEPTION")
            raise

    def _prepare_gap_batch(self, first, last, live_event):
        gate = self._public_defer_gate()
        use_gate = gate is not None and gate.active
        def prepare():
            rows = sorted(self.fetch_agg_trades(self.symbol, first, last), key=lambda row: int(row["a"]))
            ids = [int(row["a"]) for row in rows]
            if len(ids) != last - first + 1 or ids != list(range(first, last + 1)):
                return None, {"status": "BACKFILL_INCOMPLETE", "error": f"expected={first}-{last}; got_count={len(ids)}"}
            events = [normalize_rest_agg_trade(row, symbol=self.symbol,
                connection_session_id=gate.token[2] if use_gate else self.market_connection_session_id,
                receive_monotonic_ns=int(live_event["local_receive_monotonic_ns"]),
                receive_timestamp=str(live_event["local_receive_timestamp"])) for row in rows]
            return events, None
        if use_gate:
            with gate.outside_fetch():
                prepared = prepare()
            if not gate.valid():
                return None, {"status": "BACKFILL_IDENTITY_INVALIDATED", "error": "session/generation/shutdown/overflow changed"}
            return prepared
        return prepare()

    def _recover_gap_then_process_ordered(
        self,
        live_event: dict[str, Any],
        *,
        first_missing_id: int,
        last_missing_id: int,
    ) -> list[dict[str, Any]]:
        self.state.on_gap_detected(
            first_missing=first_missing_id,
            last_missing=last_missing_id,
        )
        actions: list[dict[str, Any]] = []
        if first_missing_id > last_missing_id:
            actions.append(self._persist_and_dispatch_agg_trade(live_event))
            return actions
        # Each REST request and durable group is bounded, never the entire gap.
        for first in range(first_missing_id, last_missing_id + 1, self.recovery_batch_size):
            last = min(last_missing_id, first + self.recovery_batch_size - 1)
            try:
                events, failure = self._prepare_gap_batch(first, last, live_event)
            except Exception as exc:
                self.state.on_backfill_failed(str(exc))
                return actions + [{"status": "BACKFILL_FAILED", "error": str(exc)}]
            if failure:
                self.state.on_backfill_failed(failure["error"])
                return actions + [failure]
            appends = self.wal.append_batch(events, max_events=self.recovery_batch_size)
            if len(appends) != len(events) or any(not append.ok for append in appends):
                error = appends[0].error if appends else "empty_batch"
                self.state.on_wal_append_failure(retryable=False)
                self.state.on_backfill_failed(str(error))
                self._halted = True
                return actions + [{"status": "WAL_BATCH_FAILED", "error": error}]
            checkpoint_before = self.checkpoint.to_dict()
            try:
                for event, append in zip(events, appends):
                    self._bounded_append(self.wal_append_log, append.wal_offset)
                    action = self._dispatch_agg_trade(event, wal_offset=append.wal_offset,
                                                      save_checkpoint=False)
                    self._bounded_append(actions, action)
                    self.state.on_backfill_progress(aggregate_trade_id=int(event["aggregate_trade_id"]))
                self._sync_engine_outputs()
                self.checkpoint.save(self.checkpoint_path)
            except Exception as exc:
                # No acknowledged batch checkpoint and no continuation in this
                # process after uncertain engine output / checkpoint publication.
                self.checkpoint = ExecutionMarketCheckpoint.from_dict(checkpoint_before)
                self._halted = True
                self.state.on_backfill_failed(f"batch_processing_failed:{exc}")
                raise
        live_action = self._persist_and_dispatch_agg_trade(live_event)
        self._bounded_append(actions, live_action)
        if live_action.get("status") == "AGG_TRADE_DISPATCHED":
            self._resolve_gap(last_confirmed=int(live_event["aggregate_trade_id"]))
        else:
            self.state.on_backfill_failed(
                f"live_durable_acceptance_failed:{live_event['aggregate_trade_id']}"
            )
        return actions

    def _resolve_gap(self, *, last_confirmed: int) -> None:
        if self.recovery_barrier is not None:
            try:
                self.recovery_barrier()
            except BaseException:
                self._halted = True
                self.state._set(ExecutionMarketState.UNSAFE, "recovery_command_barrier_failed")
                raise
        self.state.on_gap_resolved(last_confirmed=last_confirmed)

    def _persist_and_dispatch_agg_trade(self, event: dict[str, Any]) -> dict[str, Any]:
        # The hard AGG_TRADE append fsyncs the whole WAL, including preceding
        # soft BBO bytes, before dispatch. Avoid a second identical prefix sync.
        agg_id = int(event["aggregate_trade_id"])
        protective = self._agg_trade_crosses_protective(float(event["price"]))
        append = self._append_with_retry(event, allow_degraded_protective=protective)
        if not append.ok:
            # A failed hard append did not confirm the soft prefix. Preserve
            # its existing sync attempt before the unchanged failure/exit path.
            self.wal.flush_durable(reason="pre_agg_trade")
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
            self._resolve_gap(last_confirmed=agg_id)
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
        if not self.economic_dispatch_enabled:
            raise RuntimeError("RESUME_ECONOMIC_DISPATCH_NOT_ADMITTED")
        self._bounded_append(self.dispatch_log, (EVENT_BOOK_TICKER, wal_offset))
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
        save_checkpoint: bool = True,
    ) -> dict[str, Any]:
        if not self.economic_dispatch_enabled:
            raise RuntimeError("RESUME_ECONOMIC_DISPATCH_NOT_ADMITTED")
        self._bounded_append(self.dispatch_log, (EVENT_AGG_TRADE, wal_offset))
        provenance = self._provenance(event, wal_offset)
        if durability_degraded:
            provenance["durability_degraded"] = True
            provenance["durability_reason"] = PROTECTIVE_EXIT_DURABILITY_DEGRADED
        checkpoint_before = self.checkpoint.to_dict() if save_checkpoint else None
        try:
            result = self.engine.update_from_trade(
                price=float(event["price"]),
                receive_monotonic_ns=int(event["local_receive_monotonic_ns"]),
                receive_timestamp=event.get("local_receive_timestamp"),
                source_event_id=event.get("source_event_id"),
                market_provenance=provenance,
            )
            agg_id = int(event["aggregate_trade_id"])
            self.checkpoint.note_processed(
                aggregate_trade_id=agg_id,
                wal_offset=int(wal_offset or self.checkpoint.last_processed_wal_offset),
            )
            if save_checkpoint:
                self._sync_engine_outputs()
                self.checkpoint.save(self.checkpoint_path)
        except BaseException:
            if checkpoint_before is not None:
                self.checkpoint = ExecutionMarketCheckpoint.from_dict(checkpoint_before)
            self._halted = True
            self.state._set(ExecutionMarketState.UNSAFE, "execution_commit_or_checkpoint_failed")
            raise
        # Queue delivery and REST catch-up do not make old trades fresh.
        # Apply the existing max_agg_trade_age_ms to the actual exchange trade.
        exchange_ms = int(event.get("exchange_trade_timestamp") or 0)
        exchange_age_ns = max(0, time.time_ns() - exchange_ms * 1_000_000)
        freshness_mono = min(int(event["local_receive_monotonic_ns"]),
                             time.monotonic_ns() - exchange_age_ns)
        self.state.note_agg_trade(
            aggregate_trade_id=agg_id,
            receive_monotonic_ns=freshness_mono,
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

    def replay_from_checkpoint(self, *, stop_requested: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
        if not self.economic_dispatch_enabled:
            return []
        actions: list[dict[str, Any]] = []
        for event in self.wal.iter_from_offset(self.checkpoint.last_processed_wal_offset):
            if stop_requested is not None and stop_requested():
                self._halted = True
                raise ReplayInterrupted("STARTUP_REPLAY_STOP_REQUESTED")
            if event.get("event_type") == EVENT_BOOK_TICKER:
                self._dispatch_book_ticker(event, wal_offset=int(event.get("wal_offset") or 0))
                self._bounded_append(actions, {"status": "REPLAY_BOOK_TICKER", "wal_offset": event.get("wal_offset")})
            elif event.get("event_type") == EVENT_AGG_TRADE:
                agg_id = int(event["aggregate_trade_id"])
                if agg_id in self.checkpoint.processed_agg_trade_ids:
                    continue
                self._bounded_append(actions,
                    self._dispatch_agg_trade(event, wal_offset=int(event.get("wal_offset") or 0))
                )
        return actions

    def snapshot(self) -> dict[str, Any]:
        return {
            "public_connection_session_id": self.public_connection_session_id,
            "market_connection_session_id": self.market_connection_session_id,
            "wal": {
                "root": str(self.wal.root),
                "storage_mode": self.wal.storage_mode,
                "last_offset": self.wal.last_offset,
                "last_confirmed_agg_trade_id": self.wal.last_confirmed_agg_trade_id,
                "active_segment_start_offset": self.wal.active_start_offset,
                "closed_segment_count": self.wal.closed_segment_count,
                "archive_count": self.wal.archive_count,
                "archive_error": self.wal.archive_error,
                "retention_error": self.wal.retention_error,
                "wal_size_bytes": self.wal.wal_size_bytes,
                "wal_segments_count": self.wal.wal_segments_count,
                "wal_oldest_event_timestamp": self.wal.wal_oldest_event_timestamp,
                "wal_retention_status": self.wal.wal_retention_status,
                "fsync_count": self.wal.fsync_count,
                "periodic_fsync_count": self.wal.periodic_fsync_count,
                "state_write_count": self.wal.state_write_count,
                "soft_dirty": self.wal._soft_dirty,
            },
            "checkpoint": self.checkpoint.to_dict(),
            "state": {**self.state.snapshot(), "entry_allowed": self.execution_market_ready_for_entry()},
            "fresh_live_boundary": ({**{key: value for key, value in self.fresh_live_boundary.proof.items() if key not in {"rest_tail", "first_ws_event"}}, "admission_committed": self.fresh_live_boundary.admitted} if getattr(self, "fresh_live_boundary", None) and self.fresh_live_boundary.proof else None),
        }
