"""Append-only execution market WAL for Binance Futures LIVE1B hot path."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .execution_market_wal_archive import SegmentedWalStorage, iter_jsonl

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

    def __init__(
        self,
        root: Path,
        *,
        paper_epoch_id: str,
        enable_segmented_storage: bool = False,
        segment_max_bytes: int = 64 * 1024 * 1024,
        archive_batch_rows: int = 65_536,
        delete_verified_plaintext: bool = False,
        plaintext_retention_hours: float = 0.0,
        warning_size_bytes: int = 10 * 1024**3,
        critical_size_bytes: int = 20 * 1024**3,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paper_epoch_id = paper_epoch_id
        self.events_path = self.root / "events.jsonl"
        self.state_path = self.root / "state.json"
        self._lock = threading.Lock()
        self.events_path.touch(exist_ok=True)
        self.segmented = (
            SegmentedWalStorage(
                self.root,
                max_segment_bytes=segment_max_bytes,
                archive_batch_rows=archive_batch_rows,
                delete_verified_plaintext=delete_verified_plaintext,
                plaintext_retention_hours=plaintext_retention_hours,
            )
            if enable_segmented_storage
            else None
        )
        has_segmented_artifacts = (
            (self.root / "archive").exists()
            or any(self.root.glob("closed-*-*.jsonl"))
        )
        self._reader = self.segmented or (
            SegmentedWalStorage(
                self.root,
                max_segment_bytes=segment_max_bytes,
                archive_batch_rows=archive_batch_rows,
                delete_verified_plaintext=False,
            )
            if has_segmented_artifacts
            else None
        )
        self._next_offset = self._load_next_offset()
        state = self._load_state()
        # The physical active tail is authoritative. A crash can happen after
        # atomic rotation but before state.json records the new range start.
        self._active_start_offset = self._infer_active_start()
        self.warning_size_bytes = int(warning_size_bytes)
        self.critical_size_bytes = int(critical_size_bytes)
        self._oldest_event_timestamp = self._discover_oldest_event_timestamp()
        self.last_confirmed_agg_trade_id: int | None = state.get("last_confirmed_agg_trade_id")
        self.fail_next_appends: int = 0
        self.fsync_count: int = 0
        self.state_write_count: int = 0
        self.periodic_fsync_count: int = 0
        self.soft_fsync_interval_ms: float = 250.0
        self._soft_dirty: bool = False
        self._last_durable_mono_ns: int = 0
        if self.segmented is not None and self.events_path.stat().st_size >= self.segmented.max_segment_bytes:
            closed = self.segmented.rotate(
                first_offset=self._active_start_offset,
                last_offset=self.last_offset,
            )
            if closed is not None:
                self._active_start_offset = self._next_offset
                self._save_state(active_segment_start_offset=self._active_start_offset)

    def inject_fail_next_appends(self, count: int) -> None:
        self.fail_next_appends = max(0, int(count))

    def _load_next_offset(self) -> int:
        archived_last = 0
        if self._reader is not None:
            archived_last = max(
                [end for _start, end, _path in self._reader.archives()]
                + [end for _start, end, _path in self._reader.closed_segments()],
                default=0,
            )
        # Restart must not materialize or scan the production WAL (currently
        # multi-GB) before the first health write.  Read backwards until the
        # last complete valid record; this also handles a torn final append.
        for line in self._iter_lines_reverse():
            try:
                last = int(json.loads(line).get("wal_offset") or 0)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if last:
                return max(last, archived_last) + 1
        return archived_last + 1

    def _infer_active_start(self) -> int:
        for row in iter_jsonl(self.events_path):
            return int(row["wal_offset"])
        return self._next_offset

    def _iter_lines_reverse(self, *, chunk_size: int = 64 * 1024) -> Iterator[str]:
        """Yield non-empty UTF-8 lines from the WAL tail to its head."""
        with self.events_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            position = fh.tell()
            remainder = b""
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                fh.seek(position)
                block = fh.read(read_size) + remainder
                parts = block.split(b"\n")
                remainder = parts[0]
                for raw in reversed(parts[1:]):
                    if raw.strip():
                        yield raw.decode("utf-8", errors="replace")
            if remainder.strip():
                yield remainder.decode("utf-8", errors="replace")

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
        self.state_write_count += 1

    @property
    def last_offset(self) -> int:
        return max(0, self._next_offset - 1)

    def start_background_compaction(self) -> None:
        if self.segmented is not None:
            self.segmented.compact_async()

    @property
    def storage_mode(self) -> str:
        return "segmented" if self.segmented is not None else "legacy"

    @property
    def active_start_offset(self) -> int:
        return self._active_start_offset

    @property
    def closed_segment_count(self) -> int:
        return 0 if self._reader is None else len(self._reader.closed_segments())

    @property
    def archive_count(self) -> int:
        return 0 if self._reader is None else len(self._reader.archives())

    @property
    def archive_error(self) -> str | None:
        return None if self.segmented is None else self.segmented.last_compaction_error

    @property
    def retention_error(self) -> str | None:
        return None if self.segmented is None else self.segmented.last_retention_error

    @property
    def wal_size_bytes(self) -> int:
        total = 0
        for path in self.root.rglob("*"):
            # Atomic state/archive publication can rename a temporary file
            # between directory enumeration and stat. Health telemetry must
            # never terminate the live manager because of that benign race.
            try:
                if path.is_file() and not path.name.endswith(".tmp"):
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
        return total

    @property
    def wal_segments_count(self) -> int:
        if self._reader is None:
            return 1 if self.events_path.exists() else 0
        ranges = {(start, end) for start, end, _ in self._reader.archives()}
        ranges.update((start, end) for start, end, _ in self._reader.closed_segments())
        return len(ranges) + (1 if self.events_path.exists() else 0)

    @property
    def wal_oldest_event_timestamp(self) -> str | None:
        return self._oldest_event_timestamp

    @property
    def wal_retention_status(self) -> str:
        if self.archive_error or self.retention_error:
            return "DEGRADED"
        size = self.wal_size_bytes
        if size > self.critical_size_bytes:
            return "CRITICAL"
        if size > self.warning_size_bytes:
            return "WARNING"
        return "OK"

    @staticmethod
    def _event_timestamp(row: dict[str, Any]) -> str | None:
        for key in ("local_receive_timestamp", "receive_timestamp", "durable_append_timestamp"):
            value = row.get(key)
            if value:
                return str(value)
        value = row.get("exchange_event_timestamp")
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(
                float(value) / 1000.0, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError, OSError):
            return None

    def _discover_oldest_event_timestamp(self) -> str | None:
        try:
            row = next(self.iter_from_offset(0), None)
        except (OSError, ValueError):
            return None
        return self._event_timestamp(row) if row else None

    def flush_durable(self, *, reason: str = "periodic") -> bool:
        """Fsync the active WAL and persist state for any soft-appended bytes.

        Soft BOOK_TICKER appends write+flush without fsync. This catches them up
        on a timer, before AGG_TRADE, or on shutdown. AGG_TRADE hard-fsync also
        clears soft dirtiness because it syncs the whole file.
        """
        with self._lock:
            if not self._soft_dirty:
                return False
            try:
                with self.events_path.open("a", encoding="utf-8") as fh:
                    fh.flush()
                    os.fsync(fh.fileno())
                self.fsync_count += 1
                if reason == "periodic":
                    self.periodic_fsync_count += 1
                self._save_state(
                    last_wal_offset=self.last_offset,
                    active_segment_start_offset=self._active_start_offset,
                    last_confirmed_agg_trade_id=self.last_confirmed_agg_trade_id,
                )
                self._soft_dirty = False
                self._last_durable_mono_ns = time.monotonic_ns()
                return True
            except OSError:
                return False

    def maybe_periodic_flush(self, *, now_mono_ns: int | None = None) -> bool:
        """Fsync soft BOOK_TICKER bytes when the interval has elapsed."""
        now = int(now_mono_ns if now_mono_ns is not None else time.monotonic_ns())
        if not self._soft_dirty:
            return False
        interval_ns = int(max(0.0, float(self.soft_fsync_interval_ms)) * 1_000_000.0)
        last = int(self._last_durable_mono_ns or 0)
        if last == 0:
            self._last_durable_mono_ns = now
            return False
        if (now - last) < interval_ns:
            return False
        return self.flush_durable(reason="periodic")

    def append(
        self,
        event: dict[str, Any],
        *,
        simulate_failure: bool = False,
        fsync: bool = True,
        update_state: bool = True,
    ) -> WalAppendResult:
        """Append one WAL event.

        Phase C: BOOK_TICKER may pass ``fsync=False`` / ``update_state=False``
        to drop per-tick durability cost. AGG_TRADE (volume + TP/SL trigger)
        must keep ``fsync=True`` and ``update_state=True`` so quantity and
        continuity ids remain crash-durable. Soft bytes are later hardened by
        ``maybe_periodic_flush`` / ``flush_durable`` or the next hard fsync.
        """
        payload = dict(event)
        payload.setdefault("schema_version", WAL_SCHEMA_VERSION)
        payload.setdefault("paper_epoch_id", self.paper_epoch_id)
        payload.setdefault("source", SOURCE_BINANCE_FUTURES)
        payload["durable_append_timestamp"] = _utc_iso()
        payload["wal_fsync"] = bool(fsync)
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
                    if fsync:
                        os.fsync(fh.fileno())
                        self.fsync_count += 1
                        self._soft_dirty = False
                        self._last_durable_mono_ns = time.monotonic_ns()
                    else:
                        self._soft_dirty = True
                        if self._last_durable_mono_ns == 0:
                            # Start the soft durability window on first soft write.
                            self._last_durable_mono_ns = time.monotonic_ns()
                self._next_offset = offset + 1
                if self._oldest_event_timestamp is None:
                    self._oldest_event_timestamp = self._event_timestamp(payload)
                if payload.get("event_type") == EVENT_AGG_TRADE and payload.get("aggregate_trade_id") is not None:
                    agg_id = int(payload["aggregate_trade_id"])
                    self.last_confirmed_agg_trade_id = agg_id
                    if update_state:
                        self._save_state(
                            last_confirmed_agg_trade_id=agg_id,
                            last_wal_offset=offset,
                            active_segment_start_offset=self._active_start_offset,
                        )
                elif update_state:
                    self._save_state(
                        last_wal_offset=offset,
                        active_segment_start_offset=self._active_start_offset,
                    )
                if self.segmented is not None:
                    closed = self.segmented.rotate_if_due(
                        first_offset=self._active_start_offset, last_offset=offset
                    )
                    if closed is not None:
                        self._active_start_offset = offset + 1
                        self._save_state(active_segment_start_offset=self._active_start_offset)
                        self.segmented.compact_async()
                return WalAppendResult(ok=True, wal_offset=offset)
            except OSError as exc:
                return WalAppendResult(ok=False, error=str(exc), retryable=True)

    def iter_from_offset(self, offset: int) -> Iterator[dict[str, Any]]:
        if self._reader is not None:
            return self._reader.iter_from_offset(
                int(offset),
                active_start_offset=self._active_start_offset,
                active_last_offset=self.last_offset,
            )
        if not self.events_path.exists():
            return iter(())

        def rows() -> Iterator[dict[str, Any]]:
            pending: list[dict[str, Any]] = []
            for line in self._iter_lines_reverse():
                try:
                    row = json.loads(line)
                    wal_offset = int(row.get("wal_offset") or 0)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if wal_offset <= int(offset):
                    break
                pending.append(row)
            yield from reversed(pending)

        return rows()
