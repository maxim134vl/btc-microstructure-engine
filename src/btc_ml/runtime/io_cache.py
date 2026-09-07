"""Mtime/size-keyed read caches for append-mostly JSONL (observe + reuse).

Preserves parse results when (path, size, mtime_ns) is unchanged. Callers that
append must ``invalidate(path)`` so the next read reloads.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class IoObserveStats:
    bytes_read: int = 0
    files_read: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    checkpoint_writes: int = 0
    health_writes: int = 0
    idle_checkpoint_skips: int = 0
    poll_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "bytes_read": int(self.bytes_read),
            "files_read": int(self.files_read),
            "cache_hits": int(self.cache_hits),
            "cache_misses": int(self.cache_misses),
            "checkpoint_writes": int(self.checkpoint_writes),
            "health_writes": int(self.health_writes),
            "idle_checkpoint_skips": int(self.idle_checkpoint_skips),
            "poll_ms": float(self.poll_ms),
        }

    def reset_poll(self) -> None:
        """Reset per-poll counters; keep cumulative checkpoint/health totals."""
        self.bytes_read = 0
        self.files_read = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.poll_ms = 0.0


@dataclass
class _CacheEntry:
    size: int
    mtime_ns: int
    rows: list[dict[str, Any]]
    text: str | None = None


@dataclass
class MtimeJsonlCache:
    """Thread-safe JSONL reader keyed by file size + mtime."""

    stats: IoObserveStats = field(default_factory=IoObserveStats)
    _entries: dict[str, _CacheEntry] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def invalidate(self, path: Path | str) -> None:
        key = str(Path(path).resolve()) if Path(path).exists() else str(path)
        with self._lock:
            self._entries.pop(key, None)
            # Also drop unresolved / alternate forms.
            self._entries.pop(str(path), None)

    def note_appended(self, path: Path | str, rows: list[dict[str, Any]]) -> None:
        """Advance a cached entry over rows that were just appended to the file.

        Callers that append and then read the same journal used to invalidate here,
        which forced the next read to re-parse the file from the start. A writer
        knows exactly which rows it added, so the cache can be advanced instead of
        dropped. That is the difference between O(file) and O(appended) per read:
        an EQCORR batch replay appends to journals that grow past 100k rows while
        re-reading them ~20 times per closed trade, and was spending roughly 95% of
        its runtime inside json.loads as a result.

        `rows` must already be JSON round-tripped so the cached value is identical
        to what re-reading the file would produce. If nothing is cached for this
        path yet, this is a no-op and the next read populates the entry normally.
        """
        p = Path(path)
        key = str(p)
        try:
            resolved = str(p.resolve())
        except OSError:
            resolved = key
        try:
            st = p.stat()
        except OSError:
            self.invalidate(p)
            return

        with self._lock:
            entry = self._entries.get(resolved) or self._entries.get(key)
            if entry is None:
                return
            entry.rows.extend(row for row in rows if isinstance(row, dict))
            entry.size = int(st.st_size)
            entry.mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
            # Any retained text is now short by the appended lines.
            entry.text = None
            self._entries[resolved] = entry
            self._entries[key] = entry

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def read_jsonl(
        self,
        path: Path | str,
        *,
        keep_text: bool = False,
    ) -> list[dict[str, Any]]:
        p = Path(path)
        key = str(p)
        try:
            resolved = str(p.resolve())
        except OSError:
            resolved = key

        if not p.exists():
            with self._lock:
                self._entries.pop(key, None)
                self._entries.pop(resolved, None)
            return []

        try:
            st = p.stat()
        except OSError:
            return []

        size = int(st.st_size)
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))

        with self._lock:
            for lookup in (resolved, key):
                hit = self._entries.get(lookup)
                if hit is not None and hit.size == size and hit.mtime_ns == mtime_ns:
                    self.stats.cache_hits += 1
                    return hit.rows

        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return []

        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)

        entry = _CacheEntry(
            size=size,
            mtime_ns=mtime_ns,
            rows=rows,
            text=text if keep_text else None,
        )
        with self._lock:
            self.stats.cache_misses += 1
            self.stats.files_read += 1
            self.stats.bytes_read += size
            self._entries[resolved] = entry
            self._entries[key] = entry
        return rows

    def file_fingerprint(self, path: Path | str) -> tuple[str, int, int] | None:
        p = Path(path)
        if not p.exists():
            return None
        try:
            st = p.stat()
        except OSError:
            return None
        return (
            str(p),
            int(st.st_size),
            int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
        )


def journal_tree_fingerprint(root: Path) -> tuple[tuple[str, int, int], ...]:
    """Stable fingerprint of all ``*.jsonl`` under root (sorted by path)."""
    if not root.exists():
        return ()
    out: list[tuple[str, int, int]] = []
    for path in sorted(root.rglob("*.jsonl")):
        try:
            st = path.stat()
        except OSError:
            continue
        out.append(
            (
                str(path.resolve()),
                int(st.st_size),
                int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
            )
        )
    return tuple(out)
