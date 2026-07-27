"""Read-only journal reader / per-stream iterator (replay readiness, not TRD2 merge)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from .dedupe_gap import SequenceMonitor
from .schemas import SCHEMA_VERSION, StreamType, validate_event
from .writer import stream_dir_name


@dataclass
class ReaderIssue:
    kind: str
    path: Optional[str]
    details: dict[str, Any]


@dataclass
class StreamReadResult:
    stream: str
    events: list[dict[str, Any]]
    gaps: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    issues: list[ReaderIssue] = field(default_factory=list)


def _sort_key_agg(event: dict[str, Any]) -> tuple:
    agg = event.get("aggregate_trade_id")
    trade_ts = event.get("exchange_trade_timestamp") or ""
    mono = event.get("local_receive_monotonic_ns") or 0
    # Primary: aggregate_trade_id; tie-break trade ts then mono
    return (agg is None, agg if agg is not None else 0, trade_ts, mono)


def _sort_key_book(event: dict[str, Any]) -> tuple:
    uid = event.get("update_id")
    mono = event.get("local_receive_monotonic_ns") or 0
    return (uid is None, uid if uid is not None else 0, mono)


class RawEventJournalReader:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def list_batch_files(self, stream: StreamType) -> list[Path]:
        base = self.root / stream_dir_name(stream)
        if not base.exists():
            return []
        files = sorted(p for p in base.rglob("*.jsonl") if p.is_file() and not p.name.endswith(".tmp"))
        return files

    def verify_batch_checksum(self, path: Path, expected: Optional[str] = None) -> tuple[str, bool]:
        hasher = hashlib.sha256()
        with path.open("rb") as fh:
            for line in fh:
                hasher.update(line)
        digest = hasher.hexdigest()
        if expected is None:
            return digest, True
        return digest, digest == expected

    def iter_batch(self, path: Path, stream: StreamType) -> Iterator[dict[str, Any]]:
        with path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                errors = validate_event(obj, stream)
                if errors:
                    raise ValueError(f"schema_invalid:{path}:{lineno}:{errors}")
                if obj.get("schema_version") != SCHEMA_VERSION:
                    raise ValueError(f"schema_version_mismatch:{path}:{lineno}")
                yield obj

    def read_stream(self, stream: StreamType) -> StreamReadResult:
        events: list[dict[str, Any]] = []
        issues: list[ReaderIssue] = []
        for path in self.list_batch_files(stream):
            try:
                digest, _ = self.verify_batch_checksum(path)
                batch_events = list(self.iter_batch(path, stream))
                # Independent checksum presence recorded
                for ev in batch_events:
                    ev = dict(ev)
                    ev["_reader_batch_path"] = str(path.relative_to(self.root))
                    ev["_reader_batch_checksum"] = digest
                    events.append(ev)
            except Exception as exc:  # noqa: BLE001 — surface as issue
                issues.append(
                    ReaderIssue(kind="BATCH_READ_ERROR", path=str(path), details={"error": str(exc)})
                )

        if stream is StreamType.AGG_TRADE:
            events.sort(key=_sort_key_agg)
        elif stream is StreamType.BOOK_TICKER:
            events.sort(key=_sort_key_book)
        else:
            events.sort(key=lambda e: e.get("local_receive_monotonic_ns") or 0)

        duplicates: list[dict[str, Any]] = []
        seen_agg: set[tuple[str, int]] = set()
        seen_book: set[tuple[str, int]] = set()
        ordered: list[dict[str, Any]] = []
        for ev in events:
            if stream is StreamType.AGG_TRADE:
                aid = ev.get("aggregate_trade_id")
                sym = ev.get("symbol") or ""
                if aid is not None:
                    key = (sym, int(aid))
                    if key in seen_agg:
                        duplicates.append({"symbol": sym, "aggregate_trade_id": aid})
                        continue
                    seen_agg.add(key)
            elif stream is StreamType.BOOK_TICKER:
                uid = ev.get("update_id")
                sym = ev.get("symbol") or ""
                if uid is not None:
                    key = (sym, int(uid))
                    if key in seen_book:
                        duplicates.append({"symbol": sym, "update_id": uid})
                        continue
                    seen_book.add(key)
            ordered.append(ev)

        monitor = SequenceMonitor()
        gaps: list[dict[str, Any]] = []
        for ev in ordered:
            if stream is StreamType.AGG_TRADE:
                report = monitor.check_agg_trade(ev)
            elif stream is StreamType.BOOK_TICKER:
                report = monitor.check_book_ticker(ev)
            else:
                report = None
            if report is not None and report.gap_type.endswith("GAP"):
                gaps.append(
                    {
                        "stream": report.stream,
                        "gap_type": report.gap_type,
                        "previous": report.previous,
                        "current": report.current,
                        "details": report.details,
                    }
                )

        return StreamReadResult(
            stream=stream.value,
            events=ordered,
            gaps=gaps,
            duplicates=duplicates,
            issues=issues,
        )

    def iter_stream(self, stream: StreamType) -> Iterable[dict[str, Any]]:
        return self.read_stream(stream).events
