#!/usr/bin/env python3
"""LIVE1A durable intrabar cognition service (paper-only shadow path).

Fans out normalized spot aggTrade/bookTicker to:
  1) online provisional cognition → CONTEXT_* journal
  2) async Parquet/Zstd archival writer (data/raw_market_events_v2)

Does NOT touch paper manager/traders or void legacy epochs.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import ssl
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from btc_ml.feeds.raw_event_journal.archival_writer import ArchivalParquetWriter, ChunkPolicy  # noqa: E402
from btc_ml.feeds.raw_event_journal.normalize import (  # noqa: E402
    normalize_agg_trade,
    normalize_book_ticker,
    normalize_operational,
)
from btc_ml.feeds.raw_event_journal.queue import BoundedEventQueue  # noqa: E402
from btc_ml.feeds.raw_event_journal.schemas import OperationalEventType, StreamType  # noqa: E402
from btc_ml.feeds.raw_event_journal.session import SessionManager  # noqa: E402
from btc_ml.feeds.raw_event_journal.timestamps import capture_local_receive, utc_now_iso  # noqa: E402
from btc_ml.live.intrabar.atomic_json import atomic_write_json  # noqa: E402
from btc_ml.live.intrabar.cognition_pipeline import IntrabarCognitionEngine  # noqa: E402
from btc_ml.live.intrabar.closed_bar_event_bridge import ClosedBarContextEventBridge  # noqa: E402
from btc_ml.live.intrabar.context_event_journal import ContextEventJournal  # noqa: E402

try:
    import websocket  # type: ignore
except ImportError:  # pragma: no cover
    websocket = None


DEFAULT_WS = "wss://stream.binance.com:9443/stream?streams=btcusdt@aggTrade/btcusdt@bookTicker"


class IntrabarCognitionService:
    def __init__(
        self,
        *,
        journal_root: Path,
        context_root: Path,
        health_path: Path,
        pid_file: Path,
        symbol: str = "BTCUSDT",
    ):
        self.journal_root = Path(journal_root)
        self.context_root = Path(context_root)
        self.health_path = Path(health_path)
        self.pid_file = Path(pid_file)
        self.symbol = symbol
        self.queue = BoundedEventQueue(capacity_events=50_000, capacity_bytes=64 * 1024 * 1024)
        self.writer = ArchivalParquetWriter(
            root=self.journal_root,
            queue=self.queue,
            policy=ChunkPolicy(
                max_events_per_chunk=50_000,
                max_seconds_per_chunk=60.0,
                compression="zstd",
                compression_level=6,
            ),
        )
        self.session = SessionManager()
        self.engine = IntrabarCognitionEngine(
            context_journal=ContextEventJournal(self.context_root),
        )
        self.closed_bar_bridge = ClosedBarContextEventBridge(
            repo_root=ROOT,
            context_journal=self.engine.journal,
        )
        self.closed_bar_bridge_last_poll_mono = 0
        self.closed_bar_bridge_poll_interval_ns = 1_000_000_000
        self._stop = threading.Event()
        self._ws = None
        self._source_seq = 0
        self._lock = threading.Lock()
        self.started_at = utc_now_iso()
        self.last_agg: Optional[str] = None
        self.last_book: Optional[str] = None
        self.recv_counts = {"aggTrade": 0, "bookTicker": 0}
        self.errors: list[str] = []

    def write_pid(self) -> None:
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def clear_pid(self) -> None:
        if self.pid_file.exists():
            self.pid_file.unlink(missing_ok=True)

    def _open_journal_event(self, timeframe: str) -> dict[str, Any] | None:
        """Last unfinished CONTEXT_START/FLIP for TF from durable journal."""
        path = Path(self.context_root) / "events.jsonl"
        if not path.exists():
            return None
        open_ev: dict[str, Any] | None = None
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("timeframe") or "").upper() != timeframe.upper():
                    continue
                et = str(raw.get("event_type") or "").upper()
                if et in {"CONTEXT_START", "CONTEXT_FLIP"}:
                    open_ev = raw
                elif et == "CONTEXT_END":
                    open_ev = None
        except OSError:
            return None
        return open_ev

    def _provisional_tip_row(self, timeframe: str, eval_row: dict[str, Any]) -> dict[str, Any]:
        """Export provisional vs active context without collapsing lineage."""
        synth = eval_row.get("synthesis") if isinstance(eval_row.get("synthesis"), dict) else {}
        life = eval_row.get("lifecycle") if isinstance(eval_row.get("lifecycle"), dict) else {}
        provisional = synth.get("market_context")
        active = life.get("active_market_context")
        lifecycle_state = life.get("lifecycle_state")
        tip: dict[str, Any] = {
            # Backward-compat aliases used by OPS/visual consumers.
            "market_context": provisional,
            "lifecycle": lifecycle_state,
            "active": active,
            # Explicit OPS1.8 fields.
            "provisional_market_context": provisional,
            "active_market_context": active,
            "lifecycle_state": lifecycle_state,
            "lifecycle_episode_id": None,
            "context_event_id": None,
            "context_started_at": None,
            "context_price": None,
        }
        active_u = str(active or "").strip().upper()
        last_ev = self.engine.last_context_event.get(timeframe)
        if not isinstance(last_ev, dict):
            last_ev = {}
        # Recover unfinished START/FLIP after process restart (in-memory lifecycle empty).
        if active_u not in {"LONG", "LONG_CONTEXT", "SHORT", "SHORT_CONTEXT"}:
            if not last_ev:
                last_ev = self._open_journal_event(timeframe) or {}
            et = str(last_ev.get("event_type") or "").upper()
            new_ctx = str(last_ev.get("new_context") or "").upper()
            if et in {"CONTEXT_START", "CONTEXT_FLIP"} and new_ctx in {
                "LONG",
                "LONG_CONTEXT",
                "SHORT",
                "SHORT_CONTEXT",
            }:
                active = last_ev.get("new_context")
                active_u = str(active or "").strip().upper()
                tip["active"] = active
                tip["active_market_context"] = active
                if str(lifecycle_state or "").upper() in {"", "NO_ACTIVE_CONTEXT", "OBSERVE", "NONE"}:
                    tip["lifecycle"] = "ACTIVE"
                    tip["lifecycle_state"] = "ACTIVE"
                    lifecycle_state = "ACTIVE"
                # Rehydrate engine mirrors so subsequent tips stay consistent.
                if timeframe not in self.engine.last_context_event and last_ev:
                    self.engine.last_context_event[timeframe] = last_ev
                ep = last_ev.get("lifecycle_episode_id")
                if ep and timeframe not in self.engine._active_episode:
                    self.engine._active_episode[timeframe] = str(ep)
        if active_u not in {"LONG", "LONG_CONTEXT", "SHORT", "SHORT_CONTEXT"}:
            return tip
        et = str(last_ev.get("event_type") or "").upper()
        tip["lifecycle_episode_id"] = (
            self.engine._active_episode.get(timeframe)
            or last_ev.get("lifecycle_episode_id")
        )
        if et in {"CONTEXT_START", "CONTEXT_FLIP"}:
            tip["context_event_id"] = last_ev.get("context_event_id")
            tip["context_started_at"] = last_ev.get("event_timestamp") or last_ev.get(
                "context_started_at"
            )
            tip["context_price"] = last_ev.get("context_event_price")
        return tip

    def write_health(self) -> None:
        payload = {
            "service": "intrabar_cognition",
            "pid": os.getpid(),
            "alive": not self._stop.is_set(),
            "started_at": self.started_at,
            "updated_at": utc_now_iso(),
            "symbol": self.symbol,
            "streams": {
                "aggTrade": {"received": self.recv_counts["aggTrade"], "last": self.last_agg},
                "bookTicker": {"received": self.recv_counts["bookTicker"], "last": self.last_book},
            },
            "partial_bars": self.engine.bars.snapshot(),
            "last_provisional_eval": {
                tf: self._provisional_tip_row(tf, v)
                for tf, v in self.engine.last_eval.items()
            },
            "last_context_event": self.engine.last_context_event,
            "context_event_counts": self.engine.event_counts,
            "closed_bar_event_bridge": {
                "provider_id": self.closed_bar_bridge.provider_id,
                "bridge_activated_at": self.closed_bar_bridge.bridge_activated_at,
                "last_run_at": self.closed_bar_bridge.last_run_at,
                "last_result": self.closed_bar_bridge.last_result.to_dict(),
            },
            "queue": self.queue.metrics.to_dict(),
            "writer": self.writer.stats.to_dict(),
            "journal_root": str(self.journal_root),
            "context_journal": str(self.context_root),
            "errors": self.errors[-20:],
            "paper_execution": False,
            "real_execution": False,
        }
        atomic_write_json(self.health_path, payload)

    def _enqueue(self, stream: StreamType, event: dict[str, Any]) -> None:
        try:
            ok = self.queue.try_enqueue(stream, event)
            if not ok:
                self.errors.append("queue:backpressure_reject")
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"queue:{exc}")

    def _maybe_materialize_closed_bar_context_event(self, receive_mono: int) -> None:
        if receive_mono - self.closed_bar_bridge_last_poll_mono < self.closed_bar_bridge_poll_interval_ns:
            return
        self.closed_bar_bridge_last_poll_mono = receive_mono
        try:
            result = self.closed_bar_bridge.maybe_materialize(current_bbo=self.engine.bbo)
            if result.emitted_count:
                self.errors.append(f"closed_bar_bridge:emitted:{result.emitted_count}")
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"closed_bar_bridge:{type(exc).__name__}:{exc}")
            self.errors = self.errors[-50:]

    def _on_message(self, _ws: Any, message: str) -> None:
        try:
            outer = json.loads(message)
            data = outer.get("data") or outer
            stream = str(outer.get("stream") or "")
            local_ts, mono = capture_local_receive()
            with self._lock:
                self._source_seq += 1
                seq = self._source_seq
            sess = self.session.current
            sid = sess.connection_session_id if sess else None
            gen = sess.reconnect_generation if sess else 0
            if "aggTrade" in stream or data.get("e") == "aggTrade":
                event = normalize_agg_trade(
                    data,
                    symbol=self.symbol,
                    local_receive_timestamp=local_ts,
                    local_receive_monotonic_ns=mono,
                    connection_session_id=str(sid),
                    reconnect_generation=int(gen or 0),
                    source_sequence=seq,
                )
                self.last_agg = local_ts
                self.recv_counts["aggTrade"] += 1
                self._enqueue(StreamType.AGG_TRADE, event)
                try:
                    self.engine.on_agg_trade(event)
                    self._maybe_materialize_closed_bar_context_event(int(mono))
                except Exception as exc:  # noqa: BLE001
                    self.errors.append(f"cognition_agg:{type(exc).__name__}:{exc}")
            elif "bookTicker" in stream or data.get("e") == "bookTicker" or (
                "b" in data and "a" in data and "u" in data and "s" in data
            ):
                event = normalize_book_ticker(
                    data,
                    symbol=self.symbol,
                    local_receive_timestamp=local_ts,
                    local_receive_monotonic_ns=mono,
                    connection_session_id=str(sid),
                    reconnect_generation=int(gen or 0),
                    source_sequence=seq,
                )
                self.last_book = local_ts
                self.recv_counts["bookTicker"] += 1
                self._enqueue(StreamType.BOOK_TICKER, event)
                try:
                    self.engine.on_book_ticker(event)
                    self._maybe_materialize_closed_bar_context_event(int(mono))
                except Exception as exc:  # noqa: BLE001
                    self.errors.append(f"cognition_book:{type(exc).__name__}:{exc}")
            if (self.recv_counts["aggTrade"] + self.recv_counts["bookTicker"]) % 50 == 0:
                self.write_health()
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"message:{type(exc).__name__}:{exc}")

    def request_stop(self, reason: str = "signal") -> None:
        self._stop.set()
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        op = normalize_operational(
            OperationalEventType.COLLECTION_STOPPED.value
            if hasattr(OperationalEventType.COLLECTION_STOPPED, "value")
            else str(OperationalEventType.COLLECTION_STOPPED),
            symbol=self.symbol,
            local_receive_timestamp=utc_now_iso(),
            local_receive_monotonic_ns=time.time_ns(),
            connection_session_id=None,
            reconnect_generation=0,
            details={"reason": reason, "fault": False},
        )
        self._enqueue(StreamType.OPERATIONAL, op)

    def run(self) -> int:
        if websocket is None:
            raise RuntimeError("websocket-client required")
        self.write_pid()
        self.writer.recover_temp_files()
        self.writer.start_thread()
        self.session.begin_session()
        self.write_health()

        def _sig(_signum: int, _frame: Any) -> None:
            self.request_stop("signal")

        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)

        def _heartbeat() -> None:
            while not self._stop.is_set():
                try:
                    self.write_health()
                except Exception as exc:  # noqa: BLE001
                    self.errors.append(f"health:{exc}")
                self._stop.wait(5.0)

        threading.Thread(target=_heartbeat, name="intrabar-health", daemon=True).start()

        sslopt = {"cert_reqs": ssl.CERT_NONE}

        def _on_open(_ws: Any) -> None:
            self.errors.append("ws:opened")

        def _on_error(_ws: Any, err: Any) -> None:
            self.errors.append(f"ws_error:{err}")

        def _on_close(_ws: Any, *args: Any) -> None:
            self.errors.append(f"ws:closed:{args}")

        while not self._stop.is_set():
            try:
                self._ws = websocket.WebSocketApp(
                    DEFAULT_WS,
                    on_message=self._on_message,
                    on_open=_on_open,
                    on_error=_on_error,
                    on_close=_on_close,
                )
                self._ws.run_forever(sslopt=sslopt, ping_interval=20, ping_timeout=10)
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"ws:{exc}")
            if self._stop.is_set():
                break
            time.sleep(5.0)
        self.writer.stop(flush=True)
        self.write_health()
        self.clear_pid()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LIVE1A intrabar cognition service")
    parser.add_argument("--journal-root", type=Path, default=ROOT / "data" / "raw_market_events_v2")
    parser.add_argument(
        "--context-root",
        type=Path,
        default=ROOT / "data" / "cognition" / "intrabar_context_events",
    )
    parser.add_argument(
        "--health-path",
        type=Path,
        default=ROOT / "data" / "runtime" / "intrabar_cognition_health.json",
    )
    parser.add_argument("--pid-file", type=Path, default=ROOT / "run" / "intrabar_cognition.pid")
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args()
    svc = IntrabarCognitionService(
        journal_root=args.journal_root,
        context_root=args.context_root,
        health_path=args.health_path,
        pid_file=args.pid_file,
        symbol=args.symbol,
    )
    return svc.run()


if __name__ == "__main__":
    raise SystemExit(main())
