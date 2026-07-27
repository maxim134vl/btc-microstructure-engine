"""Unit tests for TRD1A raw event journal."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from btc_ml.feeds.raw_event_journal.dedupe_gap import DuplicateTracker, SequenceMonitor
from btc_ml.feeds.raw_event_journal.disk import check_disk
from btc_ml.feeds.raw_event_journal.normalize import (
    normalize_agg_trade,
    normalize_book_ticker,
)
from btc_ml.feeds.raw_event_journal.precision import decimal_from_payload
from btc_ml.feeds.raw_event_journal.reader import RawEventJournalReader
from btc_ml.feeds.raw_event_journal.schemas import SCHEMA_VERSION, StreamType
from btc_ml.feeds.raw_event_journal.session import SessionManager
from btc_ml.feeds.raw_event_journal.writer import AtomicJournalWriter, BatchPolicy


AGG_PAYLOAD = {
    "e": "aggTrade",
    "E": 1672515782136,
    "a": 12345,
    "s": "BTCUSDT",
    "p": "16500.01000000",
    "q": "0.00100000",
    "f": 100,
    "l": 105,
    "T": 1672515782136,
    "m": True,
}

BOOK_PAYLOAD = {
    "e": "bookTicker",
    "u": 400900217,
    "s": "BTCUSDT",
    "b": "16500.00000000",
    "B": "1.23000000",
    "a": "16500.01000000",
    "A": "0.98000000",
}


def test_agg_trade_normalization():
    ev = normalize_agg_trade(
        AGG_PAYLOAD,
        symbol="BTCUSDT",
        local_receive_timestamp="2023-01-01T00:00:00Z",
        local_receive_monotonic_ns=1,
        connection_session_id="sess",
        reconnect_generation=1,
        source_sequence=1,
    )
    assert ev["stream_type"] == "AGG_TRADE"
    assert ev["schema_version"] == SCHEMA_VERSION
    assert ev["aggregate_trade_id"] == 12345
    assert ev["price"] == "16500.01000000"
    assert ev["quantity"] == "0.00100000"
    assert ev["buyer_is_market_maker"] is True
    assert ev["exchange_event_timestamp"] is not None
    assert ev["exchange_trade_timestamp"] is not None
    assert ev["local_receive_timestamp"] == "2023-01-01T00:00:00Z"
    assert "timestamp" not in ev


def test_book_ticker_normalization_missing_exchange_ts():
    ev = normalize_book_ticker(
        BOOK_PAYLOAD,
        symbol="BTCUSDT",
        local_receive_timestamp="2023-01-01T00:00:01Z",
        local_receive_monotonic_ns=2,
        connection_session_id="sess",
        reconnect_generation=1,
        source_sequence=2,
    )
    assert ev["stream_type"] == "BOOK_TICKER"
    assert ev["exchange_event_timestamp"] is None  # no E in payload
    assert ev["update_id"] == 400900217
    assert ev["spread"] == "0.01000000"
    assert Decimal(ev["mid_price"]) == Decimal("16500.00500000")


def test_missing_optional_fields_are_null():
    sparse = {"p": "1.0", "q": "2.0"}
    ev = normalize_agg_trade(
        sparse,
        symbol="BTCUSDT",
        local_receive_timestamp="2023-01-01T00:00:00Z",
        local_receive_monotonic_ns=1,
        connection_session_id="s",
        reconnect_generation=1,
        source_sequence=1,
    )
    assert ev["aggregate_trade_id"] is None
    assert ev["exchange_event_timestamp"] is None
    assert ev["buyer_is_market_maker"] is None


def test_timestamp_separation():
    ev = normalize_agg_trade(
        AGG_PAYLOAD,
        symbol="BTCUSDT",
        local_receive_timestamp="2023-01-01T00:00:00.123Z",
        local_receive_monotonic_ns=99,
        connection_session_id="s",
        reconnect_generation=1,
        source_sequence=1,
    )
    assert ev["exchange_event_timestamp"] != ev["local_receive_timestamp"]
    assert ev["ingested_at"] is not None
    assert ev["local_receive_monotonic_ns"] == 99


def test_decimal_round_trip():
    raw = "0.00000001"
    got = decimal_from_payload(raw)
    assert got == "0.00000001"
    assert Decimal(got) == Decimal(raw)
    # Must not go through float
    assert decimal_from_payload("16500.01000000") == "16500.01000000"


def test_duplicate_detection():
    d = DuplicateTracker()
    assert not d.is_duplicate_agg("BTCUSDT", 1)
    assert d.is_duplicate_agg("BTCUSDT", 1)
    assert d.dropped == 1
    assert not d.is_duplicate_book("BTCUSDT", 10, raw_payload_hash="h", connection_session_id="s")
    assert d.is_duplicate_book("BTCUSDT", 10, raw_payload_hash="h", connection_session_id="s")
    # fallback hash when update_id missing
    assert not d.is_duplicate_book("BTCUSDT", None, raw_payload_hash="abc", connection_session_id="s1")
    assert d.is_duplicate_book("BTCUSDT", None, raw_payload_hash="abc", connection_session_id="s1")


def test_session_identity_and_reconnect_generation():
    sm = SessionManager()
    s1 = sm.begin_session()
    assert s1.reconnect_generation == 1
    ended = sm.end_session("test")
    assert ended.disconnect_reason == "test"
    s2 = sm.begin_session()
    assert s2.reconnect_generation == 2
    assert s2.connection_session_id != s1.connection_session_id


def test_sequence_gap_detection():
    mon = SequenceMonitor()
    e1 = {"aggregate_trade_id": 10, "first_trade_id": 100, "last_trade_id": 105}
    e2 = {"aggregate_trade_id": 12, "first_trade_id": 110, "last_trade_id": 115}
    assert mon.check_agg_trade(e1) is None
    gap = mon.check_agg_trade(e2)
    assert gap is not None
    assert gap.gap_type == "AGGREGATE_TRADE_ID_GAP"
    assert mon.gap_count == 1


def test_atomic_batch_commit_and_manifest(tmp_path: Path):
    w = AtomicJournalWriter(tmp_path, policy=BatchPolicy(max_events_per_batch=2, max_seconds_per_batch=60))
    for i in range(2):
        ev = normalize_agg_trade(
            {**AGG_PAYLOAD, "a": 100 + i, "f": 200 + i, "l": 200 + i},
            symbol="BTCUSDT",
            local_receive_timestamp=f"2026-07-25T12:00:0{i}Z",
            local_receive_monotonic_ns=i,
            connection_session_id="sess-aaa",
            reconnect_generation=1,
            source_sequence=i + 1,
        )
        batch = w.append(StreamType.AGG_TRADE, ev)
    assert batch is not None
    final = tmp_path / batch.path
    assert final.exists()
    assert not list(tmp_path.rglob("*.tmp"))
    text = final.read_text(encoding="utf-8")
    assert text.count("\n") == 2
    # immutable: content checksum stable
    digest1 = __import__("hashlib").sha256(final.read_bytes()).hexdigest()
    digest2 = __import__("hashlib").sha256(final.read_bytes()).hexdigest()
    assert digest1 == digest2
    man = list((tmp_path / "manifests").rglob("batches.jsonl"))
    assert man
    meta = json.loads(man[0].read_text(encoding="utf-8").strip().splitlines()[0])
    assert meta["checksum"]
    assert meta["row_count"] == 2


def test_batch_ordering_names_sortable(tmp_path: Path):
    w = AtomicJournalWriter(tmp_path, policy=BatchPolicy(max_events_per_batch=1, max_seconds_per_batch=60))
    paths = []
    for i in range(3):
        ev = normalize_book_ticker(
            {**BOOK_PAYLOAD, "u": 1000 + i},
            symbol="BTCUSDT",
            local_receive_timestamp=f"2026-07-25T12:00:0{i}Z",
            local_receive_monotonic_ns=i,
            connection_session_id="sess",
            reconnect_generation=1,
            source_sequence=i + 1,
        )
        b = w.append(StreamType.BOOK_TICKER, ev)
        assert b is not None
        paths.append(b.path)
    assert paths == sorted(paths)


def test_graceful_final_flush(tmp_path: Path):
    w = AtomicJournalWriter(tmp_path, policy=BatchPolicy(max_events_per_batch=100, max_seconds_per_batch=60))
    ev = normalize_agg_trade(
        AGG_PAYLOAD,
        symbol="BTCUSDT",
        local_receive_timestamp="2026-07-25T12:00:00Z",
        local_receive_monotonic_ns=1,
        connection_session_id="s",
        reconnect_generation=1,
        source_sequence=1,
    )
    assert w.append(StreamType.AGG_TRADE, ev) is None
    batches = w.flush_all()
    assert len(batches) == 1
    assert batches[0].row_count == 1


def test_reader_schema_checksum_gap(tmp_path: Path):
    w = AtomicJournalWriter(tmp_path, policy=BatchPolicy(max_events_per_batch=10, max_seconds_per_batch=60))
    for aid in (1, 2, 4):
        ev = normalize_agg_trade(
            {**AGG_PAYLOAD, "a": aid, "f": aid, "l": aid},
            symbol="BTCUSDT",
            local_receive_timestamp="2026-07-25T12:00:00Z",
            local_receive_monotonic_ns=aid,
            connection_session_id="s",
            reconnect_generation=1,
            source_sequence=aid,
        )
        w.append(StreamType.AGG_TRADE, ev)
    w.flush_all()
    reader = RawEventJournalReader(tmp_path)
    result = reader.read_stream(StreamType.AGG_TRADE)
    assert len(result.events) == 3
    assert any(g["gap_type"] == "AGGREGATE_TRADE_ID_GAP" for g in result.gaps)
    # checksum verify
    for path in reader.list_batch_files(StreamType.AGG_TRADE):
        digest, ok = reader.verify_batch_checksum(path)
        assert ok and len(digest) == 64


def test_disk_low_fail_closed(tmp_path: Path):
    # Force min_free absurdly high so any volume looks low
    status = check_disk(tmp_path, min_free_bytes=10**18)
    assert status.is_low is True
    w = AtomicJournalWriter(tmp_path)
    w.block_writes("disk_low")
    ev = normalize_agg_trade(
        AGG_PAYLOAD,
        symbol="BTCUSDT",
        local_receive_timestamp="2026-07-25T12:00:00Z",
        local_receive_monotonic_ns=1,
        connection_session_id="s",
        reconnect_generation=1,
        source_sequence=1,
    )
    with pytest.raises(RuntimeError, match="writer_blocked"):
        w.append(StreamType.AGG_TRADE, ev)
