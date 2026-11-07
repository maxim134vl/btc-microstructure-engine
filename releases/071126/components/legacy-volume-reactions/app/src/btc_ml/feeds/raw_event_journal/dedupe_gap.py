"""Duplicate and sequence-gap policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Set, Tuple

from .schemas import StreamType


@dataclass
class DuplicateTracker:
    """In-memory dedupe window for a single process lifetime."""

    agg_keys: Set[Tuple[str, int]] = field(default_factory=set)
    book_keys: Set[Tuple[str, int]] = field(default_factory=set)
    book_hash_keys: Set[Tuple[str, str, str]] = field(default_factory=set)
    dropped: int = 0

    def is_duplicate_agg(self, symbol: str, aggregate_trade_id: Optional[int]) -> bool:
        if aggregate_trade_id is None:
            return False
        key = (symbol, int(aggregate_trade_id))
        if key in self.agg_keys:
            self.dropped += 1
            return True
        self.agg_keys.add(key)
        return False

    def is_duplicate_book(
        self,
        symbol: str,
        update_id: Optional[int],
        *,
        raw_payload_hash: str,
        connection_session_id: str,
    ) -> bool:
        if update_id is not None:
            key = (symbol, int(update_id))
            if key in self.book_keys:
                self.dropped += 1
                return True
            self.book_keys.add(key)
            return False
        hkey = (symbol, raw_payload_hash, connection_session_id)
        if hkey in self.book_hash_keys:
            self.dropped += 1
            return True
        self.book_hash_keys.add(hkey)
        return False


@dataclass
class GapReport:
    stream: str
    gap_type: str
    previous: Any
    current: Any
    details: dict[str, Any]


@dataclass
class SequenceMonitor:
    last_agg_trade_id: Optional[int] = None
    last_agg_last_trade_id: Optional[int] = None
    last_book_update_id: Optional[int] = None
    gap_count: int = 0
    gaps: list[GapReport] = field(default_factory=list)

    def check_agg_trade(self, event: Mapping[str, Any]) -> Optional[GapReport]:
        agg_id = event.get("aggregate_trade_id")
        first_id = event.get("first_trade_id")
        last_id = event.get("last_trade_id")
        report: Optional[GapReport] = None

        if self.last_agg_trade_id is not None and agg_id is not None:
            expected = self.last_agg_trade_id + 1
            if int(agg_id) > expected:
                report = GapReport(
                    stream=StreamType.AGG_TRADE.value,
                    gap_type="AGGREGATE_TRADE_ID_GAP",
                    previous=self.last_agg_trade_id,
                    current=agg_id,
                    details={"expected_next": expected, "delta": int(agg_id) - self.last_agg_trade_id},
                )
                self.gap_count += 1
                self.gaps.append(report)
            elif int(agg_id) < self.last_agg_trade_id:
                # Out-of-order / rewind — not counted as sequence gap for continuity,
                # but recorded as operational anomaly for reader.
                report = GapReport(
                    stream=StreamType.AGG_TRADE.value,
                    gap_type="AGGREGATE_TRADE_ID_REWIND",
                    previous=self.last_agg_trade_id,
                    current=agg_id,
                    details={},
                )
                self.gaps.append(report)

        if (
            report is None
            and self.last_agg_last_trade_id is not None
            and first_id is not None
            and int(first_id) > self.last_agg_last_trade_id + 1
        ):
            report = GapReport(
                stream=StreamType.AGG_TRADE.value,
                gap_type="TRADE_ID_RANGE_GAP",
                previous=self.last_agg_last_trade_id,
                current=first_id,
                details={"expected_next_first": self.last_agg_last_trade_id + 1},
            )
            self.gap_count += 1
            self.gaps.append(report)

        if agg_id is not None:
            if self.last_agg_trade_id is None or int(agg_id) > self.last_agg_trade_id:
                self.last_agg_trade_id = int(agg_id)
        if last_id is not None:
            if self.last_agg_last_trade_id is None or int(last_id) > self.last_agg_last_trade_id:
                self.last_agg_last_trade_id = int(last_id)
        return report

    def check_book_ticker(self, event: Mapping[str, Any]) -> Optional[GapReport]:
        """bookTicker update_id is monotonic increasing but NOT guaranteed +1.

        We only flag large backward jumps (rewind). Forward jumps are not SEQUENCE_GAP.
        """
        update_id = event.get("update_id")
        report: Optional[GapReport] = None
        if self.last_book_update_id is not None and update_id is not None:
            if int(update_id) < self.last_book_update_id:
                report = GapReport(
                    stream=StreamType.BOOK_TICKER.value,
                    gap_type="UPDATE_ID_REWIND",
                    previous=self.last_book_update_id,
                    current=update_id,
                    details={},
                )
                self.gaps.append(report)
                # Do not increment gap_count for rewind-only; operational only.
            elif int(update_id) > self.last_book_update_id:
                # Normal forward progress — not a gap under Binance semantics.
                pass
        if update_id is not None:
            if self.last_book_update_id is None or int(update_id) > self.last_book_update_id:
                self.last_book_update_id = int(update_id)
        return report
