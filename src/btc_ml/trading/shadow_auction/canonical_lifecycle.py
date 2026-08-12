"""Read-only canonical lifecycle adapters for AES4 checkpoints.

Confirmed sources (AES0/AES1 + AES4 OBSERVE):
- CONTEXT_START / CONTEXT_END / CONTEXT_FLIP:
  data/cognition/intrabar_context_events/events.jsonl
- PAPER_ENTRY: data/trading/intrabar_paper/<epoch>/books/positions.jsonl
  (opened_at; entry_context_event_id; fill ENTRY as secondary)
- PAPER_CLOSE: .../trades.jsonl (exit_ts) / positions closed_at

Never writes canonical or paper journals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nat", "nan", "none", "null"}:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def side_from_context(new_context: Any, *, direction: Any = None, intended_side: Any = None) -> str | None:
    for raw in (intended_side, direction, new_context):
        if raw is None:
            continue
        text = str(raw).upper()
        if "LONG" in text:
            return "LONG"
        if "SHORT" in text:
            return "SHORT"
    return None


@dataclass(frozen=True)
class CanonicalLifecycleEvent:
    """Normalized canonical/paper lifecycle event for checkpointing."""

    checkpoint_type: str  # CONTEXT_START | CONTEXT_END | PAPER_ENTRY | PAPER_CLOSE
    canonical_timestamp: str
    canonical_event_id: str
    canonical_context_episode_id: str | None = None
    trade_id: str | None = None
    position_id: str | None = None
    canonical_timeframe: str | None = None
    canonical_side: str | None = None
    entry_price: float | None = None
    close_price: float | None = None
    close_reason: str | None = None
    source_path: str = ""
    source_event_type: str | None = None
    linkage_method: str = "EXACT_ID"
    linkage_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    def primary_ids(self) -> tuple[str, str | None, str | None, str | None]:
        return (
            self.checkpoint_type,
            self.canonical_event_id,
            self.position_id or self.trade_id,
            self.canonical_context_episode_id,
        )


def active_paper_epoch_id(repo: Path) -> str | None:
    path = repo / "data" / "trading" / "paper_epochs" / "active.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw.get("paper_epoch_id") or raw.get("epoch_id")


def iter_context_events(
    repo: Path,
    *,
    since_timestamp: str | None = None,
    limit: int | None = None,
) -> Iterator[CanonicalLifecycleEvent]:
    path = repo / "data" / "cognition" / "intrabar_context_events" / "events.jsonl"
    if not path.exists():
        return
    since = _parse_ts(since_timestamp)
    n = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = str(raw.get("event_type") or "").upper()
            if et == "CONTEXT_START" or et == "CONTEXT_FLIP":
                ctype = "CONTEXT_START"
            elif et == "CONTEXT_END":
                ctype = "CONTEXT_END"
            else:
                continue
            ts = raw.get("event_timestamp") or raw.get("decision_available_at")
            pts = _parse_ts(ts)
            if pts is None:
                continue
            if since is not None and pts <= since:
                continue
            side = side_from_context(
                raw.get("new_context"),
                direction=raw.get("direction"),
                intended_side=raw.get("intended_side"),
            )
            price = raw.get("context_event_price")
            try:
                price_f = float(price) if price is not None else None
            except (TypeError, ValueError):
                price_f = None
            event_id = str(raw.get("context_event_id") or raw.get("event_identity_key") or "")
            if not event_id:
                continue
            yield CanonicalLifecycleEvent(
                checkpoint_type=ctype,
                canonical_timestamp=_iso(pts),
                canonical_event_id=event_id,
                canonical_context_episode_id=_opt_str(raw.get("lifecycle_episode_id")),
                trade_id=None,
                position_id=None,
                canonical_timeframe=_opt_str(raw.get("timeframe")),
                canonical_side=side,
                entry_price=None,
                close_price=None,
                close_reason=None,
                source_path=str(path),
                source_event_type=et,
                linkage_method="EXACT_ID",
                raw=raw,
            )
            n += 1
            if limit is not None and n >= int(limit):
                return


def iter_paper_entries(
    repo: Path,
    *,
    epoch_id: str | None = None,
    since_timestamp: str | None = None,
    limit: int | None = None,
) -> Iterator[CanonicalLifecycleEvent]:
    epoch = epoch_id or active_paper_epoch_id(repo)
    if not epoch:
        return
    path = repo / "data" / "trading" / "intrabar_paper" / epoch / "books" / "positions.jsonl"
    if not path.exists():
        return
    since = _parse_ts(since_timestamp)
    n = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            opened = raw.get("opened_at")
            pts = _parse_ts(opened)
            if pts is None:
                continue
            if since is not None and pts <= since:
                continue
            pos_id = _opt_str(raw.get("position_id"))
            if not pos_id:
                continue
            ctx_event = _opt_str(raw.get("entry_context_event_id"))
            # Deterministic event id for entry: prefer fill/context, else position open identity.
            event_id = ctx_event or _opt_str(raw.get("entry_fill_id")) or f"ENTRY|{pos_id}|{_iso(pts)}"
            linkage = "EXACT_ID" if ctx_event else "DERIVED"
            linkage_reason = None if ctx_event else "ENTRY_IDENTITY_FROM_POSITION_ID"
            try:
                entry_price = float(raw["entry_price"]) if raw.get("entry_price") is not None else None
            except (TypeError, ValueError):
                entry_price = None
            yield CanonicalLifecycleEvent(
                checkpoint_type="PAPER_ENTRY",
                canonical_timestamp=_iso(pts),
                canonical_event_id=event_id,
                canonical_context_episode_id=_opt_str(raw.get("lifecycle_episode_id")),
                trade_id=None,
                position_id=pos_id,
                canonical_timeframe=_opt_str(raw.get("timeframe")),
                canonical_side=_opt_str(raw.get("side")),
                entry_price=entry_price,
                close_price=None,
                close_reason=None,
                source_path=str(path),
                source_event_type="POSITION_OPEN",
                linkage_method=linkage,
                linkage_reason=linkage_reason,
                raw=raw,
            )
            n += 1
            if limit is not None and n >= int(limit):
                return


def iter_paper_closes(
    repo: Path,
    *,
    epoch_id: str | None = None,
    since_timestamp: str | None = None,
    limit: int | None = None,
) -> Iterator[CanonicalLifecycleEvent]:
    epoch = epoch_id or active_paper_epoch_id(repo)
    if not epoch:
        return
    path = repo / "data" / "trading" / "intrabar_paper" / epoch / "books" / "trades.jsonl"
    if not path.exists():
        return
    since = _parse_ts(since_timestamp)
    n = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(raw.get("status") or "").upper() not in {"CLOSED", "CLOSE", ""} and not raw.get("exit_ts"):
                # Prefer closed trades; skip open placeholders.
                if not raw.get("exit_ts"):
                    continue
            ts = raw.get("exit_ts") or raw.get("closed_at")
            pts = _parse_ts(ts)
            if pts is None:
                continue
            if since is not None and pts <= since:
                continue
            trade_id = _opt_str(raw.get("trade_id"))
            pos_id = _opt_str(raw.get("position_id"))
            if not trade_id and not pos_id:
                continue
            event_id = trade_id or f"CLOSE|{pos_id}|{_iso(pts)}"
            try:
                close_price = float(raw["exit_price"]) if raw.get("exit_price") is not None else None
            except (TypeError, ValueError):
                close_price = None
            try:
                entry_price = float(raw["entry_price"]) if raw.get("entry_price") is not None else None
            except (TypeError, ValueError):
                entry_price = None
            yield CanonicalLifecycleEvent(
                checkpoint_type="PAPER_CLOSE",
                canonical_timestamp=_iso(pts),
                canonical_event_id=event_id,
                canonical_context_episode_id=_opt_str(raw.get("lifecycle_episode_id")),
                trade_id=trade_id,
                position_id=pos_id,
                canonical_timeframe=_opt_str(raw.get("timeframe")),
                canonical_side=_opt_str(raw.get("side")),
                entry_price=entry_price,
                close_price=close_price,
                close_reason=_opt_str(raw.get("exit_reason")),
                source_path=str(path),
                source_event_type="TRADE_CLOSE",
                linkage_method="EXACT_ID" if trade_id else "DERIVED",
                linkage_reason=None if trade_id else "CLOSE_IDENTITY_FROM_POSITION_ID",
                raw=raw,
            )
            n += 1
            if limit is not None and n >= int(limit):
                return


def iter_lifecycle_events(
    repo: Path,
    *,
    epoch_id: str | None = None,
    since_timestamp: str | None = None,
) -> list[CanonicalLifecycleEvent]:
    """Collect and sort lifecycle events by canonical timestamp (stable)."""
    events: list[CanonicalLifecycleEvent] = []
    events.extend(list(iter_context_events(repo, since_timestamp=since_timestamp) or []))
    events.extend(list(iter_paper_entries(repo, epoch_id=epoch_id, since_timestamp=since_timestamp) or []))
    events.extend(list(iter_paper_closes(repo, epoch_id=epoch_id, since_timestamp=since_timestamp) or []))
    events.sort(
        key=lambda e: (
            e.canonical_timestamp,
            e.checkpoint_type,
            e.canonical_event_id,
        )
    )
    return events


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text
