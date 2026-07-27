"""Shadow collector: Binance combined aggTrade + bookTicker → journal."""

from __future__ import annotations

import json
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .dedupe_gap import DuplicateTracker, SequenceMonitor
from .disk import check_disk, estimate_write_rate
from .health import HealthSnapshot, HealthStatus
from .normalize import normalize_agg_trade, normalize_book_ticker, normalize_operational
from .schemas import OperationalEventType, StreamType
from .session import SessionManager
from .timestamps import capture_local_receive, utc_now_iso
from .writer import AtomicJournalWriter, BatchPolicy

DEFAULT_WS_URL = (
    "wss://stream.binance.com:9443/stream?streams=btcusdt@aggTrade/btcusdt@bookTicker"
)
DEFAULT_SYMBOL = "BTCUSDT"


@dataclass
class CollectorConfig:
    journal_root: Path
    health_path: Path
    symbol: str = DEFAULT_SYMBOL
    ws_url: str = DEFAULT_WS_URL
    duration_seconds: Optional[float] = None
    min_free_bytes: int = 2 * 1024**3  # 2 GiB fail-closed
    stale_after_seconds: float = 30.0
    retain_raw_payload: bool = False
    batch_policy: BatchPolicy = field(
        default_factory=lambda: BatchPolicy(
            max_events_per_batch=500,
            max_seconds_per_batch=2.0,
            max_buffered_bytes=512_000,
        )
    )
    disk_check_every_events: int = 200


