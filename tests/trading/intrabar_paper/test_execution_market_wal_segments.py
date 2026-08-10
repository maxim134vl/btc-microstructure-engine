from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pyarrow.parquet as pq

from btc_ml.trading.intrabar_paper.execution_market_wal import ExecutionMarketWAL


def _event(i: int, kind: str = "BOOK_TICKER") -> dict:
    base = {
        "event_type": kind,
        "symbol": "BTCUSDT",
        "connection_session_id": "session-a",
        "receive_monotonic_ns": i,
        "receive_timestamp": "2026-08-10T00:00:00Z",
    }
    if kind == "BOOK_TICKER":
        base.update(update_id=i, best_bid="118000.10000000", best_ask="118000.20000000")
    else:
        base.update(aggregate_trade_id=i, price="118000.15000000", quantity="0.00100000")
    return base


def _logical(rows: list[dict]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    return digest.hexdigest()


def test_rotation_compaction_and_transparent_replay(tmp_path: Path) -> None:
    wal = ExecutionMarketWAL(
        tmp_path, paper_epoch_id="epoch", enable_segmented_storage=True,
        segment_max_bytes=1800, delete_verified_plaintext=True,
    )
    for i in range(1, 101):
        assert wal.append(_event(i, "AGG_TRADE" if i % 17 == 0 else "BOOK_TICKER")).ok
    wal.segmented.wait()
    wal.segmented.compact_pending()
    rows = list(wal.iter_from_offset(0))
    assert [r["wal_offset"] for r in rows] == list(range(1, 101))
    assert _logical(rows) == _logical(sorted(rows, key=lambda r: r["wal_offset"]))
    assert list((tmp_path / "archive").glob("*.parquet"))
    assert not list(tmp_path.glob("closed-*.jsonl"))


def test_archive_crash_artifacts_keep_plaintext_replayable(tmp_path: Path) -> None:
    wal = ExecutionMarketWAL(
        tmp_path, paper_epoch_id="epoch", enable_segmented_storage=True,
        segment_max_bytes=10**9, delete_verified_plaintext=True,
    )
    for i in range(1, 8):
        wal.append(_event(i))
    closed = wal.segmented.rotate(first_offset=1, last_offset=7)
    assert closed is not None
    (tmp_path / "archive" / "segment-00000000000000000001-00000000000000000007.parquet.tmp").write_bytes(b"crash")
    assert [r["wal_offset"] for r in wal.segmented.iter_from_offset(0, active_start_offset=8, active_last_offset=7)] == list(range(1, 8))
    wal.segmented.compact_pending()
    assert [r["wal_offset"] for r in wal.segmented.iter_from_offset(0, active_start_offset=8, active_last_offset=7)] == list(range(1, 8))


def test_torn_active_tail_and_near_checkpoint(tmp_path: Path) -> None:
    wal = ExecutionMarketWAL(tmp_path, paper_epoch_id="epoch", enable_segmented_storage=True, segment_max_bytes=2200)
    for i in range(1, 80):
        wal.append(_event(i))
    wal.segmented.wait()
    with wal.events_path.open("ab") as handle:
        handle.write(b'{"wal_offset":80')
    assert [r["wal_offset"] for r in wal.iter_from_offset(75)] == [76, 77, 78, 79]
    restarted = ExecutionMarketWAL(tmp_path, paper_epoch_id="epoch", enable_segmented_storage=True, segment_max_bytes=2200)
    assert restarted.last_offset == 79


def test_legacy_single_file_is_backward_compatible_and_migratable(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("".join(json.dumps({**_event(i), "wal_offset": i}) + "\n" for i in range(1, 21)), encoding="utf-8")
    legacy = ExecutionMarketWAL(tmp_path, paper_epoch_id="epoch")
    assert [r["wal_offset"] for r in legacy.iter_from_offset(17)] == [18, 19, 20]
    migrated = ExecutionMarketWAL(tmp_path, paper_epoch_id="epoch", enable_segmented_storage=True, segment_max_bytes=1, delete_verified_plaintext=True)
    migrated.append(_event(21))
    migrated.segmented.wait()
    assert [r["wal_offset"] for r in migrated.iter_from_offset(0)] == list(range(1, 22))


def test_zstd_archive_preserves_event_order_and_compresses(tmp_path: Path) -> None:
    wal = ExecutionMarketWAL(tmp_path, paper_epoch_id="epoch", enable_segmented_storage=True, segment_max_bytes=10**9, delete_verified_plaintext=False)
    for i in range(1, 5001):
        wal.append(_event(i, "AGG_TRADE" if i % 30 == 0 else "BOOK_TICKER"))
    raw_bytes = wal.events_path.stat().st_size
    wal.segmented.rotate(first_offset=1, last_offset=5000)
    archive = wal.segmented.compact_pending()[0]
    assert archive.stat().st_size < raw_bytes * 0.30
    table = pq.read_table(archive, columns=["wal_offset"])
    assert table.column(0).to_pylist() == list(range(1, 5001))
    replay = list(wal.segmented.iter_from_offset(4990, active_start_offset=5001, active_last_offset=5000))
    assert [r["wal_offset"] for r in replay] == list(range(4991, 5001))
    assert [r["event_type"] for r in replay] == ["AGG_TRADE" if i % 30 == 0 else "BOOK_TICKER" for i in range(4991, 5001)]


def test_legacy_write_rollback_remains_archive_aware(tmp_path: Path) -> None:
    segmented = ExecutionMarketWAL(
        tmp_path,
        paper_epoch_id="epoch",
        enable_segmented_storage=True,
        segment_max_bytes=1800,
        delete_verified_plaintext=True,
    )
    for i in range(1, 31):
        assert segmented.append(_event(i)).ok
    segmented.segmented.wait()
    segmented.segmented.compact_pending()

    rollback = ExecutionMarketWAL(tmp_path, paper_epoch_id="epoch")
    assert rollback.segmented is None
    assert rollback.append(_event(31)).wal_offset == 31
    assert [row["wal_offset"] for row in rollback.iter_from_offset(0)] == list(range(1, 32))


def test_compaction_writes_bounded_batches(tmp_path: Path, monkeypatch) -> None:
    wal = ExecutionMarketWAL(
        tmp_path,
        paper_epoch_id="epoch",
        enable_segmented_storage=True,
        segment_max_bytes=10**9,
        archive_batch_rows=7,
    )
    for i in range(1, 54):
        assert wal.append(_event(i)).ok
    wal.segmented.rotate(first_offset=1, last_offset=53)

    batch_sizes: list[int] = []
    original = pq.ParquetWriter.write_table

    def checked_write(writer, table, *args, **kwargs):
        batch_sizes.append(table.num_rows)
        return original(writer, table, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetWriter, "write_table", checked_write)
    wal.segmented.compact_pending()
    assert batch_sizes
    assert max(batch_sizes) <= 7


def test_cutover_replays_near_checkpoint_and_ignores_stale_active_start(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        "".join(json.dumps({**_event(i), "wal_offset": i}) + "\n" for i in range(1, 1001)),
        encoding="utf-8",
    )
    (tmp_path / "state.json").write_text(json.dumps({"active_segment_start_offset": 1}))

    cutover = ExecutionMarketWAL(
        tmp_path,
        paper_epoch_id="epoch",
        enable_segmented_storage=True,
        segment_max_bytes=1,
    )
    assert [row["wal_offset"] for row in cutover.iter_from_offset(997)] == [998, 999, 1000]
    assert cutover._active_start_offset == 1001

    # Simulate a crash after rename and before state persistence.
    (tmp_path / "state.json").write_text(json.dumps({"active_segment_start_offset": 1}))
    restarted = ExecutionMarketWAL(
        tmp_path,
        paper_epoch_id="epoch",
        enable_segmented_storage=True,
        segment_max_bytes=10**9,
    )
    assert restarted._active_start_offset == 1001
    assert restarted.append(_event(1001)).wal_offset == 1001


def test_rotation_never_overwrites_an_existing_closed_range(tmp_path: Path) -> None:
    wal = ExecutionMarketWAL(
        tmp_path,
        paper_epoch_id="epoch",
        enable_segmented_storage=True,
        segment_max_bytes=10**9,
    )
    assert wal.append(_event(1)).ok
    collision = tmp_path / "closed-00000000000000000001-00000000000000000001.jsonl"
    collision.write_text("preserve me\n", encoding="utf-8")
    with __import__("pytest").raises(FileExistsError):
        wal.segmented.rotate(first_offset=1, last_offset=1)
    assert collision.read_text(encoding="utf-8") == "preserve me\n"


def test_plaintext_retention_waits_for_window_and_preserves_replay(tmp_path: Path) -> None:
    wal = ExecutionMarketWAL(
        tmp_path,
        paper_epoch_id="epoch",
        enable_segmented_storage=True,
        segment_max_bytes=10**9,
        delete_verified_plaintext=True,
        plaintext_retention_hours=1.0,
    )
    for i in range(1, 21):
        assert wal.append(_event(i)).ok
    source = wal.segmented.rotate(first_offset=1, last_offset=20)
    archive = wal.segmented.compact_pending()[0]
    assert source is not None and source.exists()
    assert archive.exists()

    old = time.time() - 2 * 3600
    os.utime(source, (old, old))
    assert wal.segmented.apply_plaintext_retention() == [source]
    assert not source.exists()
    assert [row["wal_offset"] for row in wal.iter_from_offset(0)] == list(range(1, 21))


def test_retention_never_deletes_without_verified_archive(tmp_path: Path) -> None:
    wal = ExecutionMarketWAL(
        tmp_path,
        paper_epoch_id="epoch",
        enable_segmented_storage=True,
        segment_max_bytes=10**9,
        delete_verified_plaintext=True,
    )
    for i in range(1, 4):
        assert wal.append(_event(i)).ok
    source = wal.segmented.rotate(first_offset=1, last_offset=3)
    assert source is not None
    assert wal.segmented.apply_plaintext_retention() == []
    assert source.exists()


def test_wal_size_telemetry_tolerates_atomic_tmp_rename_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wal = ExecutionMarketWAL(
        tmp_path,
        paper_epoch_id="epoch",
        enable_segmented_storage=True,
    )
    wal.append(_event(1))
    original_stat = Path.stat

    def race_once(path: Path, *args, **kwargs):
        if path.name == "state.json":
            raise FileNotFoundError(path)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", race_once)
    assert wal.wal_size_bytes >= 0


def test_wal_size_health_thresholds_do_not_block_append(tmp_path: Path) -> None:
    wal = ExecutionMarketWAL(
        tmp_path,
        paper_epoch_id="epoch",
        enable_segmented_storage=True,
        segment_max_bytes=10**9,
        warning_size_bytes=1,
        critical_size_bytes=100,
    )
    assert wal.append(_event(1)).ok
    assert wal.wal_size_bytes > 100
    assert wal.wal_retention_status == "CRITICAL"
    assert wal.wal_segments_count == 1
    assert wal.wal_oldest_event_timestamp == "2026-08-10T00:00:00Z"
    assert wal.append(_event(2)).ok
