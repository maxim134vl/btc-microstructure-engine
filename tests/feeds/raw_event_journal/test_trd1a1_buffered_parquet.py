"""TRD1A.1 tests: bounded queue, parquet precision, crash recovery, parity."""

from __future__ import annotations

import os
import signal
import time
from decimal import Decimal
from pathlib import Path

import pytest

from btc_ml.feeds.raw_event_journal.archival_writer import ArchivalParquetWriter, ChunkPolicy
from btc_ml.feeds.raw_event_journal.normalize import normalize_agg_trade, normalize_book_ticker
from btc_ml.feeds.raw_event_journal.parquet_schema import (
    DECIMAL_SCALE,
    format_decimal_text,
    to_decimal,
)
from btc_ml.feeds.raw_event_journal.queue import BoundedEventQueue
from btc_ml.feeds.raw_event_journal.reader import RawEventJournalReader
from btc_ml.feeds.raw_event_journal.schemas import StreamType
from btc_ml.feeds.raw_event_journal.writer import AtomicJournalWriter, BatchPolicy


AGG = {
    "e": "aggTrade",
    "E": 1672515782136,
    "a": 1,
    "p": "64969.99000000",
    "q": "0.00100000",
    "f": 10,
    "l": 10,
    "T": 1672515782136,
    "m": False,
}
BOOK = {
    "e": "bookTicker",
    "u": 100,
    "b": "64969.98000000",
    "B": "1.5",
    "a": "64969.99000000",
    "A": "2.0",
}


def _agg(a: int, mono: int = 1, sess: str = "s1"):
    return normalize_agg_trade(
        {**AGG, "a": a, "f": a, "l": a},
        symbol="BTCUSDT",
        local_receive_timestamp="2026-07-28T00:00:00Z",
        local_receive_monotonic_ns=mono,
        connection_session_id=sess,
        reconnect_generation=1,
        source_sequence=a,
    )


def _book(u: int, mono: int = 1, sess: str = "s1"):
    return normalize_book_ticker(
        {**BOOK, "u": u},
        symbol="BTCUSDT",
        local_receive_timestamp="2026-07-28T00:00:00Z",
        local_receive_monotonic_ns=mono,
        connection_session_id=sess,
        reconnect_generation=1,
        source_sequence=u,
    )


def test_decimal_round_trip_binance_price():
    raw = "64969.99000000"
    assert format_decimal_text(raw) == raw
    assert to_decimal(raw) == Decimal(raw)
    assert Decimal(format_decimal_text(raw)) == Decimal(raw)


def test_bounded_queue_backpressure_no_silent_drop():
    q = BoundedEventQueue(capacity_events=2, capacity_bytes=10_000)
    assert q.try_enqueue(StreamType.AGG_TRADE, _agg(1))
    assert q.try_enqueue(StreamType.AGG_TRADE, _agg(2))
    assert q.try_enqueue(StreamType.AGG_TRADE, _agg(3)) is False
    assert q.metrics.enqueue_rejected == 1
    assert q.depth == 2  # no silent drop


def test_parquet_atomic_commit_and_precision(tmp_path: Path):
    q = BoundedEventQueue()
    w = ArchivalParquetWriter(
        tmp_path, q, policy=ChunkPolicy(max_events_per_chunk=2, max_seconds_per_chunk=60)
    )
    ev = _agg(1)
    assert ev["price"] == "64969.99000000"
    b = w.append_direct(StreamType.AGG_TRADE, ev)
    assert b is None
    w.append_direct(StreamType.AGG_TRADE, _agg(2, mono=2))
    # second triggers flush
    assert w.stats.chunks_committed == 1
    reader = RawEventJournalReader(tmp_path)
    result = reader.read_stream(StreamType.AGG_TRADE)
    assert len(result.events) == 2
    assert result.events[0]["price"] == "64969.99000000"
    assert result.events[0]["quantity"] == "0.00100000"
    path = tmp_path / w.committed[0].path
    digest, ok = reader.verify_batch_checksum(path, w.committed[0].checksum)
    assert ok and digest == w.committed[0].checksum


