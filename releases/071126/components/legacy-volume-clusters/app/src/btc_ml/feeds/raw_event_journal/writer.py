"""Atomic append-only journal writer with UTC hour partitions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .schemas import SCHEMA_VERSION, StreamType, validate_event
from .timestamps import utc_now_iso


def _parse_receive_ts(iso: str) -> datetime:
    text = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def partition_parts(receive_iso: str) -> tuple[str, str]:
    dt = _parse_receive_ts(receive_iso).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H")


def stream_dir_name(stream: StreamType) -> str:
    return {
        StreamType.AGG_TRADE: "agg_trade",
        StreamType.BOOK_TICKER: "book_ticker",
        StreamType.OPERATIONAL: "operational",
    }[stream]


@dataclass
class BatchPolicy:
    max_events_per_batch: int = 500
    max_seconds_per_batch: float = 2.0
    max_buffered_bytes: int = 512_000


@dataclass
class CommittedBatch:
    path: str
    stream: str
    schema_version: str
    row_count: int
    first_event_id: Any
    last_event_id: Any
    first_exchange_timestamp: Optional[str]
    last_exchange_timestamp: Optional[str]
    first_receive_timestamp: Optional[str]
    last_receive_timestamp: Optional[str]
    session_id: Optional[str]
    checksum: str
    created_at: str
    batch_sequence: int


@dataclass
class AtomicJournalWriter:
    root: Path
    policy: BatchPolicy = field(default_factory=BatchPolicy)
    on_operational: Optional[Callable[[dict[str, Any]], None]] = None

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._buffers: dict[StreamType, list[dict[str, Any]]] = {
            StreamType.AGG_TRADE: [],
            StreamType.BOOK_TICKER: [],
            StreamType.OPERATIONAL: [],
        }
        self._buffer_bytes: dict[StreamType, int] = {
            StreamType.AGG_TRADE: 0,
            StreamType.BOOK_TICKER: 0,
            StreamType.OPERATIONAL: 0,
        }
        self._batch_opened_at: dict[StreamType, Optional[float]] = {
            StreamType.AGG_TRADE: None,
            StreamType.BOOK_TICKER: None,
            StreamType.OPERATIONAL: None,
        }
        self._batch_seq: dict[StreamType, int] = {
            StreamType.AGG_TRADE: 0,
            StreamType.BOOK_TICKER: 0,
            StreamType.OPERATIONAL: 0,
        }
        self.committed: list[CommittedBatch] = []
        self.bytes_written: int = 0
        self.write_errors: int = 0
        self._blocked: bool = False

    @property
    def buffer_size(self) -> int:
        return sum(len(v) for v in self._buffers.values())

    def recover_temp_files(self) -> list[str]:
        """Remove uncommitted *.tmp leftovers after crash (do not promote)."""
        recovered: list[str] = []
        for path in self.root.rglob("*.tmp"):
            try:
                path.unlink()
                recovered.append(str(path))
            except OSError:
                self.write_errors += 1
        return recovered

    def append(self, stream: StreamType, event: Mapping[str, Any]) -> Optional[CommittedBatch]:
        if self._blocked:
            raise RuntimeError("writer_blocked")
        errors = validate_event(event, stream)
        if errors:
            self.write_errors += 1
            raise ValueError(f"schema_violation:{errors}")
        payload = dict(event)
        line = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        buf = self._buffers[stream]
        if not buf:
            import time

            self._batch_opened_at[stream] = time.monotonic()
        buf.append(payload)
        self._buffer_bytes[stream] += len(line.encode("utf-8")) + 1
        return self._maybe_flush(stream)

    def _maybe_flush(self, stream: StreamType) -> Optional[CommittedBatch]:
        import time

        buf = self._buffers[stream]
        if not buf:
            return None
        opened = self._batch_opened_at[stream] or time.monotonic()
        age = time.monotonic() - opened
        if (
            len(buf) >= self.policy.max_events_per_batch
            or age >= self.policy.max_seconds_per_batch
            or self._buffer_bytes[stream] >= self.policy.max_buffered_bytes
        ):
            return self.flush_stream(stream)
        return None

    def flush_all(self) -> list[CommittedBatch]:
        out: list[CommittedBatch] = []
        for stream in (StreamType.AGG_TRADE, StreamType.BOOK_TICKER, StreamType.OPERATIONAL):
            batch = self.flush_stream(stream)
            if batch is not None:
                out.append(batch)
        return out

    def flush_stream(self, stream: StreamType) -> Optional[CommittedBatch]:
        buf = self._buffers[stream]
        if not buf:
            return None
        try:
            batch = self._commit_batch(stream, list(buf))
        except Exception:
            self.write_errors += 1
            self._blocked = True
            raise
        self._buffers[stream] = []
        self._buffer_bytes[stream] = 0
        self._batch_opened_at[stream] = None
        return batch

    def block_writes(self, reason: str = "disk_low") -> None:
        self._blocked = True
        self.flush_all()

    def _event_id(self, stream: StreamType, event: Mapping[str, Any]) -> Any:
        if stream is StreamType.AGG_TRADE:
            return event.get("aggregate_trade_id")
        if stream is StreamType.BOOK_TICKER:
            return event.get("update_id")
        return event.get("event_type")

    def _exchange_ts(self, stream: StreamType, event: Mapping[str, Any]) -> Optional[str]:
        if stream is StreamType.AGG_TRADE:
            return event.get("exchange_trade_timestamp") or event.get("exchange_event_timestamp")
        return event.get("exchange_event_timestamp")

    def _commit_batch(self, stream: StreamType, events: list[dict[str, Any]]) -> CommittedBatch:
        self._batch_seq[stream] += 1
        seq = self._batch_seq[stream]
        first_recv = events[0].get("local_receive_timestamp")
        last_recv = events[-1].get("local_receive_timestamp")
        date_part, hour_part = partition_parts(str(first_recv or utc_now_iso()))
        session_id = events[0].get("connection_session_id")
        start_token = str(first_recv or "na").replace(":", "").replace("-", "").replace(".", "")
        end_token = str(last_recv or "na").replace(":", "").replace("-", "").replace(".", "")
        sid = str(session_id or "nosession")[:8]
        filename = (
            f"{stream_dir_name(stream)}"
            f"__start={start_token}"
            f"__end={end_token}"
            f"__session={sid}"
            f"__batch={seq:08d}.jsonl"
        )
        part_dir = self.root / stream_dir_name(stream) / f"date={date_part}" / f"hour={hour_part}"
        part_dir.mkdir(parents=True, exist_ok=True)
        final_path = part_dir / filename
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=filename + ".", suffix=".tmp", dir=str(part_dir))
        tmp_path = Path(tmp_name)
        try:
            hasher = hashlib.sha256()
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                for event in events:
                    line = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
                    fh.write(line + "\n")
                    hasher.update(line.encode("utf-8"))
                    hasher.update(b"\n")
                fh.flush()
                os.fsync(fh.fileno())
            # Schema + row count verification before rename
            verified = 0
            with tmp_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    obj = json.loads(line)
                    errs = validate_event(obj, stream)
                    if errs:
                        raise ValueError(f"post_write_schema:{errs}")
                    verified += 1
            if verified != len(events):
                raise ValueError(f"row_count_mismatch:{verified}!={len(events)}")
            os.replace(str(tmp_path), str(final_path))
            # Directory fsync best-effort
            try:
                dir_fd = os.open(str(part_dir), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

        checksum = hasher.hexdigest()
        size = final_path.stat().st_size
        self.bytes_written += size
        created = utc_now_iso()
        meta = CommittedBatch(
            path=str(final_path.relative_to(self.root)),
            stream=stream.value,
            schema_version=SCHEMA_VERSION,
            row_count=len(events),
            first_event_id=self._event_id(stream, events[0]),
            last_event_id=self._event_id(stream, events[-1]),
            first_exchange_timestamp=self._exchange_ts(stream, events[0]),
            last_exchange_timestamp=self._exchange_ts(stream, events[-1]),
            first_receive_timestamp=first_recv,
            last_receive_timestamp=last_recv,
            session_id=session_id,
            checksum=checksum,
            created_at=created,
            batch_sequence=seq,
        )
        self.committed.append(meta)
        self._write_manifest(stream, date_part, hour_part, meta)
        return meta

    def _write_manifest(
        self, stream: StreamType, date_part: str, hour_part: str, meta: CommittedBatch
    ) -> None:
        man_dir = self.root / "manifests" / stream_dir_name(stream) / f"date={date_part}" / f"hour={hour_part}"
        man_dir.mkdir(parents=True, exist_ok=True)
        man_path = man_dir / "batches.jsonl"
        with man_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(meta.__dict__, ensure_ascii=True, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
