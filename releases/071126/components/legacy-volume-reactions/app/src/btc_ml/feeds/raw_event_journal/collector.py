"""Shadow collector: Binance combined aggTrade + bookTicker → journal."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .archival_writer import ArchivalParquetWriter, ChunkPolicy
from .dedupe_gap import DuplicateTracker, SequenceMonitor
from .disk import check_disk, estimate_write_rate
from .health import HealthSnapshot, HealthStatus
from .normalize import normalize_agg_trade, normalize_book_ticker, normalize_operational
from .queue import BoundedEventQueue
from .schemas import OperationalEventType, StreamType
from .session import SessionManager
from .timestamps import capture_local_receive, utc_now_iso
from .writer import AtomicJournalWriter, BatchPolicy

DEFAULT_WS_URL = (
    "wss://stream.binance.com:9443/stream?streams=btcusdt@aggTrade/btcusdt@bookTicker"
)
DEFAULT_SYMBOL = "BTCUSDT"

# Measured TRD1A smoke ~1.2 agg/s, ~32 book/s; max combined gap ~2.3s.
# Conservative stale thresholds (>> observed maxima).
DEFAULT_AGG_STALE_SECONDS = 60.0
DEFAULT_BOOK_STALE_SECONDS = 15.0


@dataclass
class CollectorConfig:
    journal_root: Path
    health_path: Path
    symbol: str = DEFAULT_SYMBOL
    ws_url: str = DEFAULT_WS_URL
    duration_seconds: Optional[float] = None
    # Working stop threshold (priority). Emergency floor remains for defense-in-depth.
    min_free_bytes: int = 5 * 1024**3
    emergency_min_free_bytes: int = 2 * 1024**3
    stale_agg_after_seconds: float = DEFAULT_AGG_STALE_SECONDS
    stale_book_after_seconds: float = DEFAULT_BOOK_STALE_SECONDS
    # Back-compat alias used by older call sites / tests
    stale_after_seconds: Optional[float] = None
    retain_raw_payload: bool = False
    auto_reconnect: bool = True
    reconnect_delay_seconds: float = 5.0
    storage_format: str = "parquet"  # parquet | jsonl
    writer_mode: str = "thread"  # thread | process
    queue_capacity_events: int = 50_000
    queue_capacity_bytes: int = 64 * 1024 * 1024
    chunk_policy: ChunkPolicy = field(default_factory=ChunkPolicy)
    batch_policy: BatchPolicy = field(
        default_factory=lambda: BatchPolicy(
            max_events_per_batch=500,
            max_seconds_per_batch=2.0,
            max_buffered_bytes=512_000,
        )
    )
    disk_check_every_events: int = 200
    health_every_events: int = 50

    def __post_init__(self) -> None:
        if self.stale_after_seconds is not None:
            self.stale_agg_after_seconds = float(self.stale_after_seconds)
            self.stale_book_after_seconds = float(self.stale_after_seconds)


class RawMarketEventCollector:
    def __init__(self, config: CollectorConfig):
        self.config = config
        self.queue = BoundedEventQueue(
            capacity_events=config.queue_capacity_events,
            capacity_bytes=config.queue_capacity_bytes,
        )
        self.archival = ArchivalParquetWriter(
            root=config.journal_root,
            queue=self.queue,
            policy=config.chunk_policy,
        )
        # JSONL writer retained for optional storage_format=jsonl / parity tooling.
        self.jsonl_writer = AtomicJournalWriter(config.journal_root, policy=config.batch_policy)
        self.writer = self.archival  # primary metrics surface (bytes/commits)
        self.sessions = SessionManager()
        # Continue reconnect generation across process restarts when prior health exists.
        try:
            if config.health_path.exists():
                prior = json.loads(config.health_path.read_text(encoding="utf-8"))
                prior_gen = int(prior.get("reconnect_generation") or 0)
                if prior_gen > 0:
                    self.sessions.reconnect_generation = prior_gen
        except Exception:
            pass
        self.dupes = DuplicateTracker()
        self.gaps = SequenceMonitor()
        self.health = HealthSnapshot(pid=os.getpid())
        self._stop = threading.Event()
        self._force_reconnect = threading.Event()
        self._source_seq = 0
        self._lock = threading.RLock()
        self._health_lock = threading.Lock()
        self._ws = None
        self._started_mono = 0.0
        self._agg_intervals: list[float] = []
        self._book_intervals: list[float] = []
        self._last_agg_mono: Optional[float] = None
        self._last_book_mono: Optional[float] = None
        self._session_connected_mono: Optional[float] = None
        self._events_since_disk_check = 0
        self._stop_reason: Optional[str] = None
        self._fault_stop = False
        self._ws_failures = 0

    def request_stop(self, reason: str = "stop_requested", *, fault: bool = False) -> None:
        if self._stop.is_set():
            return
        self._stop_reason = reason
        self._fault_stop = bool(fault)
        self.health.stop_reason = reason
        self._stop.set()
        self._emit_operational(
            OperationalEventType.COLLECTION_STOPPED.value,
            {"reason": reason, "fault": bool(fault)},
        )
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass

    def _buffer_bytes(self) -> int:
        return int(self.queue.metrics.queue_current_bytes)

    def _enqueue(self, stream: StreamType, event: dict) -> bool:
        """Receive-path enqueue only — no Parquet/fsync/manifest work here."""
        ok = self.queue.try_enqueue(stream, event)
        if not ok:
            self._on_backpressure(stream, event)
        return ok

    def _on_backpressure(self, stream: StreamType, event: dict) -> None:
        self._set_status(
            HealthStatus.RAW_EVENT_BACKPRESSURE,
            {
                "stream": stream.value,
                "queue": self.queue.metrics.to_dict(),
            },
        )
        # Operational emit best-effort; may also fail if queue full — integrity already flagged.
        try:
            recv_ts, mono = capture_local_receive()
            session = self.sessions.current
            op = normalize_operational(
                OperationalEventType.RAW_EVENT_BACKPRESSURE.value,
                symbol=self.config.symbol,
                local_receive_timestamp=recv_ts,
                local_receive_monotonic_ns=mono,
                connection_session_id=session.connection_session_id if session else None,
                reconnect_generation=session.reconnect_generation
                if session
                else self.sessions.reconnect_generation,
                details={"stream": stream.value, "queue": self.queue.metrics.to_dict()},
            )
            self.queue.try_enqueue(StreamType.OPERATIONAL, op)
        except Exception:
            pass
        self.request_stop("raw_event_backpressure", fault=True)

    def _emit_operational_direct(self, event_type: str, details: Optional[dict] = None) -> None:
        """Write operational event after queue is closed (shutdown path only)."""
        recv_ts, mono = capture_local_receive()
        session = self.sessions.current
        event = normalize_operational(
            event_type,
            symbol=self.config.symbol,
            local_receive_timestamp=recv_ts,
            local_receive_monotonic_ns=mono,
            connection_session_id=session.connection_session_id if session else None,
            reconnect_generation=session.reconnect_generation
            if session
            else self.sessions.reconnect_generation,
            details=details,
        )
        self.archival.append_direct(StreamType.OPERATIONAL, event)

    def _refresh_runtime_health(self) -> None:
        session = self.sessions.current
        self.health.pid = os.getpid()
        if self._started_mono:
            self.health.uptime_seconds = round(time.monotonic() - self._started_mono, 3)
        self.health.connection_session_id = (
            session.connection_session_id if session else None
        )
        self.health.reconnect_generation = (
            session.reconnect_generation
            if session
            else self.sessions.reconnect_generation
        )
        self.health.current_buffer_events = self.queue.metrics.queue_current_events
        self.health.current_buffer_size = self.queue.metrics.queue_current_events
        self.health.current_buffer_bytes = self._buffer_bytes()
        self.health.details["queue"] = self.queue.metrics.to_dict()
        self.health.details["writer_stats"] = self.archival.stats.to_dict()
        self.health.details["writer_mode"] = self.config.writer_mode
        self.health.details["storage_format"] = self.config.storage_format
        if self.config.storage_format == "parquet":
            self.health.events_committed = self.archival.stats.events_committed
            if self.archival.committed:
                self.health.last_committed_batch = self.archival.committed[-1].path
                self.health.last_successful_commit_time = self.archival.committed[-1].created_at
            self.health.write_errors = self.archival.stats.write_errors
        self.health.duplicates_dropped = self.dupes.dropped
        self.health.gaps_detected = self.gaps.gap_count
        duration = max(0.001, self.health.uptime_seconds or 0.001)
        bytes_written = (
            self.archival.stats.bytes_written
            if self.config.storage_format == "parquet"
            else self.jsonl_writer.bytes_written
        )
        _, gb_day = estimate_write_rate(
            bytes_written=bytes_written, duration_seconds=duration
        )
        self.health.projected_gb_per_day = round(gb_day, 3)
        try:
            disk = check_disk(
                self.config.journal_root, min_free_bytes=self.config.min_free_bytes
            )
            self.health.free_disk_gib = disk.free_gb
            if disk.free_bytes <= self.config.emergency_min_free_bytes:
                self.health.disk_status = "EMERGENCY_LOW"
            elif disk.is_low:
                self.health.disk_status = "WORKING_LOW"
            else:
                self.health.disk_status = "OK"
        except Exception as exc:  # noqa: BLE001
            self.health.disk_status = "UNAVAILABLE"
            self.health.details["disk_error"] = str(exc)

    def _write_health(self) -> None:
        """Atomically refresh health snapshot (unique temp names; dedicated lock)."""
        import tempfile

        with self._health_lock:
            self._refresh_runtime_health()
            self.config.health_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self.health.to_dict()
            text = json.dumps(payload, indent=2)
            last_exc: Exception | None = None
            for _attempt in range(3):
                tmp_path: Path | None = None
                try:
                    fd, name = tempfile.mkstemp(
                        prefix=self.config.health_path.name + ".",
                        suffix=".tmp",
                        dir=str(self.config.health_path.parent),
                    )
                    tmp_path = Path(name)
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(text)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(str(tmp_path), str(self.config.health_path))
                    return
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if tmp_path is not None:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                    time.sleep(0.05)
            self.health.write_errors += 1
            self.health.details["health_write_error"] = str(last_exc)
            # Soft-stop without re-entering request_stop/operational emit under health lock.
            self._stop_reason = "health_artifact_unwritable"
            self._fault_stop = True
            self.health.stop_reason = self._stop_reason
            self._stop.set()
            try:
                if self._ws is not None:
                    self._ws.close()
            except Exception:
                pass

    def _set_status(self, status: HealthStatus, detail: Optional[dict] = None) -> None:
        if self.health.health_status != status.value:
            self.health.health_status = status.value
            if detail:
                self.health.details.update(detail)
            self._emit_operational(
                OperationalEventType.HEALTH_STATUS_CHANGED.value,
                {"status": status.value, **(detail or {})},
            )
            self._write_health()

    def _emit_operational(self, event_type: str, details: Optional[dict] = None) -> None:
        recv_ts, mono = capture_local_receive()
        session = self.sessions.current
        event = normalize_operational(
            event_type,
            symbol=self.config.symbol,
            local_receive_timestamp=recv_ts,
            local_receive_monotonic_ns=mono,
            connection_session_id=session.connection_session_id if session else None,
            reconnect_generation=session.reconnect_generation
            if session
            else self.sessions.reconnect_generation,
            details=details,
        )
        try:
            if self.config.storage_format == "jsonl":
                batch = self.jsonl_writer.append(StreamType.OPERATIONAL, event)
                if batch:
                    self.health.last_committed_batch = batch.path
                    self.health.last_successful_commit_time = utc_now_iso()
                    self.health.events_committed += batch.row_count
            else:
                self._enqueue(StreamType.OPERATIONAL, event)
                self.health.events_committed = self.archival.stats.events_committed
                if self.archival.committed:
                    self.health.last_committed_batch = self.archival.committed[-1].path
                    self.health.last_successful_commit_time = self.archival.committed[-1].created_at
        except Exception as exc:  # noqa: BLE001
            self.health.write_errors += 1
            self._set_status(HealthStatus.WRITER_BLOCKED, {"error": str(exc)})

    def _check_disk(self) -> bool:
        try:
            status = check_disk(
                self.config.journal_root, min_free_bytes=self.config.min_free_bytes
            )
        except Exception as exc:  # noqa: BLE001
            self._set_status(HealthStatus.DISK_ERROR, {"error": str(exc)})
            self.request_stop("journal_root_unavailable", fault=True)
            return False
        self.health.free_disk_gib = status.free_gb
        # Working threshold (5 GiB) has priority over emergency (2 GiB).
        if status.free_bytes <= self.config.min_free_bytes:
            level = (
                "emergency"
                if status.free_bytes <= self.config.emergency_min_free_bytes
                else "working"
            )
            self.health.disk_status = (
                "EMERGENCY_LOW" if level == "emergency" else "WORKING_LOW"
            )
            self._set_status(
                HealthStatus.DISK_LOW,
                {
                    "level": level,
                    "free_bytes": status.free_bytes,
                    "min_free_bytes": self.config.min_free_bytes,
                    "emergency_min_free_bytes": self.config.emergency_min_free_bytes,
                },
            )
            self._emit_operational(
                OperationalEventType.DISK_LOW.value,
                {
                    "level": level,
                    "free_bytes": status.free_bytes,
                    "free_gb": status.free_gb,
                },
            )
            try:
                if self.config.storage_format == "jsonl":
                    self.jsonl_writer.block_writes("disk_low")
                else:
                    self.archival.block_writes("disk_low")
            except Exception:
                pass
            self.request_stop("disk_low", fault=True)
            return False
        self.health.disk_status = "OK"
        return True

    def _note_interval(self, bucket: list[float], last: Optional[float]) -> float:
        now_m = time.monotonic()
        if last is not None:
            bucket.append((now_m - last) * 1000.0)
            if len(bucket) > 5000:
                del bucket[:2500]
        return now_m

    def _on_message(self, _ws: Any, message: str) -> None:
        if self._stop.is_set():
            return
        recv_ts, mono = capture_local_receive()
        try:
            envelope = json.loads(message)
        except json.JSONDecodeError:
            return
        stream_name = envelope.get("stream") or ""
        data = envelope.get("data") or envelope
        session = self.sessions.current
        if session is None:
            return
        with self._lock:
            self._source_seq += 1
            seq = self._source_seq
            self.health.events_received += 1
            self._events_since_disk_check += 1
            if self._events_since_disk_check >= self.config.disk_check_every_events:
                self._events_since_disk_check = 0
                if not self._check_disk():
                    return

            try:
                if "aggTrade" in stream_name or data.get("e") == "aggTrade":
                    self._handle_agg(data, recv_ts, mono, session, seq)
                elif "bookTicker" in stream_name or data.get("e") == "bookTicker":
                    self._handle_book(data, recv_ts, mono, session, seq)
            except Exception as exc:  # noqa: BLE001
                self.health.write_errors += 1
                msg = str(exc)
                if "schema" in msg:
                    self.health.schema_errors += 1
                    self._set_status(HealthStatus.SCHEMA_ERROR, {"error": msg})
                    self.request_stop("schema_incompatibility", fault=True)
                else:
                    self._set_status(HealthStatus.WRITER_BLOCKED, {"error": msg})
                    self.request_stop("writer_failure", fault=True)

            if self.config.duration_seconds is not None:
                if time.monotonic() - self._started_mono >= self.config.duration_seconds:
                    self.request_stop("duration_elapsed", fault=False)

            if self.health.events_received % self.config.health_every_events == 0:
                self._write_health()

    def _handle_agg(self, data: dict, recv_ts: str, mono: int, session: Any, seq: int) -> None:
        event = normalize_agg_trade(
            data,
            symbol=self.config.symbol,
            local_receive_timestamp=recv_ts,
            local_receive_monotonic_ns=mono,
            connection_session_id=session.connection_session_id,
            reconnect_generation=session.reconnect_generation,
            source_sequence=seq,
            retain_raw_payload=self.config.retain_raw_payload,
        )
        self._last_agg_mono = self._note_interval(self._agg_intervals, self._last_agg_mono)
        self.health.last_agg_trade_receive_time = recv_ts
        self.health.agg_trade_received += 1

        if self.dupes.is_duplicate_agg(self.config.symbol, event.get("aggregate_trade_id")):
            self.health.duplicates_dropped = self.dupes.dropped
            self._emit_operational(
                OperationalEventType.DUPLICATE_DROPPED.value,
                {"stream": "AGG_TRADE", "aggregate_trade_id": event.get("aggregate_trade_id")},
            )
            return

        gap = self.gaps.check_agg_trade(event)
        if gap is not None and gap.gap_type.endswith("GAP"):
            self.health.gaps_detected = self.gaps.gap_count
            self._set_status(HealthStatus.EVENT_SEQUENCE_GAP, {"gap": gap.gap_type})
            self._emit_operational(
                OperationalEventType.SEQUENCE_GAP_DETECTED.value,
                {
                    "gap_type": gap.gap_type,
                    "previous": gap.previous,
                    "current": gap.current,
                    "details": gap.details,
                },
            )

        if self.config.storage_format == "jsonl":
            batch = self.jsonl_writer.append(StreamType.AGG_TRADE, event)
            if batch:
                self.health.last_committed_batch = batch.path
                self.health.last_successful_commit_time = utc_now_iso()
                self.health.events_committed += batch.row_count
        else:
            self._enqueue(StreamType.AGG_TRADE, event)

    def _handle_book(self, data: dict, recv_ts: str, mono: int, session: Any, seq: int) -> None:
        event = normalize_book_ticker(
            data,
            symbol=self.config.symbol,
            local_receive_timestamp=recv_ts,
            local_receive_monotonic_ns=mono,
            connection_session_id=session.connection_session_id,
            reconnect_generation=session.reconnect_generation,
            source_sequence=seq,
            retain_raw_payload=self.config.retain_raw_payload,
        )
        self._last_book_mono = self._note_interval(self._book_intervals, self._last_book_mono)
        self.health.last_book_ticker_receive_time = recv_ts
        self.health.book_ticker_received += 1

        if self.dupes.is_duplicate_book(
            self.config.symbol,
            event.get("update_id"),
            raw_payload_hash=event["raw_payload_hash"],
            connection_session_id=session.connection_session_id,
        ):
            self.health.duplicates_dropped = self.dupes.dropped
            self._emit_operational(
                OperationalEventType.DUPLICATE_DROPPED.value,
                {"stream": "BOOK_TICKER", "update_id": event.get("update_id")},
            )
            return

        gap = self.gaps.check_book_ticker(event)
        if gap is not None and gap.gap_type.endswith("GAP"):
            self.health.gaps_detected = self.gaps.gap_count
            self._emit_operational(
                OperationalEventType.SEQUENCE_GAP_DETECTED.value,
                {"gap_type": gap.gap_type, "previous": gap.previous, "current": gap.current},
            )

        if self.config.storage_format == "jsonl":
            batch = self.jsonl_writer.append(StreamType.BOOK_TICKER, event)
            if batch:
                self.health.last_committed_batch = batch.path
                self.health.last_successful_commit_time = utc_now_iso()
                self.health.events_committed += batch.row_count
        else:
            self._enqueue(StreamType.BOOK_TICKER, event)

    def _on_open(self, _ws: Any) -> None:
        recovered = self.archival.recover_temp_files() + self.jsonl_writer.recover_temp_files()
        if recovered:
            self._emit_operational(
                OperationalEventType.WRITER_RECOVERED.value, {"removed_temp": recovered}
            )
        is_reconnect = self.sessions.reconnect_generation > 0
        if is_reconnect:
            self._emit_operational(OperationalEventType.STREAM_RECONNECTING.value, {})
        session = self.sessions.begin_session()
        self.health.connection_state = "CONNECTED"
        self.health.reconnect_count = max(0, self.sessions.reconnect_generation - 1)
        self.health.connection_session_id = session.connection_session_id
        self.health.reconnect_generation = session.reconnect_generation
        self._ws_failures = 0
        self._session_connected_mono = time.monotonic()
        # Reset per-session receive clocks so stale logic does not close a fresh socket.
        self._last_agg_mono = None
        self._last_book_mono = None
        self._force_reconnect.clear()
        if self.health.health_status in {
            HealthStatus.STREAM_STALE.value,
            HealthStatus.DEGRADED.value,
        }:
            self.health.health_status = HealthStatus.HEALTHY.value
        if is_reconnect:
            self._emit_operational(
                OperationalEventType.STREAM_RECONNECTED.value, session.to_dict()
            )
        else:
            self._emit_operational(
                OperationalEventType.STREAM_CONNECTED.value, session.to_dict()
            )
        self._write_health()

    def _on_close(self, _ws: Any, status_code: Any, msg: Any) -> None:
        reason = f"close:{status_code}:{msg}"
        self.sessions.end_session(reason)
        self.health.connection_state = "DISCONNECTED"
        self._emit_operational(
            OperationalEventType.STREAM_DISCONNECTED.value, {"reason": reason}
        )
        self._write_health()

    def _on_error(self, _ws: Any, error: Any) -> None:
        err = str(error)
        self.health.details["last_ws_error"] = err
        # websocket-client can emit a benign race when closing (`sock` is None).
        if "has no attribute 'sock'" in err:
            return
        self._ws_failures += 1
        self._set_status(HealthStatus.DEGRADED, {"ws_error": err})
        if self._ws_failures >= 10:
            self.request_stop("unrecoverable_websocket_failure", fault=True)

    def _check_staleness(self) -> None:
        # Only while connected; ignore until this session has received events.
        if self.health.connection_state != "CONNECTED":
            return
        now = time.monotonic()
        stale = False
        if self._last_agg_mono is not None and now - self._last_agg_mono > self.config.stale_agg_after_seconds:
            self._set_status(HealthStatus.STREAM_STALE, {"stream": "aggTrade"})
            stale = True
        if self._last_book_mono is not None and now - self._last_book_mono > self.config.stale_book_after_seconds:
            self._set_status(HealthStatus.STREAM_STALE, {"stream": "bookTicker"})
            stale = True
        if stale and self.config.auto_reconnect and not self._stop.is_set():
            self._force_reconnect.set()
            try:
                if self._ws is not None:
                    self._ws.close()
            except Exception:
                pass

    def run(self) -> dict[str, Any]:
        import ssl

        import websocket

        if not self._check_disk():
            self._fault_stop = True
            return self._finalize_metrics()

        recovered = self.archival.recover_temp_files() + self.jsonl_writer.recover_temp_files()
        self.health.collection_started_at = utc_now_iso()
        self.health.process_alive = True
        self.health.pid = os.getpid()
        self._started_mono = time.monotonic()
        # Start archival writer BEFORE websocket threads (disk path off receive path).
        if self.config.storage_format == "parquet":
            # Dedicated archival worker off the websocket receive path.
            # Default is a dedicated writer thread (process mode cannot share
            # BoundedEventQueue without IPC; thread provides fail-closed backpressure).
            self.archival.start_thread()
            self.health.details["archival_worker"] = "thread"
            self.health.details["writer_mode_requested"] = self.config.writer_mode
        self._emit_operational(
            OperationalEventType.COLLECTION_STARTED.value,
            {
                "collection_started_at": self.health.collection_started_at,
                "recovered_temp": recovered,
                "ws_url": self.config.ws_url,
                "min_free_bytes": self.config.min_free_bytes,
                "emergency_min_free_bytes": self.config.emergency_min_free_bytes,
                "storage_format": self.config.storage_format,
                "writer_mode": self.config.writer_mode,
                "chunk_policy": self.config.chunk_policy.__dict__,
                "queue_capacity_events": self.config.queue_capacity_events,
                "queue_capacity_bytes": self.config.queue_capacity_bytes,
            },
        )
        self._write_health()

        def _sig_handler(_signum: int, _frame: Any) -> None:
            self.request_stop("signal", fault=False)

        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)

        while not self._stop.is_set():
            if self.config.duration_seconds is not None:
                if time.monotonic() - self._started_mono >= self.config.duration_seconds:
                    self.request_stop("duration_elapsed", fault=False)
                    break

            self._force_reconnect.clear()
            self._ws = websocket.WebSocketApp(
                self.config.ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )

            def _run_ws() -> None:
                self._ws.run_forever(
                    ping_interval=20,
                    ping_timeout=10,
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                )

            thread = threading.Thread(target=_run_ws, name="raw-event-ws", daemon=True)
            thread.start()

            while thread.is_alive() and not self._stop.is_set():
                if self.config.duration_seconds is not None:
                    if time.monotonic() - self._started_mono >= self.config.duration_seconds:
                        self.request_stop("duration_elapsed", fault=False)
                        break
                self._check_staleness()
                if not self._check_disk():
                    break
                # Health refresh every ~5s (avoid racing message-path writes).
                if int(time.monotonic()) % 5 == 0:
                    self._write_health()
                if self._force_reconnect.is_set():
                    break
                time.sleep(1.0)

            try:
                if self._ws is not None:
                    self._ws.close()
            except Exception:
                pass
            thread.join(timeout=5.0)

            if self._stop.is_set():
                break
            if not self.config.auto_reconnect:
                self.request_stop("websocket_closed_no_reconnect", fault=True)
                break
            self._emit_operational(
                OperationalEventType.STREAM_RECONNECTING.value,
                {"delay_seconds": self.config.reconnect_delay_seconds},
            )
            time.sleep(self.config.reconnect_delay_seconds)

        time.sleep(0.3)
        try:
            if self.config.storage_format == "parquet":
                pending = self.queue.depth
                self.archival.stop(flush=True, timeout=60.0)
                # After stop, queue is closed — use direct append for terminal operational records.
                if pending > 0 and self.queue.depth > 0:
                    self._emit_operational_direct(
                        OperationalEventType.BUFFERED_EVENTS_LOST.value,
                        {"pending_at_stop": pending, "remaining": self.queue.depth},
                    )
                self._emit_operational_direct(
                    OperationalEventType.WRITER_FLUSHED.value,
                    {
                        "final_flush": True,
                        "batches": self.archival.stats.chunks_committed,
                        "writer_stats": self.archival.stats.to_dict(),
                        "queue": self.queue.metrics.to_dict(),
                    },
                )
                self.archival.flush_all()
                batches = list(self.archival.committed)
                self.health.events_committed = self.archival.stats.events_committed
                if batches:
                    self.health.last_committed_batch = batches[-1].path
                    self.health.last_successful_commit_time = batches[-1].created_at
            else:
                batches = self.jsonl_writer.flush_all()
                for b in batches:
                    self.health.events_committed += b.row_count
                    self.health.last_committed_batch = b.path
                    self.health.last_successful_commit_time = utc_now_iso()
                self._emit_operational(
                    OperationalEventType.WRITER_FLUSHED.value,
                    {"final_flush": True, "batches": len(batches)},
                )
                self.jsonl_writer.flush_all()
        except Exception as exc:  # noqa: BLE001
            self.health.write_errors += 1
            self._set_status(HealthStatus.DISK_ERROR, {"error": str(exc)})
            self._fault_stop = True

        self.health.process_alive = False
        self.health.connection_state = "STOPPED"
        self.health.stop_reason = self._stop_reason
        self._refresh_runtime_health()
        self._write_health()
        return self._finalize_metrics()

    def _percentile(self, values: list[float], p: float) -> Optional[float]:
        if not values:
            return None
        s = sorted(values)
        idx = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
        return round(s[idx], 3)

    def _finalize_metrics(self) -> dict[str, Any]:
        duration = max(0.001, time.monotonic() - self._started_mono) if self._started_mono else 0.001
        bytes_written = (
            self.archival.stats.bytes_written
            if self.config.storage_format == "parquet"
            else self.jsonl_writer.bytes_written
        )
        bps, gb_day = estimate_write_rate(
            bytes_written=bytes_written, duration_seconds=duration
        )
        agg_n = self.health.agg_trade_received
        book_n = self.health.book_ticker_received
        intervals = self._agg_intervals + self._book_intervals
        return {
            "duration_seconds": round(duration, 3),
            "aggtrade_event_count": agg_n,
            "bookticker_event_count": book_n,
            "aggtrade_events_per_second": round(agg_n / duration, 3),
            "bookticker_events_per_second": round(book_n / duration, 3),
            "median_receive_interval_ms": self._percentile(intervals, 50),
            "p95_receive_interval_ms": self._percentile(intervals, 95),
            "max_receive_interval_ms": round(max(intervals), 3) if intervals else None,
            "agg_p95_receive_interval_ms": self._percentile(self._agg_intervals, 95),
            "book_p95_receive_interval_ms": self._percentile(self._book_intervals, 95),
            "duplicate_count": self.dupes.dropped,
            "gap_count": self.gaps.gap_count,
            "reconnect_count": self.health.reconnect_count,
            "bytes_written": bytes_written,
            "bytes_per_second": round(bps, 1),
            "estimated_gb_per_day": round(gb_day, 3),
            "health_status": self.health.health_status,
            "events_committed": self.health.events_committed,
            "collection_started_at": self.health.collection_started_at,
            "stop_reason": self._stop_reason,
            "fault_stop": self._fault_stop,
            "storage_format": self.config.storage_format,
            "writer_mode": self.config.writer_mode,
            "queue": self.queue.metrics.to_dict(),
            "writer_stats": self.archival.stats.to_dict(),
            "gaps": [
                {
                    "stream": g.stream,
                    "gap_type": g.gap_type,
                    "previous": g.previous,
                    "current": g.current,
                    "details": g.details,
                }
                for g in self.gaps.gaps
            ],
        }
