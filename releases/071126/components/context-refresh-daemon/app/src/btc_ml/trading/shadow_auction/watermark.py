"""Watermark + idempotent source-event processing foundation (AES1)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .storage import ShadowAuctionStore, atomic_write_json


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass
class WatermarkState:
    last_processed_source_event_id: str | None = None
    last_processed_timestamp: str | None = None
    last_m15_timestamp: str | None = None
    processed_event_ids: set[str] = field(default_factory=set)
    duplicates_dropped: int = 0
    ordering_violations: int = 0
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "shadow_auction_watermark_v1",
            "last_processed_source_event_id": self.last_processed_source_event_id,
            "last_processed_timestamp": self.last_processed_timestamp,
            "last_m15_timestamp": self.last_m15_timestamp,
            "processed_event_ids": sorted(self.processed_event_ids),
            "duplicates_dropped": int(self.duplicates_dropped),
            "ordering_violations": int(self.ordering_violations),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "WatermarkState":
        raw = raw or {}
        return cls(
            last_processed_source_event_id=(
                str(raw["last_processed_source_event_id"])
                if raw.get("last_processed_source_event_id") is not None
                else None
            ),
            last_processed_timestamp=(
                str(raw["last_processed_timestamp"])
                if raw.get("last_processed_timestamp") is not None
                else None
            ),
            last_m15_timestamp=(
                str(raw["last_m15_timestamp"]) if raw.get("last_m15_timestamp") is not None else None
            ),
            processed_event_ids=set(str(x) for x in (raw.get("processed_event_ids") or [])),
            duplicates_dropped=int(raw.get("duplicates_dropped") or 0),
            ordering_violations=int(raw.get("ordering_violations") or 0),
            updated_at=str(raw["updated_at"]) if raw.get("updated_at") else None,
        )


class Watermark:
    """Chronological, restart-safe processing cursor with duplicate suppression."""

    RELATIVE_PATH = "memory/watermark.json"
    SEEN_CAP = 10_000

    def __init__(self, store: ShadowAuctionStore) -> None:
        self.store = store
        self.path = store.data_root / self.RELATIVE_PATH
        self.state = self._load()

    def _load(self) -> WatermarkState:
        if not self.path.exists():
            return WatermarkState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return WatermarkState()
        return WatermarkState.from_dict(raw if isinstance(raw, dict) else {})

    def save(self) -> Path:
        self.state.updated_at = _utc_now()
        # Bound the in-memory / on-disk seen set.
        if len(self.state.processed_event_ids) > self.SEEN_CAP:
            # Keep the most recently inserted by sorting ids is not ideal;
            # drop arbitrary excess while preserving last_processed cursor.
            excess = len(self.state.processed_event_ids) - self.SEEN_CAP
            for _ in range(excess):
                self.state.processed_event_ids.pop()
        return atomic_write_json(
            self.path,
            self.state.to_dict(),
            data_root=self.store.data_root,
            repo=self.store.repo,
        )

    def already_processed(self, source_event_id: str) -> bool:
        return str(source_event_id) in self.state.processed_event_ids

    def accept(
        self,
        *,
        source_event_id: str,
        source_timestamp: str | None,
    ) -> tuple[bool, str | None]:
        """Return (accepted, reason).

        Reasons:
          None — accepted
          DUPLICATE — already seen
          ORDERING_VIOLATION — timestamp before watermark (still recorded)
        """
        eid = str(source_event_id or "").strip()
        if not eid:
            return False, "MISSING_SOURCE_EVENT_ID"
        if self.already_processed(eid):
            self.state.duplicates_dropped += 1
            return False, "DUPLICATE"

        ts = _parse_ts(source_timestamp)
        last_ts = _parse_ts(self.state.last_processed_timestamp)
        if ts is not None and last_ts is not None and ts < last_ts:
            self.state.ordering_violations += 1
            # Still consume to keep restart continuity deterministic, but flag.
            reason = "ORDERING_VIOLATION"
        else:
            reason = None

        self.state.processed_event_ids.add(eid)
        self.state.last_processed_source_event_id = eid
        if source_timestamp:
            # Advance watermark timestamp only on non-regressive timestamps.
            if reason != "ORDERING_VIOLATION":
                self.state.last_processed_timestamp = str(source_timestamp)
        self.state.updated_at = _utc_now()
        return True, reason
