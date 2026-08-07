"""Append-only execution market WAL for Binance Futures LIVE1B hot path."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

WAL_SCHEMA_VERSION = "execution_market_wal_v1"
SOURCE_BINANCE_FUTURES = "BINANCE_FUTURES"
EVENT_AGG_TRADE = "AGG_TRADE"
EVENT_BOOK_TICKER = "BOOK_TICKER"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class WalAppendResult:
    ok: bool
    wal_offset: int | None = None
    error: str | None = None
    retryable: bool = False


class ExecutionMarketWAL:
    """Synchronous JSONL WAL with fsync durability semantics."""

    def __init__(self, root: Path, *, paper_epoch_id: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paper_epoch_id = paper_epoch_id
        self.events_path = self.root / "events.jsonl"
        self.state_path = self.root / "state.json"
        self._lock = threading.Lock()
        self.events_path.touch(exist_ok=True)
        self._next_offset = self._load_next_offset()
        self.last_confirmed_agg_trade_id: int | None = self._load_state().get("last_confirmed_agg_trade_id")
        self.fail_next_appends: int = 0

    def inject_fail_next_appends(self, count: int) -> None:
        self.fail_next_appends = max(0, int(count))

    def _load_next_offset(self) -> int:
        if not self.events_path.exists():
            return 1
        last = 0
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                last = max(last, int(row.get("wal_offset") or 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return last + 1 if last else 1

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, **updates: Any) -> None:
        state = self._load_state()
        state.update(updates)
        state["paper_epoch_id"] = self.paper_epoch_id
        state["schema_version"] = WAL_SCHEMA_VERSION
        state["updated_at"] = _utc_iso()
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    @property
    def last_offset(self) -> int:
        return max(0, self._next_offset - 1)

    def append(self, event: dict[str, Any], *, simulate_failure: bool = False) -> WalAppendResult:
        payload = dict(event)
        payload.setdefault("schema_version", WAL_SCHEMA_VERSION)
        payload.setdefault("paper_epoch_id", self.paper_epoch_id)
        payload.setdefault("source", SOURCE_BINANCE_FUTURES)
        payload["durable_append_timestamp"] = _utc_iso()
        line = json.dumps(payload, sort_keys=True, default=str) + "\n"
        with self._lock:
            if simulate_failure or self.fail_next_appends > 0:
                if self.fail_next_appends > 0:
                    self.fail_next_appends -= 1
                return WalAppendResult(ok=False, error="simulated_wal_failure", retryable=True)
            try:
                offset = self._next_offset
                payload["wal_offset"] = offset
                line = json.dumps(payload, sort_keys=True, default=str) + "\n"
                with self.events_path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
                self._next_offset = offset + 1
                if payload.get("event_type") == EVENT_AGG_TRADE and payload.get("aggregate_trade_id") is not None:
                    agg_id = int(payload["aggregate_trade_id"])
                    self.last_confirmed_agg_trade_id = agg_id
                    self._save_state(last_confirmed_agg_trade_id=agg_id, last_wal_offset=offset)
                else:
                    self._save_state(last_wal_offset=offset)
                return WalAppendResult(ok=True, wal_offset=offset)
            except OSError as exc:
                return WalAppendResult(ok=False, error=str(exc), retryable=True)

    def iter_from_offset(self, offset: int) -> Iterator[dict[str, Any]]:
        if not self.events_path.exists():
            return iter(())
        rows: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if int(row.get("wal_offset") or 0) > int(offset):
                rows.append(row)
        rows.sort(key=lambda r: int(r.get("wal_offset") or 0))
        return iter(rows)
