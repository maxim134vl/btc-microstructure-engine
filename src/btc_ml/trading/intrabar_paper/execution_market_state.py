"""Execution market-data state machine for LIVE1B."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionMarketState(str, Enum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    UNSAFE = "UNSAFE"


PROTECTIVE_EXIT_DURABILITY_DEGRADED = "PROTECTIVE_EXIT_DURABILITY_DEGRADED"


@dataclass
class ExecutionMarketStateMachine:
    max_bbo_age_ms: float
    max_agg_trade_age_ms: float
    wal_persistent_failure_threshold: int = 3
    state: ExecutionMarketState = ExecutionMarketState.STARTING
    public_ws_connected: bool = False
    market_ws_connected: bool = False
    unresolved_gap: bool = False
    wal_write_failures: int = 0
    last_confirmed_agg_trade_id: int | None = None
    last_agg_trade_monotonic_ns: int | None = None
    last_book_ticker_monotonic_ns: int | None = None
    last_transition_reason: str | None = None
    _history: list[tuple[str, ExecutionMarketState]] = field(default_factory=list)

    def _set(self, new_state: ExecutionMarketState, reason: str) -> None:
        if self.state != new_state:
            self._history.append((reason, new_state))
        self.state = new_state
        self.last_transition_reason = reason

    def on_start(self) -> None:
        self._set(ExecutionMarketState.STARTING, "manager_start")

    @property
    def websocket_connected(self) -> bool:
        return self.public_ws_connected and self.market_ws_connected

    def on_public_connected(self) -> None:
        self.public_ws_connected = True
        self._evaluate_connection_state("public_ws_connected")

    def on_public_disconnected(self) -> None:
        self.public_ws_connected = False
        if self.state != ExecutionMarketState.UNSAFE:
            self._set(ExecutionMarketState.DEGRADED, "public_ws_disconnected")

    def on_market_connected(self) -> None:
        self.market_ws_connected = True
        self._evaluate_connection_state("market_ws_connected")

    def on_market_disconnected(self) -> None:
        self.market_ws_connected = False
        if self.state != ExecutionMarketState.UNSAFE:
            self._set(ExecutionMarketState.DEGRADED, "market_ws_disconnected")

    def on_websocket_connected(self) -> None:
        """Backward-compatible helper: both routes connected."""
        self.public_ws_connected = True
        self.market_ws_connected = True
        self._evaluate_connection_state("legacy_ws_connected")

    def on_websocket_disconnected(self) -> None:
        """Backward-compatible helper: both routes disconnected."""
        self.public_ws_connected = False
        self.market_ws_connected = False
        if self.state != ExecutionMarketState.UNSAFE:
            self._set(ExecutionMarketState.DEGRADED, "ws_disconnected")

    def _evaluate_connection_state(self, reason: str) -> None:
        if not self.public_ws_connected or not self.market_ws_connected:
            if self.state not in {
                ExecutionMarketState.UNSAFE,
                ExecutionMarketState.RECOVERING,
            }:
                self._set(ExecutionMarketState.DEGRADED, reason)
            return
        if self.unresolved_gap:
            self._set(ExecutionMarketState.RECOVERING, "ws_connected_with_gap")
        elif self.state in {ExecutionMarketState.STARTING, ExecutionMarketState.DEGRADED}:
            self._set(ExecutionMarketState.DEGRADED, "ws_connected_awaiting_validation")

    def on_gap_detected(self) -> None:
        self.unresolved_gap = True
        self._set(ExecutionMarketState.RECOVERING, "agg_trade_gap")

    def on_gap_resolved(self, *, last_confirmed: int) -> None:
        self.unresolved_gap = False
        self.last_confirmed_agg_trade_id = last_confirmed
        self._maybe_promote_healthy("gap_resolved")

    def on_wal_append_success(self) -> None:
        self.wal_write_failures = 0

    def on_wal_append_failure(self, *, retryable: bool) -> None:
        if not retryable:
            self._set(ExecutionMarketState.UNSAFE, "wal_non_retryable_failure")
            return
        self.wal_write_failures += 1
        if self.wal_write_failures >= self.wal_persistent_failure_threshold:
            self._set(ExecutionMarketState.UNSAFE, "wal_persistent_failure")
        elif self.state != ExecutionMarketState.UNSAFE:
            self._set(ExecutionMarketState.DEGRADED, "wal_transient_failure")

    def on_backfill_failed(self) -> None:
        self.unresolved_gap = True
        self._set(ExecutionMarketState.UNSAFE, "backfill_failed")

    def note_agg_trade(self, *, aggregate_trade_id: int, receive_monotonic_ns: int) -> None:
        self.last_confirmed_agg_trade_id = aggregate_trade_id
        self.last_agg_trade_monotonic_ns = receive_monotonic_ns
        if self.state == ExecutionMarketState.RECOVERING and not self.unresolved_gap:
            self._maybe_promote_healthy("agg_trade_processed")

    def note_book_ticker(self, *, receive_monotonic_ns: int) -> None:
        self.last_book_ticker_monotonic_ns = receive_monotonic_ns
        if self.state in {ExecutionMarketState.STARTING, ExecutionMarketState.DEGRADED} and not self.unresolved_gap:
            self._maybe_promote_healthy("book_ticker_fresh")

    def _age_ms(self, mono: int | None) -> float | None:
        if mono is None:
            return None
        return max(0.0, (time.monotonic_ns() - int(mono)) / 1_000_000.0)

    def _maybe_promote_healthy(self, reason: str) -> None:
        if self.state == ExecutionMarketState.UNSAFE:
            return
        if not self.public_ws_connected or not self.market_ws_connected:
            return
        if self.unresolved_gap:
            return
        if self.wal_write_failures > 0:
            return
        if self.last_confirmed_agg_trade_id is None:
            return
        agg_age = self._age_ms(self.last_agg_trade_monotonic_ns)
        book_age = self._age_ms(self.last_book_ticker_monotonic_ns)
        if agg_age is None or agg_age > self.max_agg_trade_age_ms:
            return
        if book_age is None or book_age > self.max_bbo_age_ms:
            if self.state != ExecutionMarketState.DEGRADED:
                self._set(ExecutionMarketState.DEGRADED, "book_ticker_stale")
            return
        self._set(ExecutionMarketState.HEALTHY, reason)

    def execution_market_ready_for_entry(self) -> bool:
        return self.state == ExecutionMarketState.HEALTHY

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "public_ws_connected": self.public_ws_connected,
            "market_ws_connected": self.market_ws_connected,
            "websocket_connected": self.websocket_connected,
            "unresolved_gap": self.unresolved_gap,
            "wal_write_failures": self.wal_write_failures,
            "last_confirmed_agg_trade_id": self.last_confirmed_agg_trade_id,
            "last_agg_trade_age_ms": self._age_ms(self.last_agg_trade_monotonic_ns),
            "last_book_ticker_age_ms": self._age_ms(self.last_book_ticker_monotonic_ns),
            "last_transition_reason": self.last_transition_reason,
            "entry_allowed": self.execution_market_ready_for_entry(),
        }