class RawMarketEventCollector:
    def __init__(self, config: CollectorConfig):
        self.config = config
        self.writer = AtomicJournalWriter(config.journal_root, policy=config.batch_policy)
        self.sessions = SessionManager()
        self.dupes = DuplicateTracker()
        self.gaps = SequenceMonitor()
        self.health = HealthSnapshot()
        self._stop = threading.Event()
        self._source_seq = 0
        self._lock = threading.Lock()
        self._ws = None
        self._started_mono = 0.0
        self._agg_intervals: list[float] = []
        self._book_intervals: list[float] = []
        self._last_agg_mono: Optional[float] = None
        self._last_book_mono: Optional[float] = None
        self._events_since_disk_check = 0

    def request_stop(self, reason: str = "stop_requested") -> None:
        self._stop.set()
        self._emit_operational(OperationalEventType.COLLECTION_STOPPED.value, {"reason": reason})
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass

    def _write_health(self) -> None:
        self.config.health_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.health.to_dict()
        self.config.health_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
            reconnect_generation=session.reconnect_generation if session else self.sessions.reconnect_generation,
            details=details,
        )
        try:
            batch = self.writer.append(StreamType.OPERATIONAL, event)
            if batch:
                self.health.last_committed_batch = batch.path
                self.health.events_committed += batch.row_count
        except Exception as exc:  # noqa: BLE001
            self.health.write_errors += 1
            self._set_status(HealthStatus.WRITER_BLOCKED, {"error": str(exc)})

    def _check_disk(self) -> bool:
        status = check_disk(self.config.journal_root, min_free_bytes=self.config.min_free_bytes)
        if status.is_low:
            self._set_status(
                HealthStatus.DISK_LOW,
                {"free_bytes": status.free_bytes, "min_free_bytes": status.min_free_bytes},
            )
            self._emit_operational(
                OperationalEventType.DISK_LOW.value,
                {"free_bytes": status.free_bytes, "free_gb": status.free_gb},
            )
            try:
                self.writer.block_writes("disk_low")
            except Exception:
                pass
            self.request_stop("disk_low")
            return False
        return True

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
            self.health.current_buffer_size = self.writer.buffer_size
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
                    self._set_status(HealthStatus.SCHEMA_ERROR, {"error": msg})
                else:
                    self._set_status(HealthStatus.WRITER_BLOCKED, {"error": msg})
                self.request_stop("writer_failure")

            if self.config.duration_seconds is not None:
                if time.monotonic() - self._started_mono >= self.config.duration_seconds:
                    self.request_stop("duration_elapsed")

            # Stale check
            now = time.monotonic()
            if self._last_agg_mono and now - self._last_agg_mono > self.config.stale_after_seconds:
                self._set_status(HealthStatus.STREAM_STALE, {"stream": "aggTrade"})
            if self._last_book_mono and now - self._last_book_mono > self.config.stale_after_seconds:
                self._set_status(HealthStatus.STREAM_STALE, {"stream": "bookTicker"})

            if self.health.events_received % 50 == 0:
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
        now_m = time.monotonic()
        if self._last_agg_mono is not None:
            self._agg_intervals.append((now_m - self._last_agg_mono) * 1000.0)
        self._last_agg_mono = now_m
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

        batch = self.writer.append(StreamType.AGG_TRADE, event)
        if batch:
            self.health.last_committed_batch = batch.path
            self.health.events_committed += batch.row_count
            self._emit_operational(
                OperationalEventType.WRITER_FLUSHED.value,
                {"path": batch.path, "row_count": batch.row_count},
            )

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
        now_m = time.monotonic()
        if self._last_book_mono is not None:
            self._book_intervals.append((now_m - self._last_book_mono) * 1000.0)
        self._last_book_mono = now_m
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

        batch = self.writer.append(StreamType.BOOK_TICKER, event)
        if batch:
            self.health.last_committed_batch = batch.path
            self.health.events_committed += batch.row_count

    def _on_open(self, _ws: Any) -> None:
        recovered = self.writer.recover_temp_files()
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
        self.health.details["last_ws_error"] = str(error)
        self._set_status(HealthStatus.DEGRADED, {"ws_error": str(error)})

    def run(self) -> dict[str, Any]:
        import ssl

        import websocket

        if not self._check_disk():
            return self._finalize_metrics()

        recovered = self.writer.recover_temp_files()
        self.health.collection_started_at = utc_now_iso()
        self.health.process_alive = True
        self._started_mono = time.monotonic()
        self._emit_operational(
            OperationalEventType.COLLECTION_STARTED.value,
            {
                "collection_started_at": self.health.collection_started_at,
                "recovered_temp": recovered,
                "ws_url": self.config.ws_url,
            },
        )
        self._write_health()

        def _sig_handler(_signum: int, _frame: Any) -> None:
            self.request_stop("signal")

        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)

        self._ws = websocket.WebSocketApp(
            self.config.ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        def _run_ws() -> None:
            # Match live_binance_feed_v2 SSL posture for environments with
            # intercepting TLS (self-signed chain). Does not alter that collector.
            self._ws.run_forever(
                ping_interval=20,
                ping_timeout=10,
                sslopt={"cert_reqs": ssl.CERT_NONE},
            )

        thread = threading.Thread(target=_run_ws, name="raw-event-ws", daemon=True)
        thread.start()

        while not self._stop.is_set():
            if self.config.duration_seconds is not None:
                if time.monotonic() - self._started_mono >= self.config.duration_seconds:
                    self.request_stop("duration_elapsed")
                    break
            time.sleep(0.2)

        # Allow in-flight close
        time.sleep(0.3)
        try:
            batches = self.writer.flush_all()
            for b in batches:
                self.health.events_committed += b.row_count
                self.health.last_committed_batch = b.path
            self._emit_operational(
                OperationalEventType.WRITER_FLUSHED.value,
                {"final_flush": True, "batches": len(batches)},
            )
            # final operational may still be buffered
            self.writer.flush_all()
        except Exception as exc:  # noqa: BLE001
            self.health.write_errors += 1
            self._set_status(HealthStatus.DISK_ERROR, {"error": str(exc)})

        self.health.process_alive = False
        self.health.connection_state = "STOPPED"
        self.health.current_buffer_size = self.writer.buffer_size
        self.health.duplicates_dropped = self.dupes.dropped
        self.health.gaps_detected = self.gaps.gap_count
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
        bps, gb_day = estimate_write_rate(
            bytes_written=self.writer.bytes_written, duration_seconds=duration
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
            "duplicate_count": self.dupes.dropped,
            "gap_count": self.gaps.gap_count,
            "reconnect_count": self.health.reconnect_count,
            "bytes_written": self.writer.bytes_written,
            "bytes_per_second": round(bps, 1),
            "estimated_gb_per_day": round(gb_day, 3),
            "health_status": self.health.health_status,
            "events_committed": self.health.events_committed,
            "collection_started_at": self.health.collection_started_at,
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
