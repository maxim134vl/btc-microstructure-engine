"""Durable checkpoint for execution market WAL consumer."""

from __future__ import annotations

import json
import heapq
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RECENT_PROCESSED_AGG_TRADE_IDS_LIMIT = 4096


@dataclass
class ExecutionMarketCheckpoint:
    paper_epoch_id: str
    last_processed_wal_offset: int = 0
    last_processed_agg_trade_id: int | None = None
    processed_agg_trade_ids: set[int] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_epoch_id": self.paper_epoch_id,
            "last_processed_wal_offset": int(self.last_processed_wal_offset),
            "last_processed_agg_trade_id": self.last_processed_agg_trade_id,
            "processed_agg_trade_ids": sorted(self.processed_agg_trade_ids),
        }

    def __post_init__(self) -> None:
        # Same highest-4096 set as the original sort/truncate, O(log N) per ID.
        self._recent_heap = list(self.processed_agg_trade_ids)
        heapq.heapify(self._recent_heap)

    def note_processed(self, *, aggregate_trade_id: int, wal_offset: int) -> None:
        agg_id = int(aggregate_trade_id)
        self.last_processed_wal_offset = int(wal_offset)
        self.last_processed_agg_trade_id = agg_id
        if agg_id in self.processed_agg_trade_ids:
            return
        if len(self.processed_agg_trade_ids) < RECENT_PROCESSED_AGG_TRADE_IDS_LIMIT:
            self.processed_agg_trade_ids.add(agg_id)
            heapq.heappush(self._recent_heap, agg_id)
        elif agg_id > self._recent_heap[0]:
            removed = heapq.heapreplace(self._recent_heap, agg_id)
            self.processed_agg_trade_ids.remove(removed)
            self.processed_agg_trade_ids.add(agg_id)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExecutionMarketCheckpoint":
        stored = raw.get("processed_agg_trade_ids")
        if isinstance(stored, dict):
            if set(stored) != {"encoding", "ranges"} or stored["encoding"] != "inclusive_ranges_v1":
                raise ValueError("CHECKPOINT_ID_ENCODING_INVALID")
            ranges = stored["ranges"]
            if not isinstance(ranges, list):
                raise ValueError("CHECKPOINT_ID_RANGES_INVALID")
            previous = None
            for pair in ranges:
                if (not isinstance(pair, list) or len(pair) != 2
                        or any(type(x) is not int for x in pair)
                        or pair[0] > pair[1]
                        or (previous is not None and pair[0] <= previous)):
                    raise ValueError("CHECKPOINT_ID_RANGE_INVALID")
                previous = pair[1]
            # Preserve the existing highest-4096 recovery rule without ever
            # expanding an arbitrarily large range into an unbounded list.
            ids = []
            for first, last in reversed(ranges):
                count = min(last - first + 1, RECENT_PROCESSED_AGG_TRADE_IDS_LIMIT - len(ids))
                if count:
                    ids.extend(range(last - count + 1, last + 1))
                if len(ids) == RECENT_PROCESSED_AGG_TRADE_IDS_LIMIT:
                    break
        elif stored is None or isinstance(stored, (list, tuple)):
            ids = sorted(int(x) for x in (stored or []))[-RECENT_PROCESSED_AGG_TRADE_IDS_LIMIT:]
        else:
            raise ValueError("CHECKPOINT_ID_SET_INVALID")
        return cls(
            paper_epoch_id=str(raw.get("paper_epoch_id") or ""),
            last_processed_wal_offset=int(raw.get("last_processed_wal_offset") or 0),
            last_processed_agg_trade_id=(
                int(raw["last_processed_agg_trade_id"])
                if raw.get("last_processed_agg_trade_id") is not None
                else None
            ),
            processed_agg_trade_ids=set(ids),
        )

    def save(self, path: Path, *, compact: bool = True) -> None:
        payload = self.to_dict()  # logical/in-memory interface remains V1
        if compact:
            ids = payload["processed_agg_trade_ids"]
            ranges = []
            for value in ids:
                if ranges and value == ranges[-1][1] + 1:
                    ranges[-1][1] = value
                else:
                    ranges.append([value, value])
            encoded_ids = {"encoding": "inclusive_ranges_v1", "ranges": ranges}
            # Sparse sets retain the smaller plain-list representation.
            size = lambda value: len(json.dumps(value, separators=(",", ":")))
            if size(encoded_ids) < size(ids):
                payload["processed_agg_trade_ids"] = encoded_ids
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) if compact
                   else json.dumps(payload, indent=2, sort_keys=True)) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    @classmethod
    def load(cls, path: Path, *, paper_epoch_id: str) -> "ExecutionMarketCheckpoint":
        if not path.exists():
            return cls(paper_epoch_id=paper_epoch_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            ck = cls.from_dict(raw)
            if ck.paper_epoch_id and ck.paper_epoch_id != paper_epoch_id:
                raise ValueError("CHECKPOINT_EPOCH_MISMATCH")
            ck.paper_epoch_id = paper_epoch_id
            return ck
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            # Existing invalid state must never silently become a fresh cursor.
            raise RuntimeError(f"EXECUTION_MARKET_CHECKPOINT_INVALID:{path}:{exc}") from exc
