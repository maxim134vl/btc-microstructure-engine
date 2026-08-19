"""Causal BBO store for LIVE1B paper fills."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CausalBBO:
    book_update_id: str | None
    best_bid: float
    best_ask: float
    receive_timestamp: str | None
    receive_monotonic_ns: int
    source_event_id: str | None = None

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0


class CausalBBOStore:
    """Keeps last causal BBO; never returns a future quote.

    Notes:
    - Context-event BBO and cognition ``event_monotonic_ns`` share one clock.
    - Manager websocket BBO uses the manager process clock; use
      ``resolve_local`` / TP-SL path for those updates — do not compare
      websocket mono against context-event mono.
    """

    def __init__(self) -> None:
        self._latest: CausalBBO | None = None
        self._latest_local: CausalBBO | None = None
        self.updates = 0

    @property
    def latest(self) -> CausalBBO | None:
        return self._latest or self._latest_local

    def update_from_book_ticker(
        self,
        *,
        best_bid: float,
        best_ask: float,
        receive_monotonic_ns: int,
        receive_timestamp: str | None = None,
        book_update_id: str | None = None,
        source_event_id: str | None = None,
        domain: str = "context",
    ) -> CausalBBO:
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            raise ValueError("invalid BBO")
        bbo = CausalBBO(
            book_update_id=book_update_id,
            best_bid=float(best_bid),
            best_ask=float(best_ask),
            receive_timestamp=receive_timestamp,
            receive_monotonic_ns=int(receive_monotonic_ns),
            source_event_id=source_event_id,
        )
        if domain == "local":
            if (
                self._latest_local is None
                or bbo.receive_monotonic_ns >= self._latest_local.receive_monotonic_ns
            ):
                self._latest_local = bbo
                self.updates += 1
            return bbo
        if self._latest is None or bbo.receive_monotonic_ns >= self._latest.receive_monotonic_ns:
            self._latest = bbo
            self.updates += 1
        return bbo

    def update_from_context_event(self, event: dict[str, Any]) -> CausalBBO | None:
        bid = event.get("best_bid")
        ask = event.get("best_ask")
        mono = event.get("bbo_receive_monotonic_ns") or event.get("event_monotonic_ns")
        if bid is None or ask is None or mono is None:
            return None
        try:
            return self.update_from_book_ticker(
                best_bid=float(bid),
                best_ask=float(ask),
                receive_monotonic_ns=int(mono),
                receive_timestamp=event.get("bbo_receive_timestamp") or event.get("event_timestamp"),
                book_update_id=str(event.get("book_update_id")) if event.get("book_update_id") is not None else None,
                source_event_id=str(event.get("context_event_id") or event.get("event_id") or ""),
                domain="context",
            )
        except (TypeError, ValueError):
            return None

    def resolve_causal(
        self,
        *,
        command_monotonic_ns: int,
        max_age_ms: float,
    ) -> tuple[CausalBBO | None, str | None, float | None]:
        """Resolve BBO in the context-event monotonic domain."""
        bbo = self._latest
        if bbo is None:
            return None, "ENTRY_BLOCKED_NO_CAUSAL_BBO", None
        if bbo.receive_monotonic_ns > int(command_monotonic_ns):
            return None, "ENTRY_BLOCKED_NO_CAUSAL_BBO", None
        age_ms = (int(command_monotonic_ns) - bbo.receive_monotonic_ns) / 1_000_000.0
        if age_ms > float(max_age_ms):
            return None, "ENTRY_BLOCKED_NO_CAUSAL_BBO", age_ms
        return bbo, None, age_ms

    def resolve_causal_exit(
        self,
        *,
        command_monotonic_ns: int,
        max_age_ms: float,
    ) -> tuple[CausalBBO | None, str | None, float | None]:
        bbo, reason, age = self.resolve_causal(
            command_monotonic_ns=command_monotonic_ns,
            max_age_ms=max_age_ms,
        )
        if reason == "ENTRY_BLOCKED_NO_CAUSAL_BBO":
            return None, "EXIT_PENDING_NO_CAUSAL_BBO", age
        return bbo, reason, age

    def resolve_local(
        self,
        *,
        command_monotonic_ns: int,
        max_age_ms: float,
    ) -> tuple[CausalBBO | None, str | None, float | None]:
        """Resolve manager-local websocket BBO (TP/SL path)."""
        bbo = self._latest_local
        if bbo is None:
            return None, "EXIT_PENDING_NO_CAUSAL_BBO", None
        if bbo.receive_monotonic_ns > int(command_monotonic_ns):
            return None, "EXIT_PENDING_NO_CAUSAL_BBO", None
        age_ms = (int(command_monotonic_ns) - bbo.receive_monotonic_ns) / 1_000_000.0
        if age_ms > float(max_age_ms):
            return None, "EXIT_PENDING_NO_CAUSAL_BBO", age_ms
        return bbo, None, age_ms

    def resolve_live_local_entry_bbo(
        self,
        *,
        max_age_ms: float,
        now_monotonic_ns: int | None = None,
    ) -> tuple[CausalBBO | None, str | None, float | None, str]:
        """Price an S4.1 OPEN from the execution-market websocket clock.

        Context-domain quotes live on the cognition monotonic clock and must
        not gate manager commands. Execution-market quotes use
        ``time.monotonic_ns()`` (same clock as the websocket ingest). A live
        local quote stamped a few ns after the command snapshot is still valid.
        """
        bbo = self._latest_local
        if bbo is None:
            return None, "ENTRY_BLOCKED_NO_CAUSAL_BBO", None, "local"
        now = int(now_monotonic_ns if now_monotonic_ns is not None else time.monotonic_ns())
        ref = now if now >= bbo.receive_monotonic_ns else bbo.receive_monotonic_ns
        age_ms = (ref - bbo.receive_monotonic_ns) / 1_000_000.0
        if age_ms > float(max_age_ms):
            return None, "ENTRY_BLOCKED_NO_CAUSAL_BBO", age_ms, "local"
        return bbo, None, age_ms, "local"

    def resolve_execution_entry_bbo(
        self,
        *,
        command_monotonic_ns: int,
        max_age_ms: float,
    ) -> tuple[CausalBBO | None, str | None, float | None, str]:
        """Price a paper ENTRY at processing time.

        Causal context-domain BBO remains the gate (quote attached on the
        decision path). Fill uses execution-market local BBO when present so a
        delayed closed-bar event is not filled at a historical quote embedded
        on the event. Falls back to the causal context BBO when no local
        market quote exists (cognition-only / unit-test path).
        """
        causal, reason, age_ms = self.resolve_causal(
            command_monotonic_ns=command_monotonic_ns,
            max_age_ms=max_age_ms,
        )
        if causal is None:
            return None, reason, age_ms, "context"
        local = self._latest_local
        if local is not None:
            return local, None, 0.0, "local"
        return causal, None, age_ms, "context"


def fill_price_for(*, side: str, action: str, bbo: CausalBBO) -> float:
    """Paper fill policy: LONG ENTRY=ask, SHORT ENTRY=bid; EXIT is the opposite.

    ENTRY uses this helper against the BBO returned by
    :meth:`CausalBBOStore.resolve_execution_entry_bbo`. Context occurrence
    price is provenance only and must not be passed here.
    """
    side_u = str(side).upper()
    act = str(action).upper()
    if act == "ENTRY":
        return bbo.best_ask if side_u == "LONG" else bbo.best_bid
    if act == "EXIT":
        return bbo.best_bid if side_u == "LONG" else bbo.best_ask
    raise ValueError(f"unknown action {action}")


def resolve_context_entry_price(event: dict[str, Any] | None, *candidates: Any) -> float | None:
    """Parse context-occurrence price for provenance / audit only.

    Never used as paper ENTRY fill, sizing input, or a LIVE execution blocker.
    Does not invent prices from BBO.
    """
    values: list[Any] = list(candidates)
    if isinstance(event, dict):
        for key in (
            "context_event_price",
            "price",
            "context_origin_price",
            "historical_context_event_price",
        ):
            if event.get(key) is not None:
                values.append(event.get(key))
    for raw in values:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text or text.lower() in {"nan", "nat", "none", "null", ""}:
            continue
        try:
            px = float(text)
        except (TypeError, ValueError):
            continue
        if px > 0.0 and px == px:  # finite and positive
            return px
    return None
