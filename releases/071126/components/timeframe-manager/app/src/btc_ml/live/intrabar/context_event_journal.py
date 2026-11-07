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


def make_context_event_id_v2(
    *,
    provider_id: str,
    epoch_id: str,
    timeframe: str,
    lifecycle_episode_id: str,
    event_type: str,
    source_bar_timestamp: str,
    direction: str,
) -> str:
    raw = "|".join(
        [
            str(provider_id),
            str(epoch_id),
            str(timeframe),
            str(lifecycle_episode_id),
            str(event_type),
            str(source_bar_timestamp),
            str(direction),
        ]
    )
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
        explicit = obj.get("event_identity_key") or obj.get("dedupe_key")
        if explicit:
            return str(explicit)
        if (
            obj.get("provider_id") is not None
            and obj.get("epoch_id") is not None
            and obj.get("source_bar_timestamp") is not None
            and obj.get("direction") is not None
        ):
            return "|".join(
                [
                    str(obj.get("provider_id")),
                    str(obj.get("epoch_id")),
                    str(obj.get("timeframe")),
                    str(obj.get("lifecycle_episode_id")),
                    str(obj.get("event_type")),
                    str(obj.get("source_bar_timestamp")),
                    str(obj.get("direction")),
                ]
            )
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
        provider_id: str | None = None,
        epoch_id: str | None = None,
        source_bar_timestamp: Any = None,
        decision_available_at: Any = None,
        context_origin_timestamp: Any = None,
        execution_not_before: Any = None,
        direction: str | None = None,
        evaluation_mode: str = "PROVISIONAL_INTRABAR",
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        identity_key = None
        if provider_id and epoch_id and source_bar_timestamp is not None and direction:
            identity_key = "|".join(
                [
                    str(provider_id),
                    str(epoch_id),
                    str(timeframe),
                    str(lifecycle_episode_id),
                    str(event_type),
                    str(source_bar_timestamp),
                    str(direction),
                ]
            )
            eid = make_context_event_id_v2(
                provider_id=str(provider_id),
                epoch_id=str(epoch_id),
                timeframe=timeframe,
                lifecycle_episode_id=lifecycle_episode_id,
                event_type=event_type,
                source_bar_timestamp=str(source_bar_timestamp),
                direction=str(direction),
            )
        else:
            eid = make_context_event_id(
                timeframe, lifecycle_episode_id, event_type, int(event_monotonic_ns)
            )
        event = {
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
            "evaluation_mode": evaluation_mode,
        }
        if identity_key is not None:
            event["event_identity_key"] = identity_key
        optional = {
            "provider_id": provider_id,
            "epoch_id": epoch_id,
            "source_bar_timestamp": source_bar_timestamp,
            "decision_available_at": decision_available_at,
            "context_origin_timestamp": context_origin_timestamp,
            "execution_not_before": execution_not_before,
            "direction": direction,
        }
        for key, value in optional.items():
            if value is not None:
                event[key] = value
        if extra_metadata:
            event.update(dict(extra_metadata))
        return event
