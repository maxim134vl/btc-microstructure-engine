"""Integration tests for TRD1A raw event journal (fixture-driven, no live writes)."""

from __future__ import annotations

import json
from pathlib import Path

from btc_ml.feeds.raw_event_journal.dedupe_gap import DuplicateTracker, SequenceMonitor
from btc_ml.feeds.raw_event_journal.normalize import normalize_agg_trade, normalize_book_ticker
from btc_ml.feeds.raw_event_journal.reader import RawEventJournalReader
from btc_ml.feeds.raw_event_journal.schemas import StreamType
from btc_ml.feeds.raw_event_journal.session import SessionManager
from btc_ml.feeds.raw_event_journal.writer import AtomicJournalWriter, BatchPolicy


def _agg(a: int, mono: int, ts: str, sess: str, gen: int, seq: int):
    return normalize_agg_trade(
        {
            "e": "aggTrade",
            "E": 1672515782136,
            "a": a,
            "p": "100.5",
            "q": "0.01",
            "f": a,
            "l": a,
            "T": 1672515782136,
            "m": False,
        },
        symbol="BTCUSDT",
        local_receive_timestamp=ts,
        local_receive_monotonic_ns=mono,
        connection_session_id=sess,
        reconnect_generation=gen,
        source_sequence=seq,
    )


def _book(u: int, mono: int, ts: str, sess: str, gen: int, seq: int):
    return normalize_book_ticker(
        {
            "e": "bookTicker",
            "u": u,
            "b": "100.0",
            "B": "1",
            "a": "100.1",
            "A": "1",
        },
        symbol="BTCUSDT",
        local_receive_timestamp=ts,
        local_receive_monotonic_ns=mono,
        connection_session_id=sess,
        reconnect_generation=gen,
        source_sequence=seq,
    )


def test_interleaved_streams_separate_partitions(tmp_path: Path):
    w = AtomicJournalWriter(tmp_path, policy=BatchPolicy(max_events_per_batch=10, max_seconds_per_batch=60))
    for i in range(5):
        w.append(StreamType.AGG_TRADE, _agg(i + 1, i * 2, "2026-07-25T10:00:00Z", "s1", 1, i * 2 + 1))
        w.append(StreamType.BOOK_TICKER, _book(1000 + i, i * 2 + 1, "2026-07-25T10:00:00Z", "s1", 1, i * 2 + 2))
    w.flush_all()
    assert (tmp_path / "agg_trade").exists()
    assert (tmp_path / "book_ticker").exists()
    r = RawEventJournalReader(tmp_path)
    assert len(r.read_stream(StreamType.AGG_TRADE).events) == 5
    assert len(r.read_stream(StreamType.BOOK_TICKER).events) == 5


def test_duplicates_out_of_order_receive(tmp_path: Path):
    w = AtomicJournalWriter(tmp_path, policy=BatchPolicy(max_events_per_batch=100, max_seconds_per_batch=60))
    d = DuplicateTracker()
    # receive order: 3,1,2,1(dup)
    for a, mono in ((3, 1), (1, 2), (2, 3), (1, 4)):
        ev = _agg(a, mono, "2026-07-25T10:00:00Z", "s1", 1, mono)
        if d.is_duplicate_agg("BTCUSDT", a):
            continue
        w.append(StreamType.AGG_TRADE, ev)
    w.flush_all()
    result = RawEventJournalReader(tmp_path).read_stream(StreamType.AGG_TRADE)
    ids = [e["aggregate_trade_id"] for e in result.events]
    assert ids == [1, 2, 3]
    assert d.dropped == 1


def test_reconnect_boundary_new_session(tmp_path: Path):
    sm = SessionManager()
    s1 = sm.begin_session()
    sm.end_session("net")
    s2 = sm.begin_session()
    w = AtomicJournalWriter(tmp_path, policy=BatchPolicy(max_events_per_batch=10, max_seconds_per_batch=60))
    w.append(StreamType.AGG_TRADE, _agg(1, 1, "2026-07-25T10:00:00Z", s1.connection_session_id, 1, 1))
    w.append(StreamType.AGG_TRADE, _agg(2, 2, "2026-07-25T10:00:01Z", s2.connection_session_id, 2, 2))
    w.flush_all()
    events = RawEventJournalReader(tmp_path).read_stream(StreamType.AGG_TRADE).events
    assert events[0]["connection_session_id"] != events[1]["connection_session_id"]
    assert events[1]["reconnect_generation"] == 2


def test_partial_batch_crash_temp_not_committed(tmp_path: Path):
    part = tmp_path / "agg_trade" / "date=2026-07-25" / "hour=10"
    part.mkdir(parents=True)
    tmp = part / "crash_batch.jsonl.tmp"
    tmp.write_text('{"broken":true}\n', encoding="utf-8")
    w = AtomicJournalWriter(tmp_path)
    recovered = w.recover_temp_files()
    assert any(str(tmp) == r or Path(r).name.endswith(".tmp") for r in recovered)
    assert not tmp.exists()
    # restart does not promote temp
    assert RawEventJournalReader(tmp_path).read_stream(StreamType.AGG_TRADE).events == []


def test_corrupted_committed_batch_reported(tmp_path: Path):
    part = tmp_path / "agg_trade" / "date=2026-07-25" / "hour=10"
    part.mkdir(parents=True)
    bad = part / "agg_trade__start=x__end=y__session=s__batch=00000001.jsonl"
    bad.write_text("{not-json\n", encoding="utf-8")
    result = RawEventJournalReader(tmp_path).read_stream(StreamType.AGG_TRADE)
    assert result.issues
    assert result.issues[0].kind == "BATCH_READ_ERROR"


def test_hour_and_date_rollover(tmp_path: Path):
    w = AtomicJournalWriter(tmp_path, policy=BatchPolicy(max_events_per_batch=1, max_seconds_per_batch=60))
    w.append(StreamType.BOOK_TICKER, _book(1, 1, "2026-07-25T23:59:59Z", "s", 1, 1))
    w.append(StreamType.BOOK_TICKER, _book(2, 2, "2026-07-26T00:00:01Z", "s", 1, 2))
    w.flush_all()
    hours = {p.parent.name for p in (tmp_path / "book_ticker").rglob("*.jsonl")}
    dates = {p.parent.parent.name for p in (tmp_path / "book_ticker").rglob("*.jsonl")}
    assert "hour=23" in hours and "hour=00" in hours
    assert "date=2026-07-25" in dates and "date=2026-07-26" in dates


def test_sequence_monitor_across_reconnect_gap(tmp_path: Path):
    mon = SequenceMonitor()
    assert mon.check_agg_trade({"aggregate_trade_id": 10, "first_trade_id": 10, "last_trade_id": 10}) is None
    gap = mon.check_agg_trade({"aggregate_trade_id": 50, "first_trade_id": 50, "last_trade_id": 50})
    assert gap is not None and gap.gap_type == "AGGREGATE_TRADE_ID_GAP"
    w = AtomicJournalWriter(tmp_path, policy=BatchPolicy(max_events_per_batch=10, max_seconds_per_batch=60))
    w.append(StreamType.AGG_TRADE, _agg(10, 1, "2026-07-25T10:00:00Z", "s1", 1, 1))
    w.append(StreamType.AGG_TRADE, _agg(50, 2, "2026-07-25T10:00:05Z", "s2", 2, 2))
    w.flush_all()
    result = RawEventJournalReader(tmp_path).read_stream(StreamType.AGG_TRADE)
    assert any(g["gap_type"] == "AGGREGATE_TRADE_ID_GAP" for g in result.gaps)
