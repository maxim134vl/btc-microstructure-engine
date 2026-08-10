"""Opt-in segmented Parquet/Zstd storage for the execution-market WAL.

This module is deliberately not activated by the live processor.  A cutover must
explicitly construct :class:`SegmentedWalStorage` after the production plan is
approved.  Its destructive cleanup switch also defaults to false.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

_CLOSED = re.compile(r"closed-(\d+)-(\d+)\.jsonl$")
_ARCHIVE = re.compile(r"segment-(\d+)-(\d+)\.parquet$")


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Stream complete valid records; a torn final append is ignored."""
    if not path.exists():
        return
    with path.open("rb") as handle:
        for raw in handle:
            try:
                row = json.loads(raw)
                int(row.get("wal_offset") or 0)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
                continue
            yield row


def _iter_lines_reverse(path: Path, *, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        remainder = b""
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            block = handle.read(read_size) + remainder
            parts = block.split(b"\n")
            remainder = parts[0]
            for raw in reversed(parts[1:]):
                if raw.strip():
                    yield raw
        if remainder.strip():
            yield remainder


def iter_jsonl_after(
    path: Path,
    after_offset: int,
    *,
    first_offset: int,
    last_offset: int,
    reverse_tail_limit: int = 250_000,
) -> Iterator[dict[str, Any]]:
    """Stream rows after an offset, using a bounded near-tail fast path."""
    remaining = max(0, int(last_offset) - int(after_offset))
    use_reverse = (
        int(after_offset) >= int(first_offset)
        and remaining <= max(1, int(reverse_tail_limit))
    )
    if not use_reverse:
        for row in iter_jsonl(path):
            if int(row.get("wal_offset") or 0) > int(after_offset):
                yield row
        return

    pending: list[dict[str, Any]] = []
    for raw in _iter_lines_reverse(path):
        try:
            row = json.loads(raw)
            wal_offset = int(row.get("wal_offset") or 0)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            continue
        if wal_offset <= int(after_offset):
            break
        pending.append(row)
    yield from reversed(pending)


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class SegmentedWalStorage:
    """Rotate an fsynced active tail and archive every event without sampling."""

    def __init__(
        self,
        root: Path,
        *,
        max_segment_bytes: int = 64 * 1024 * 1024,
        archive_batch_rows: int = 65_536,
        delete_verified_plaintext: bool = False,
        plaintext_retention_hours: float = 0.0,
    ) -> None:
        self.root = Path(root)
        self.active_path = self.root / "events.jsonl"
        self.archive_root = self.root / "archive"
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.max_segment_bytes = max(1, int(max_segment_bytes))
        self.archive_batch_rows = max(1, int(archive_batch_rows))
        self.delete_verified_plaintext = bool(delete_verified_plaintext)
        self.plaintext_retention_seconds = max(0.0, float(plaintext_retention_hours) * 3600.0)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.last_compaction_error: str | None = None
        self.last_retention_error: str | None = None

    def closed_segments(self) -> list[tuple[int, int, Path]]:
        found = []
        for path in self.root.glob("closed-*-*.jsonl"):
            match = _CLOSED.match(path.name)
            if match:
                found.append((int(match.group(1)), int(match.group(2)), path))
        return sorted(found)

    def archives(self) -> list[tuple[int, int, Path]]:
        found = []
        for path in self.archive_root.glob("segment-*-*.parquet"):
            match = _ARCHIVE.match(path.name)
            if match and Path(str(path) + ".meta.json").exists():
                found.append((int(match.group(1)), int(match.group(2)), path))
        return sorted(found)

    def rotate(self, *, first_offset: int, last_offset: int) -> Path | None:
        """Atomically detach the active segment, preserving append durability."""
        if not self.active_path.exists() or not self.active_path.stat().st_size:
            return None
        closed = self.root / f"closed-{first_offset:020d}-{last_offset:020d}.jsonl"
        if closed.exists():
            raise FileExistsError(f"execution WAL closed segment already exists: {closed}")
        os.replace(self.active_path, closed)
        self.active_path.touch()
        _fsync_dir(self.root)
        return closed

    def rotate_if_due(self, *, first_offset: int, last_offset: int) -> Path | None:
        if self.active_path.stat().st_size < self.max_segment_bytes:
            return None
        return self.rotate(first_offset=first_offset, last_offset=last_offset)

    def compact_async(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._compact_worker, name="execution-wal-archiver", daemon=True)
        self._thread.start()

    def _compact_worker(self) -> None:
        try:
            self.compact_pending()
            self.last_compaction_error = None
        except Exception as exc:  # noqa: BLE001 - surfaced through runtime health
            self.last_compaction_error = f"{type(exc).__name__}: {exc}"

    def _delete_plaintext_if_retained(
        self, source: Path, archive: Path, start: int, end: int
    ) -> bool:
        if not self.delete_verified_plaintext or not source.exists():
            return False
        age_seconds = max(0.0, time.time() - source.stat().st_mtime)
        if age_seconds < self.plaintext_retention_seconds:
            return False
        if not self.validate_archive(archive, start, end):
            return False
        source.unlink()
        _fsync_dir(self.root)
        return True

    def apply_plaintext_retention(self) -> list[Path]:
        # Delete only aged plaintext backed by a verified exact archive.
        removed: list[Path] = []
        try:
            archives = {(start, end): path for start, end, path in self.archives()}
            for start, end, source in self.closed_segments():
                archive = archives.get((start, end))
                if archive is not None and self._delete_plaintext_if_retained(
                    source, archive, start, end
                ):
                    removed.append(source)
            self.last_retention_error = None
        except OSError as exc:
            self.last_retention_error = f"{type(exc).__name__}: {exc}"
        return removed

    def wait(self, timeout: float = 30.0) -> None:
        if self._thread:
            self._thread.join(timeout)

    @staticmethod
    def _canonical(row: dict[str, Any]) -> str:
        return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)

    def compact_pending(self) -> list[Path]:
        """Publish verified archives with memory bounded by archive_batch_rows."""
        committed = []
        with self._lock:
            for start, end, source in self.closed_segments():
                final = self.archive_root / f"segment-{start:020d}-{end:020d}.parquet"
                meta_path = Path(str(final) + ".meta.json")
                if final.exists() and meta_path.exists():
                    self._delete_plaintext_if_retained(source, final, start, end)
                    continue
                tmp = final.with_suffix(".parquet.tmp")
                tmp.unlink(missing_ok=True)
                schema = pa.schema([("wal_offset", pa.int64()), ("payload_json", pa.string())])
                digest = hashlib.sha256()
                row_count = 0
                first_seen: int | None = None
                last_seen: int | None = None
                offsets: list[int] = []
                payloads: list[str] = []
                with pq.ParquetWriter(tmp, schema, compression="zstd", compression_level=6) as writer:
                    for row in iter_jsonl(source):
                        wal_offset = int(row["wal_offset"])
                        payload = self._canonical(row)
                        digest.update(payload.encode() + b"\n")
                        first_seen = wal_offset if first_seen is None else first_seen
                        last_seen = wal_offset
                        row_count += 1
                        offsets.append(wal_offset)
                        payloads.append(payload)
                        if len(offsets) >= self.archive_batch_rows:
                            writer.write_table(pa.Table.from_arrays([offsets, payloads], schema=schema))
                            offsets, payloads = [], []
                    if offsets:
                        writer.write_table(pa.Table.from_arrays([offsets, payloads], schema=schema))
                if not row_count or first_seen != start or last_seen != end:
                    tmp.unlink(missing_ok=True)
                    continue
                with tmp.open("rb") as handle:
                    os.fsync(handle.fileno())
                check_digest = hashlib.sha256()
                check_count = 0
                check_first: int | None = None
                check_last: int | None = None
                for batch in pq.ParquetFile(tmp).iter_batches(
                    columns=["wal_offset", "payload_json"], batch_size=self.archive_batch_rows
                ):
                    batch_offsets = batch.column(0).to_pylist()
                    batch_payloads = batch.column(1).to_pylist()
                    if batch_offsets:
                        check_first = int(batch_offsets[0]) if check_first is None else check_first
                        check_last = int(batch_offsets[-1])
                    check_count += len(batch_offsets)
                    for payload in batch_payloads:
                        check_digest.update(payload.encode() + b"\n")
                if check_count != row_count or check_first != start or check_last != end or check_digest.hexdigest() != digest.hexdigest():
                    tmp.unlink(missing_ok=True)
                    raise ValueError("execution WAL archive verification failed")
                os.replace(tmp, final)
                meta = {
                    "schema_version": "execution_market_wal_archive_v1",
                    "row_count": row_count,
                    "first_wal_offset": start,
                    "last_wal_offset": end,
                    "logical_sha256": digest.hexdigest(),
                    "parquet_sha256": _sha256_file(final),
                }
                meta_tmp = Path(str(meta_path) + ".tmp")
                with meta_tmp.open("w", encoding="utf-8") as handle:
                    handle.write(json.dumps(meta, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(meta_tmp, meta_path)
                _fsync_dir(self.archive_root)
                self._delete_plaintext_if_retained(source, final, start, end)
                committed.append(final)
            self.apply_plaintext_retention()
        return committed

    @staticmethod
    def validate_archive(path: Path, start: int, end: int) -> bool:
        meta_path = Path(str(path) + ".meta.json")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return (
                int(meta["first_wal_offset"]) == int(start)
                and int(meta["last_wal_offset"]) == int(end)
                and str(meta["parquet_sha256"]) == _sha256_file(path)
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def iter_archive(path: Path, after_offset: int) -> Iterator[dict[str, Any]]:
        parquet = pq.ParquetFile(path)
        for row_group in range(parquet.num_row_groups):
            stats = parquet.metadata.row_group(row_group).column(0).statistics
            if stats is not None and stats.has_min_max and int(stats.max) <= int(after_offset):
                continue
            batches = parquet.iter_batches(
                row_groups=[row_group], columns=["wal_offset", "payload_json"], batch_size=8192
            )
            for batch in batches:
                for offset, payload in zip(batch.column(0).to_pylist(), batch.column(1).to_pylist()):
                    if int(offset) > after_offset:
                        yield json.loads(payload)

    def iter_from_offset(
        self,
        offset: int,
        *,
        active_start_offset: int,
        active_last_offset: int,
    ) -> Iterator[dict[str, Any]]:
        """Read archive + unarchived closed segments + active tail in offset order."""
        archived = self.archives()
        archived_ranges = {(start, end) for start, end, _ in archived}
        sources: list[tuple[int, int, str, Path]] = [
            (start, end, "parquet", path) for start, end, path in archived if end > offset
        ]
        sources += [
            (start, end, "jsonl", path)
            for start, end, path in self.closed_segments()
            if end > offset and (start, end) not in archived_ranges
        ]
        if self.active_path.exists() and int(active_last_offset) >= int(active_start_offset):
            sources.append((active_start_offset, active_last_offset, "jsonl", self.active_path))
        for start, end, kind, path in sorted(sources):
            iterator = (
                self.iter_archive(path, offset)
                if kind == "parquet"
                else iter_jsonl_after(path, offset, first_offset=start, last_offset=end)
            )
            for row in iterator:
                if int(row.get("wal_offset") or 0) > offset:
                    yield row
