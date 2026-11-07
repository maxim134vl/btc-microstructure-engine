"""Archival Parquet/ZSTD writer process — disk I/O off the websocket receive path."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from .parquet_schema import arrow_schema_for, event_to_arrow_row
from .queue import BoundedEventQueue, QueuedEvent
from .schemas import SCHEMA_VERSION, StreamType, validate_event
from .timestamps import utc_now_iso
from .writer import CommittedBatch, partition_parts, stream_dir_name


@dataclass
class ChunkPolicy:
    max_events_per_chunk: int = 25_000
    max_seconds_per_chunk: float = 60.0
    max_bytes_per_chunk: int = 32 * 1024 * 1024
    compression: str = "zstd"
    compression_level: int = 6


@dataclass
class WriterStats:
    bytes_written: int = 0
    chunks_committed: int = 0
    events_committed: int = 0
    write_errors: int = 0
    last_write_duration_ms: float = 0.0
    last_fsync_duration_ms: float = 0.0
    max_write_duration_ms: float = 0.0
    max_fsync_duration_ms: float = 0.0
    cpu_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ArchivalParquetWriter:
    """Consumes BoundedEventQueue and commits immutable Parquet/ZSTD chunks."""

    root: Path
    queue: BoundedEventQueue
    policy: ChunkPolicy = field(default_factory=ChunkPolicy)
    stats: WriterStats = field(default_factory=WriterStats)
    committed: list[CommittedBatch] = field(default_factory=list)

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
        self._opened_at: dict[StreamType, Optional[float]] = {
            StreamType.AGG_TRADE: None,
            StreamType.BOOK_TICKER: None,
            StreamType.OPERATIONAL: None,
        }
        self._batch_seq: dict[StreamType, int] = {
            StreamType.AGG_TRADE: 0,
            StreamType.BOOK_TICKER: 0,
            StreamType.OPERATIONAL: 0,
        }
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._process = None  # optional multiprocessing.Process
        self._blocked = False
        self._lock = threading.Lock()

    def recover_temp_files(self) -> list[str]:
        recovered: list[str] = []
        for path in self.root.rglob("*.tmp"):
            try:
                path.unlink()
                recovered.append(str(path))
            except OSError:
                self.stats.write_errors += 1
        return recovered

    def start_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run_loop, name="raw-event-archival-writer", daemon=True
        )
        self._thread.start()

    def start_process(self) -> None:
        """Preferred dedicated OS process writer.

        On macOS, fork-after-import is unsafe once other threads exist, and
        spawn cannot share BoundedEventQueue. Callers should start this *before*
        websocket threads; if process start fails, fall back to thread.
        """
        import multiprocessing as mp

        try:
            ctx = mp.get_context("fork")
        except ValueError:
            # spawn/forkserver cannot share this in-memory queue.
            self.start_thread()
            return
        self._stop.clear()
        self._process = ctx.Process(target=self.run_loop, name="raw-event-archival-writer")
        self._process.daemon = True
        self._process.start()

    def stop(self, *, flush: bool = True, timeout: float = 30.0) -> None:
        self._stop.set()
        self.queue.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        if self._process is not None and self._process.is_alive():
            self._process.join(timeout=timeout)
        if flush:
            with self._lock:
                self.flush_all()

    def run_loop(self) -> None:
        cpu0 = time.process_time()
        while not self._stop.is_set():
            item = self.queue.dequeue(timeout=0.2)
            if item is not None:
                try:
                    self._accept(item)
                except Exception:
                    self.stats.write_errors += 1
                    self._blocked = True
                    self._stop.set()
                    break
            else:
                # time-based flush even when idle
                try:
                    with self._lock:
                        self._flush_due()
                except Exception:
                    self.stats.write_errors += 1
                    self._blocked = True
                    self._stop.set()
                    break
        # Drain remaining after stop signal
        while True:
            item = self.queue.dequeue(timeout=0.05)
            if item is None:
                break
            try:
                self._accept(item)
            except Exception:
                self.stats.write_errors += 1
                break
        with self._lock:
            try:
                self.flush_all()
            except Exception:
                self.stats.write_errors += 1
        self.stats.cpu_seconds = round(time.process_time() - cpu0, 4)

    def _accept(self, item: QueuedEvent) -> None:
        with self._lock:
            if self._blocked:
                raise RuntimeError("writer_blocked")
            stream = item.stream
            event = item.event
            errors = validate_event(event, stream)
            if errors:
                self.stats.write_errors += 1
                raise ValueError(f"schema_violation:{errors}")
            buf = self._buffers[stream]
            if not buf:
                self._opened_at[stream] = time.monotonic()
            buf.append(dict(event))
            self._buffer_bytes[stream] += item.estimated_bytes
            self._maybe_flush(stream)

    def append_direct(self, stream: StreamType, event: Mapping[str, Any]) -> Optional[CommittedBatch]:
        """Test/helper path: append without queue."""
        with self._lock:
            if self._blocked:
                raise RuntimeError("writer_blocked")
            errors = validate_event(event, stream)
            if errors:
                raise ValueError(f"schema_violation:{errors}")
            buf = self._buffers[stream]
            if not buf:
                self._opened_at[stream] = time.monotonic()
            payload = dict(event)
            buf.append(payload)
            self._buffer_bytes[stream] += len(
                json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            )
            return self._maybe_flush(stream)

    def _maybe_flush(self, stream: StreamType) -> Optional[CommittedBatch]:
        buf = self._buffers[stream]
        if not buf:
            return None
        opened = self._opened_at[stream] or time.monotonic()
        age = time.monotonic() - opened
        if (
            len(buf) >= self.policy.max_events_per_chunk
            or age >= self.policy.max_seconds_per_chunk
            or self._buffer_bytes[stream] >= self.policy.max_bytes_per_chunk
        ):
            return self.flush_stream(stream)
        return None

    def _flush_due(self) -> None:
        for stream in (StreamType.AGG_TRADE, StreamType.BOOK_TICKER, StreamType.OPERATIONAL):
            buf = self._buffers[stream]
            if not buf:
                continue
            opened = self._opened_at[stream] or time.monotonic()
            if time.monotonic() - opened >= self.policy.max_seconds_per_chunk:
                self.flush_stream(stream)

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
        batch = self._commit_chunk(stream, list(buf))
        self._buffers[stream] = []
        self._buffer_bytes[stream] = 0
        self._opened_at[stream] = None
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

    def _commit_chunk(self, stream: StreamType, events: list[dict[str, Any]]) -> CommittedBatch:
        t_write0 = time.monotonic()
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
            f"__batch={seq:08d}.parquet"
        )
        part_dir = self.root / stream_dir_name(stream) / f"date={date_part}" / f"hour={hour_part}"
        part_dir.mkdir(parents=True, exist_ok=True)
        final_path = part_dir / filename
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=filename + ".", suffix=".tmp", dir=str(part_dir)
        )
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)

        schema = arrow_schema_for(stream)
        rows = [event_to_arrow_row(stream, e) for e in events]
        table = pa.Table.from_pylist(rows, schema=schema)

        try:
            t_fsync0 = time.monotonic()
            pq.write_table(
                table,
                where=str(tmp_path),
                compression=self.policy.compression,
                compression_level=self.policy.compression_level,
                use_dictionary=True,
                write_statistics=True,
            )
            # fsync file
            with open(tmp_path, "rb") as fh:
                os.fsync(fh.fileno())
            fsync_ms = (time.monotonic() - t_fsync0) * 1000.0

            # read-back schema + row count validation
            read_table = pq.read_table(str(tmp_path))
            if read_table.num_rows != len(events):
                raise ValueError(f"row_count_mismatch:{read_table.num_rows}!={len(events)}")
            # Parent hive dirs (date=/hour=) may inject partition columns on read.
            expected_cols = set(schema.names)
            got_cols = set(read_table.schema.names)
            if not expected_cols.issubset(got_cols):
                raise ValueError(
                    f"schema_name_mismatch:missing={expected_cols - got_cols}"
                )
            if read_table.schema.field("schema_version").type != pa.string():
                raise ValueError("schema_type_mismatch")

            checksum = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
            # sidecar checksum for reader (parquet content is opaque to line hashing)
            sidecar = tmp_path.with_suffix(tmp_path.suffix + ".sha256")
            sidecar.write_text(checksum + "\n", encoding="utf-8")
            with open(sidecar, "rb") as fh:
                os.fsync(fh.fileno())

            os.replace(str(tmp_path), str(final_path))
            os.replace(str(sidecar), str(final_path) + ".sha256")
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
            sidecar_path = Path(str(tmp_path) + ".sha256")
            if sidecar_path.exists():
                try:
                    sidecar_path.unlink()
                except OSError:
                    pass
            raise

        write_ms = (time.monotonic() - t_write0) * 1000.0
        self.stats.last_write_duration_ms = round(write_ms, 3)
        self.stats.last_fsync_duration_ms = round(fsync_ms, 3)
        self.stats.max_write_duration_ms = max(self.stats.max_write_duration_ms, write_ms)
        self.stats.max_fsync_duration_ms = max(self.stats.max_fsync_duration_ms, fsync_ms)

        size = final_path.stat().st_size
        self.stats.bytes_written += size
        self.stats.chunks_committed += 1
        self.stats.events_committed += len(events)
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
        man_dir = (
            self.root / "manifests" / stream_dir_name(stream) / f"date={date_part}" / f"hour={hour_part}"
        )
        man_dir.mkdir(parents=True, exist_ok=True)
        man_path = man_dir / "batches.jsonl"
        with man_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(meta.__dict__, ensure_ascii=True, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