def test_receive_path_has_no_disk_wait(tmp_path: Path):
    """Enqueue returns quickly even if writer is slow (simulated by not starting writer)."""
    q = BoundedEventQueue(capacity_events=1000, capacity_bytes=10_000_000)
    t0 = time.monotonic()
    for i in range(100):
        assert q.try_enqueue(StreamType.BOOK_TICKER, _book(1000 + i, mono=i))
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert elapsed_ms < 500  # no fsync on receive path
    assert q.metrics.enqueue_latency_ms_max < 50


def test_jsonl_parquet_event_parity(tmp_path: Path):
    events = [_agg(i, mono=i) for i in range(1, 21)] + [_book(2000 + i, mono=100 + i) for i in range(20)]
    jsonl_root = tmp_path / "jsonl"
    pq_root = tmp_path / "parquet"
    jw = AtomicJournalWriter(jsonl_root, policy=BatchPolicy(max_events_per_batch=100, max_seconds_per_batch=60))
    q = BoundedEventQueue()
    pw = ArchivalParquetWriter(
        pq_root, q, policy=ChunkPolicy(max_events_per_chunk=100, max_seconds_per_chunk=60)
    )
    for ev in events:
        stream = StreamType(ev["stream_type"])
        if stream is StreamType.AGG_TRADE:
            jw.append(stream, ev)
            pw.append_direct(stream, ev)
        else:
            jw.append(stream, ev)
            pw.append_direct(stream, ev)
    jw.flush_all()
    pw.flush_all()
    jr = RawEventJournalReader(jsonl_root)
    pr = RawEventJournalReader(pq_root)
    j_agg = jr.read_stream(StreamType.AGG_TRADE).events
    p_agg = pr.read_stream(StreamType.AGG_TRADE).events
    assert [e["aggregate_trade_id"] for e in j_agg] == [e["aggregate_trade_id"] for e in p_agg]
    assert [e["raw_payload_hash"] for e in j_agg] == [e["raw_payload_hash"] for e in p_agg]
    for a, b in zip(j_agg, p_agg):
        assert Decimal(a["price"]) == Decimal(b["price"])
        assert Decimal(a["quantity"]) == Decimal(b["quantity"])
        assert a["local_receive_timestamp"] == b["local_receive_timestamp"]
    j_book = jr.read_stream(StreamType.BOOK_TICKER).events
    p_book = pr.read_stream(StreamType.BOOK_TICKER).events
    assert [e["update_id"] for e in j_book] == [e["update_id"] for e in p_book]


def test_temp_crash_not_committed(tmp_path: Path):
    part = tmp_path / "agg_trade" / "date=2026-07-28" / "hour=00"
    part.mkdir(parents=True)
    tmp = part / "broken.parquet.tmp"
    tmp.write_bytes(b"not-a-parquet")
    q = BoundedEventQueue()
    w = ArchivalParquetWriter(tmp_path, q)
    recovered = w.recover_temp_files()
    assert recovered
    assert not tmp.exists()
    assert RawEventJournalReader(tmp_path).read_stream(StreamType.AGG_TRADE).events == []


def test_writer_lag_and_queue_metrics(tmp_path: Path):
    q = BoundedEventQueue(capacity_events=100, capacity_bytes=1_000_000)
    w = ArchivalParquetWriter(
        tmp_path, q, policy=ChunkPolicy(max_events_per_chunk=50, max_seconds_per_chunk=60)
    )
    w.start_thread()
    for i in range(30):
        assert q.try_enqueue(StreamType.AGG_TRADE, _agg(i + 1, mono=i))
    time.sleep(0.5)
    w.stop(flush=True)
    assert q.metrics.dequeued >= 30
    assert w.stats.events_committed >= 30
    assert q.metrics.writer_lag_ms_max >= 0


def test_sigterm_flush_committed(tmp_path: Path):
    """Simulate graceful stop: buffered events flushed; tmp not promoted."""
    q = BoundedEventQueue()
    w = ArchivalParquetWriter(
        tmp_path, q, policy=ChunkPolicy(max_events_per_chunk=1000, max_seconds_per_chunk=60)
    )
    w.start_thread()
    for i in range(10):
        q.try_enqueue(StreamType.BOOK_TICKER, _book(i + 1, mono=i))
    w.stop(flush=True)
    result = RawEventJournalReader(tmp_path).read_stream(StreamType.BOOK_TICKER)
    assert len(result.events) == 10
    assert not list(tmp_path.rglob("*.tmp"))
