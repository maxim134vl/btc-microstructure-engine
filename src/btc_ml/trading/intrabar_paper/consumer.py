"""Durable context-event consumer with idempotent replay."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


ENTRY_EVENTS = frozenset({"CONTEXT_START", "CONTEXT_FLIP"})
EXIT_EVENTS = frozenset({"CONTEXT_END", "CONTEXT_FLIP"})


def idempotency_key(
    *,
    paper_epoch_id: str,
    context_event_id: str,
    timeframe: str,
    action: str,
) -> str:
    return f"{paper_epoch_id}|{context_event_id}|{timeframe}|{action}"


@dataclass
class ConsumerCheckpoint:
    paper_epoch_id: str
    last_consumed_context_event_id: str | None = None
    last_event_monotonic_ns: int = 0
    last_path: str | None = None
    last_offset: int = 0
    processed_keys: set[str] = field(default_factory=set)
    duplicate_events_prevented: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_epoch_id": self.paper_epoch_id,
            "last_consumed_context_event_id": self.last_consumed_context_event_id,
            "last_event_monotonic_ns": self.last_event_monotonic_ns,
            "last_path": self.last_path,
            "last_offset": self.last_offset,
            "processed_keys": sorted(self.processed_keys),
            "duplicate_events_prevented": self.duplicate_events_prevented,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ConsumerCheckpoint":
        return cls(
            paper_epoch_id=str(raw["paper_epoch_id"]),
            last_consumed_context_event_id=raw.get("last_consumed_context_event_id"),
            last_event_monotonic_ns=int(raw.get("last_event_monotonic_ns") or 0),
            last_path=raw.get("last_path"),
            last_offset=int(raw.get("last_offset") or 0),
            processed_keys=set(str(x) for x in (raw.get("processed_keys") or [])),
            duplicate_events_prevented=int(raw.get("duplicate_events_prevented") or 0),
        )


class ContextEventConsumer:
    """Reads intrabar context journal in causal monotonic order."""

    def __init__(
        self,
        *,
        journal_root: Path,
        checkpoint_path: Path,
        paper_epoch_id: str,
        activated_at_monotonic_ns: int | None = None,
        activated_at_iso: str | None = None,
    ) -> None:
        self.journal_root = Path(journal_root)
        self.checkpoint_path = Path(checkpoint_path)
        self.paper_epoch_id = paper_epoch_id
        self.activated_at_monotonic_ns = activated_at_monotonic_ns
        self.activated_at_iso = activated_at_iso
        self.checkpoint = self._load_or_create()

    def _load_or_create(self) -> ConsumerCheckpoint:
        if self.checkpoint_path.exists():
            return ConsumerCheckpoint.from_dict(
                json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            )
        return ConsumerCheckpoint(paper_epoch_id=self.paper_epoch_id)

    def save(self) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.checkpoint_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.checkpoint.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.checkpoint_path)

    def already_processed(self, key: str) -> bool:
        if key in self.checkpoint.processed_keys:
            self.checkpoint.duplicate_events_prevented += 1
            return True
        return False

    def mark_processed(
        self,
        *,
        key: str,
        context_event_id: str,
        event_monotonic_ns: int,
        path: str | None = None,
        offset: int | None = None,
    ) -> None:
        self.checkpoint.processed_keys.add(key)
        self.checkpoint.last_consumed_context_event_id = context_event_id
        self.checkpoint.last_event_monotonic_ns = int(event_monotonic_ns)
        if path is not None:
            self.checkpoint.last_path = path
        if offset is not None:
            self.checkpoint.last_offset = int(offset)

    def _iter_files(self) -> list[Path]:
        if not self.journal_root.exists():
            return []
        return sorted(self.journal_root.rglob("*.jsonl"))

    def iter_new_events(self) -> Iterator[dict[str, Any]]:
        """Yield events with event_monotonic_ns > checkpoint, sorted causally."""
        pending: list[dict[str, Any]] = []
        last_mono = int(self.checkpoint.last_event_monotonic_ns or 0)
        for path in self._iter_files():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mono = int(ev.get("event_monotonic_ns") or 0)
                if mono <= last_mono:
                    continue
                # Post-activation gate: ISO first (safe across processes).
                # Optional monotonic gate only when explicitly provided (same-clock tests).
                if self.activated_at_iso:
                    ts = str(ev.get("event_timestamp") or ev.get("timestamp") or "")
                    if ts and ts < str(self.activated_at_iso):
                        continue
                if self.activated_at_monotonic_ns is not None:
                    if mono < int(self.activated_at_monotonic_ns):
                        continue
                ev["_journal_path"] = str(path)
                ev["_journal_offset"] = i
                pending.append(ev)
        pending.sort(key=lambda e: (int(e.get("event_monotonic_ns") or 0), str(e.get("context_event_id") or "")))
        for ev in pending:
            yield ev
