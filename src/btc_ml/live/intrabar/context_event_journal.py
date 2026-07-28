"""Append-only intrabar CONTEXT_* event journal."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def make_context_event_id(
    timeframe: str,
    lifecycle_episode_id: str,
    event_type: str,
    event_monotonic_ns: int,
) -> str:
    raw = f"{timeframe}|{lifecycle_episode_id}|{event_type}|{event_monotonic_ns}"
    return "CTX_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


class ContextEventJournal:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "events.jsonl"
        self._seen: set[str] = set()
        self._load_seen()

    def _load_seen(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = self._dedupe_key(obj)
                if key:
                    self._seen.add(key)

    @staticmethod
    def _dedupe_key(obj: Mapping[str, Any]) -> Optional[str]:
        try:
            return "|".join(
                [
                    str(obj.get("timeframe")),
                    str(obj.get("lifecycle_episode_id")),
                    str(obj.get("event_type")),
                    str(obj.get("event_monotonic_ns")),
                ]
            )
        except Exception:
            return None

    def append(self, event: Mapping[str, Any]) -> bool:
        """Append if not duplicate. Returns True when written."""
        key = self._dedupe_key(event)
        if key is None or key in self._seen:
            return False
        line = json.dumps(dict(event), ensure_ascii=True, separators=(",", ":")) + "\n"
        # atomic append via temp+cat is unnecessary for append-only; fsync after write
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        self._seen.add(key)
        return True

    def build_event(
        self,
        *,
        timeframe: str,
        event_type: str,
        previous_context: str,
        new_context: str,
        event_timestamp: str,
        event_monotonic_ns: int,
        context_event_price: str,
        last_trade_id: Any,
        last_trade_timestamp: Any,
        best_bid: Any,
        best_ask: Any,
        book_update_id: Any,
        bbo_receive_monotonic_ns: Any,
        bbo_age_ms: Any,
        connection_session_id: Any,
        reconnect_generation: Any,
        causal_cutoff_timestamp: Any,
        causal_cutoff_monotonic_ns: Any,
        model_version: str,
        lifecycle_episode_id: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        eid = make_context_event_id(
            timeframe, lifecycle_episode_id, event_type, int(event_monotonic_ns)
        )
        return {
            "context_event_id": eid,
            "timeframe": timeframe,
            "event_type": event_type,
            "previous_context": previous_context,
            "new_context": new_context,
            "event_timestamp": event_timestamp,
            "event_monotonic_ns": int(event_monotonic_ns),
            "context_event_price": context_event_price,
            "last_trade_id": last_trade_id,
            "last_trade_timestamp": last_trade_timestamp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "book_update_id": book_update_id,
            "bbo_receive_monotonic_ns": bbo_receive_monotonic_ns,
            "bbo_age_ms": bbo_age_ms,
            "connection_session_id": connection_session_id,
            "reconnect_generation": reconnect_generation,
            "causal_cutoff_timestamp": causal_cutoff_timestamp,
            "causal_cutoff_monotonic_ns": causal_cutoff_monotonic_ns,
            "model_version": model_version,
            "lifecycle_episode_id": lifecycle_episode_id,
            "evidence": dict(evidence or {}),
            "ingested_at": _utc_now(),
            "evaluation_mode": "PROVISIONAL_INTRABAR",
        }
