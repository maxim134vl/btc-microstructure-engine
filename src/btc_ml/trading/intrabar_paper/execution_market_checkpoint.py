"""Durable checkpoint for execution market WAL consumer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExecutionMarketCheckpoint":
        ids = raw.get("processed_agg_trade_ids") or []
        return cls(
            paper_epoch_id=str(raw.get("paper_epoch_id") or ""),
            last_processed_wal_offset=int(raw.get("last_processed_wal_offset") or 0),
            last_processed_agg_trade_id=(
                int(raw["last_processed_agg_trade_id"])
                if raw.get("last_processed_agg_trade_id") is not None
                else None
            ),
            processed_agg_trade_ids={int(x) for x in ids},
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path, *, paper_epoch_id: str) -> "ExecutionMarketCheckpoint":
        if not path.exists():
            return cls(paper_epoch_id=paper_epoch_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            ck = cls.from_dict(raw)
            if ck.paper_epoch_id and ck.paper_epoch_id != paper_epoch_id:
                return cls(paper_epoch_id=paper_epoch_id)
            ck.paper_epoch_id = paper_epoch_id
            return ck
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return cls(paper_epoch_id=paper_epoch_id)
