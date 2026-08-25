"""Phase A/B: mtime JSONL cache + idle skip behaviour (no semantic regressions)."""

from __future__ import annotations

import json
from pathlib import Path

from btc_ml.runtime.io_cache import MtimeJsonlCache, journal_tree_fingerprint
from btc_ml.trading.intrabar_paper.consumer import ContextEventConsumer


def test_mtime_jsonl_cache_hit_and_invalidate(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a":1}\n{"a":2}\n', encoding="utf-8")
    cache = MtimeJsonlCache()

    first = cache.read_jsonl(path)
    assert [r["a"] for r in first] == [1, 2]
    assert cache.stats.cache_misses == 1
    assert cache.stats.bytes_read > 0

    second = cache.read_jsonl(path)
    assert second == first
    assert cache.stats.cache_hits == 1
    assert cache.stats.cache_misses == 1

    path.write_text('{"a":1}\n{"a":2}\n{"a":3}\n', encoding="utf-8")
    third = cache.read_jsonl(path)
    assert [r["a"] for r in third] == [1, 2, 3]
    assert cache.stats.cache_misses == 2

    cache.invalidate(path)
    path.write_text('{"a":9}\n', encoding="utf-8")
    # Even if mtime is coarse, invalidate forces reload.
    assert [r["a"] for r in cache.read_jsonl(path)] == [9]


def test_consumer_skips_idle_journal_rescan(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    journal.mkdir()
    events = journal / "events.jsonl"
    row = {
        "context_event_id": "evt_1",
        "event_type": "CONTEXT_START",
        "event_monotonic_ns": 100,
        "timeframe": "M15",
    }
    events.write_text(json.dumps(row) + "\n", encoding="utf-8")

    consumer = ContextEventConsumer(
        journal_root=journal,
        checkpoint_path=tmp_path / "ckpt.json",
        paper_epoch_id="EPOCH_TEST",
    )
    first = list(consumer.iter_new_events())
    assert len(first) == 1
    assert consumer.observe.cache_misses == 1

    consumer.mark_processed(
        key="k1",
        context_event_id="evt_1",
        event_monotonic_ns=100,
        path=str(events),
        offset=0,
    )

    # Cursor moved → one more scan that finds nothing (enables idle skip).
    second = list(consumer.iter_new_events())
    assert second == []
    assert consumer.observe.cache_misses == 2
    assert consumer._last_scan_empty is True

    # Idle: same journal fingerprint + same cursor + prior empty scan → no disk read.
    bytes_before = consumer.observe.bytes_read
    third = list(consumer.iter_new_events())
    assert third == []
    assert consumer.observe.cache_hits == 1
    assert consumer.observe.bytes_read == bytes_before

    # Peek before checkpoint must remain re-iterable.
    row2 = dict(row)
    row2["context_event_id"] = "evt_2"
    row2["event_monotonic_ns"] = 200
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row2) + "\n")
    peek_a = list(consumer.iter_new_events())
    peek_b = list(consumer.iter_new_events())
    assert len(peek_a) == 1 and len(peek_b) == 1
    assert peek_a[0]["context_event_id"] == "evt_2"


def test_journal_tree_fingerprint_changes_on_append(tmp_path: Path) -> None:
    root = tmp_path / "j"
    root.mkdir()
    path = root / "a.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    fp1 = journal_tree_fingerprint(root)
    path.write_text("{}\n{}\n", encoding="utf-8")
    fp2 = journal_tree_fingerprint(root)
    assert fp1 != fp2
