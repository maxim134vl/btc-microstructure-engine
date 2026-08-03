"""Closed-bar context decision to durable LIVE1B event materialization.

This module is intentionally narrow: it does not score contexts, change lifecycle
rules, size positions, or price fills. It only turns already-written completed-bar
directional decisions into append-only context events with a causal event-time
contract that LIVE1B can consume.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from btc_ml.live.intrabar.context_event_journal import ContextEventJournal


PROVIDER_ID = "LIVE1A_CANONICAL_INTRABAR_CONTEXT"
MODEL_VERSION = "live1a_closed_bar_context_event_bridge_v1"
EVENT_TIME_CONTRACT = "CLOSED_BAR_DECISION_AVAILABLE_THEN_CAUSAL_BBO_V1"
ENTRY_INTENTS = frozenset({"INTENT_OPEN_LONG", "INTENT_OPEN_SHORT"})
DIRECTIONAL_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})
NON_DIRECTIONAL_CONTEXTS = frozenset({"", "OBSERVE", "NO_ACTIVE_CONTEXT", "STAND_ASIDE", "NONE", "NAN", "NAT"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_ts(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce", format="ISO8601")
    if pd.isna(ts):
        ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    out = pd.Timestamp(ts)
    return out.tz_convert("UTC") if out.tzinfo is not None else out.tz_localize("UTC")


def _iso(value: Any) -> str | None:
    ts = _to_ts(value)
    if ts is None:
        return None
    return ts.isoformat().replace("+00:00", "Z")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "nat", "none", "null", "<na>"}:
        return ""
    return text


def _context(value: Any) -> str:
    text = _clean(value).upper()
    if text == "LONG":
        return "LONG_CONTEXT"
    if text == "SHORT":
        return "SHORT_CONTEXT"
    return text


def _direction(context: str) -> str:
    if context == "LONG_CONTEXT":
        return "LONG"
    if context == "SHORT_CONTEXT":
        return "SHORT"
    return ""


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _timeframe(value: Any) -> str:
    text = _clean(value).upper()
    return {"15M": "M15", "30M": "M30", "1H": "H1", "4H": "H4"}.get(text, text)


def _source_timeframe(row: Mapping[str, Any]) -> str:
    return _timeframe(row.get("timeframe") or row.get("source_timeframe") or "M15")


def _episode_id(row: Mapping[str, Any], timeframe: str, direction: str) -> str | None:
    for key in ("lifecycle_episode_id", "context_episode_id", "episode_id"):
        value = _clean(row.get(key))
        if value:
            return value
    origin = _iso(
        row.get("lifecycle_episode_start_time")
        or row.get("active_context_started_at")
        or row.get("candidate_started_at")
    )
    if origin and direction:
        return f"{timeframe}:closed:{origin}:{direction}"
    return None


def _event_action_allowed(row: Mapping[str, Any]) -> bool:
    explicit = row.get("context_event_action_allowed")
    if explicit is not None and _clean(explicit):
        return _truthy(explicit)
    if _truthy(row.get("action_allowed")):
        return True
    # Compatibility with the current closed-bar logger: it deliberately keeps
    # legacy execution fields false, while additive paper signal fields carry the
    # paper-only directional intent. This is a materialization gate, not a model
    # selectivity change.
    if _clean(row.get("paper_action_candidate")).upper() in ENTRY_INTENTS:
        eligibility = _clean(row.get("signal_eligibility_status")).upper()
        if eligibility in {"", "ELIGIBLE_DIRECTIONAL_SIGNAL"}:
            return True
    return False


def _fresh_enough(row: Mapping[str, Any]) -> bool:
    if _truthy(row.get("pipeline_pending")) or _truthy(row.get("decision_stale")):
        return False
    freshness = _clean(row.get("decision_freshness_status") or row.get("freshness_status")).upper()
    if freshness and any(token in freshness for token in ("STALE", "PENDING", "MISSING")):
        return False
    return True


def _valid_bbo(current_bbo: Mapping[str, Any] | None, decision_available_at: pd.Timestamp) -> tuple[dict[str, Any] | None, str | None]:
    if not current_bbo:
        return None, "MISSING_BBO"
    bid = current_bbo.get("best_bid") or current_bbo.get("best_bid_price")
    ask = current_bbo.get("best_ask") or current_bbo.get("best_ask_price")
    mono = current_bbo.get("bbo_receive_monotonic_ns") or current_bbo.get("local_receive_monotonic_ns")
    ts = current_bbo.get("bbo_receive_timestamp") or current_bbo.get("local_receive_timestamp")
    bbo_ts = _to_ts(ts)
    try:
        bid_f = float(bid)
        ask_f = float(ask)
        mono_i = int(mono)
    except (TypeError, ValueError):
        return None, "INVALID_BBO"
    if bid_f <= 0 or ask_f <= 0 or ask_f < bid_f or bbo_ts is None:
        return None, "INVALID_BBO"
    if bbo_ts < decision_available_at:
        return None, "STALE_BBO_BEFORE_DECISION_AVAILABLE"
    return {
        "best_bid": bid_f,
        "best_ask": ask_f,
        "book_update_id": current_bbo.get("book_update_id"),
        "bbo_receive_monotonic_ns": mono_i,
        "bbo_receive_timestamp": _iso(bbo_ts),
        "event_timestamp": _iso(bbo_ts),
        "event_monotonic_ns": mono_i,
        "bbo_age_ms": 0.0,
    }, None


def _rows_from_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or len(frame) == 0:
        return []
    out = frame.copy()
    return out.astype(object).where(pd.notna(out), None).to_dict("records")


@dataclass
class MaterializationResult:
    emitted: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    duplicate_events: int = 0

    @property
    def emitted_count(self) -> int:
        return len(self.emitted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "emitted_count": self.emitted_count,
            "duplicate_events": self.duplicate_events,
            "emitted_event_ids": [str(e.get("context_event_id")) for e in self.emitted],
            "skipped": self.skipped[-20:],
        }


def materialize_closed_bar_events(
    rows: Iterable[Mapping[str, Any]],
    *,
    journal: ContextEventJournal,
    provider_id: str,
    epoch_id: str,
    current_bbo: Mapping[str, Any] | None,
    bridge_activated_at: Any,
    active_positions_by_timeframe: set[str] | None = None,
    traded_episodes: set[str] | None = None,
) -> MaterializationResult:
    result = MaterializationResult()
    activation_ts = _to_ts(bridge_activated_at)
    if activation_ts is None:
        raise ValueError("bridge_activated_at must be a valid UTC timestamp")
    open_tfs = {str(x).upper() for x in (active_positions_by_timeframe or set())}
    traded = {str(x) for x in (traded_episodes or set())}
    ordered = sorted(
        list(rows),
        key=lambda r: (
            _to_ts(r.get("decision_available_at") or r.get("decision_written_at_utc"))
            or pd.Timestamp.min.tz_localize("UTC"),
            _to_ts(r.get("source_bar_timestamp") or r.get("candle_timestamp"))
            or pd.Timestamp.min.tz_localize("UTC"),
        ),
    )
    for row in ordered:
        tf = _source_timeframe(row)
        source_bar_ts = _to_ts(row.get("source_bar_timestamp") or row.get("candle_timestamp"))
        decision_available = _to_ts(row.get("decision_available_at") or row.get("decision_written_at_utc"))
        if source_bar_ts is None or decision_available is None:
            result.skipped.append({"reason": "MISSING_SOURCE_OR_DECISION_TIME", "timeframe": tf})
            continue
        if decision_available < activation_ts:
            result.skipped.append({"reason": "PRE_BRIDGE_ACTIVATION_ROW", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue
        if decision_available < source_bar_ts:
            result.skipped.append({"reason": "DECISION_BEFORE_SOURCE_BAR", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue
        if not _fresh_enough(row):
            result.skipped.append({"reason": "STALE_OR_PENDING_INPUT", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue

        current = _context(row.get("active_market_context") or row.get("candidate_context"))
        previous = _context(row.get("previous_active_market_context"))
        direction = _direction(current)
        prev_direction = _direction(previous)
        context_origin = _iso(
            row.get("context_origin_timestamp")
            or row.get("lifecycle_episode_start_time")
            or row.get("active_context_started_at")
            or row.get("candidate_started_at")
        )
        episode_id = _episode_id(row, tf, direction or prev_direction)
        if not episode_id:
            result.skipped.append({"reason": "MISSING_EPISODE_ID", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue

        event_type = None
        new_context = current or "OBSERVE"
        previous_context = previous or "OBSERVE"
        extra: dict[str, Any] = {}
        if current in DIRECTIONAL_CONTEXTS:
            if not _event_action_allowed(row):
                result.skipped.append({"reason": "ACTION_NOT_ALLOWED", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
                continue
            directional_flip = (
                previous in DIRECTIONAL_CONTEXTS
                and previous != current
            )
            if tf in open_tfs and not directional_flip:
                result.skipped.append({"reason": "ACTIVE_POSITION", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
                continue
            if episode_id in traded and not directional_flip:
                result.skipped.append({"reason": "EPISODE_ALREADY_TRADED", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
                continue
            origin_ts = _to_ts(context_origin)
            if directional_flip:
                event_type = "CONTEXT_FLIP"
            elif origin_ts is not None and origin_ts < activation_ts:
                event_type = "CONTEXT_START"
                previous_context = "OBSERVE"
                extra = {
                    "revalidated_after_restart": True,
                    "revalidation_event_type": "CONTEXT_START",
                    "historical_context_origin_timestamp": context_origin,
                    "revalidation_reason": "PRE_EXISTING_ACTIVE_CONTEXT_CONFIRMED_ON_FRESH_BAR",
                }
            elif previous not in DIRECTIONAL_CONTEXTS:
                event_type = "CONTEXT_START"
            else:
                result.skipped.append({"reason": "SAME_CONTEXT_CONTINUATION", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
                continue
        elif previous in DIRECTIONAL_CONTEXTS and current in NON_DIRECTIONAL_CONTEXTS:
            event_type = "CONTEXT_END"
            direction = prev_direction
        else:
            result.skipped.append({"reason": "NON_DIRECTIONAL", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue

        bbo, bbo_reason = _valid_bbo(current_bbo, decision_available)
        if bbo is None:
            result.skipped.append({"reason": bbo_reason or "NO_CAUSAL_BBO", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue

        mid = (float(bbo["best_bid"]) + float(bbo["best_ask"])) / 2.0
        metadata = {
            "event_time_contract": EVENT_TIME_CONTRACT,
            "source": "closed_bar_context_decision",
            "context_event_price_source": "causal_bbo_mid",
            "source_bar_close": row.get("close") if row.get("close") is not None else row.get("candle_close"),
            "source_bar_close_not_execution_price": True,
            "execution_not_before": bbo["event_timestamp"],
            "paper_action_candidate": row.get("paper_action_candidate"),
            "intended_side": row.get("intended_side"),
            "signal_eligibility_status": row.get("signal_eligibility_status"),
            "source_decision_id": row.get("decision_id"),
            **extra,
        }
        event = journal.build_event(
            timeframe=tf,
            event_type=event_type,
            previous_context=previous_context,
            new_context=new_context,
            event_timestamp=str(bbo["event_timestamp"]),
            event_monotonic_ns=int(bbo["event_monotonic_ns"]),
            context_event_price=str(mid),
            last_trade_id=row.get("last_trade_id"),
            last_trade_timestamp=row.get("last_trade_timestamp"),
            best_bid=bbo["best_bid"],
            best_ask=bbo["best_ask"],
            book_update_id=bbo.get("book_update_id"),
            bbo_receive_monotonic_ns=bbo["bbo_receive_monotonic_ns"],
            bbo_age_ms=bbo["bbo_age_ms"],
            connection_session_id=current_bbo.get("connection_session_id") if current_bbo else None,
            reconnect_generation=current_bbo.get("reconnect_generation") if current_bbo else None,
            causal_cutoff_timestamp=_iso(source_bar_ts),
            causal_cutoff_monotonic_ns=None,
            model_version=MODEL_VERSION,
            lifecycle_episode_id=episode_id,
            evidence={
                "active_market_context": current,
                "previous_active_market_context": previous,
                "lifecycle_state": row.get("lifecycle_state"),
                "transition_reason": row.get("transition_reason"),
            },
            provider_id=provider_id,
            epoch_id=epoch_id,
            source_bar_timestamp=_iso(source_bar_ts),
            decision_available_at=_iso(decision_available),
            context_origin_timestamp=context_origin,
            execution_not_before=bbo["event_timestamp"],
            direction=direction,
            evaluation_mode="CLOSED_BAR_CONTEXT_DECISION",
            extra_metadata=metadata,
        )
        if journal.append(event):
            result.emitted.append(event)
        else:
            result.duplicate_events += 1
    return result


class ClosedBarContextEventBridge:
    """Small production adapter around :func:`materialize_closed_bar_events`."""

    def __init__(
        self,
        *,
        repo_root: Path,
        context_journal: ContextEventJournal,
        provider_id: str = PROVIDER_ID,
        bridge_activated_at: str | None = None,
        decision_log_path: Path | None = None,
        epoch_path: Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.context_journal = context_journal
        self.provider_id = provider_id
        self.bridge_activated_at = bridge_activated_at or utc_now_iso()
        self.decision_log_path = decision_log_path or self.repo_root / "data" / "live" / "context_decision_log.parquet"
        self.epoch_path = epoch_path or self.repo_root / "data" / "trading" / "paper_epochs" / "active.json"
        self.last_result = MaterializationResult()
        self.last_run_at: str | None = None

    def _active_epoch(self) -> dict[str, Any] | None:
        if not self.epoch_path.exists():
            return None
        try:
            raw = json.loads(self.epoch_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if str(raw.get("epoch_status") or "").upper() != "ACTIVE":
            return None
        if bool(raw.get("paper_only")) is not True and raw.get("paper_only") is not None:
            return None
        if bool(raw.get("real_execution_enabled") or raw.get("real_execution")):
            return None
        return raw

    def _epoch_books_root(self, epoch_id: str) -> Path:
        return self.repo_root / "data" / "trading" / "intrabar_paper" / epoch_id / "books"

    def _jsonl_rows(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

    def _open_timeframes_and_traded_episodes(self, epoch_id: str) -> tuple[set[str], set[str]]:
        root = self._epoch_books_root(epoch_id)
        positions = self._jsonl_rows(root / "positions.jsonl")
        latest: dict[str, dict[str, Any]] = {}
        traded: set[str] = set()
        for row in positions:
            pid = _clean(row.get("position_id"))
            if pid:
                latest[pid] = row
            ep = _clean(row.get("lifecycle_episode_id"))
            if ep:
                traded.add(ep)
        open_tfs = {
            _timeframe(row.get("timeframe"))
            for row in latest.values()
            if _clean(row.get("status")).upper() == "OPEN"
        }
        for row in self._jsonl_rows(root / "trades.jsonl"):
            ep = _clean(row.get("lifecycle_episode_id"))
            if ep:
                traded.add(ep)
        return open_tfs, traded

    def maybe_materialize(self, *, current_bbo: Mapping[str, Any] | None) -> MaterializationResult:
        epoch = self._active_epoch()
        if epoch is None:
            self.last_result = MaterializationResult(skipped=[{"reason": "NO_ACTIVE_SAFE_EPOCH"}])
            return self.last_result
        if not self.decision_log_path.exists():
            self.last_result = MaterializationResult(skipped=[{"reason": "MISSING_DECISION_LOG"}])
            return self.last_result
        frame = pd.read_parquet(self.decision_log_path)
        rows = _rows_from_frame(frame.tail(256))
        epoch_id = str(epoch["paper_epoch_id"])
        open_tfs, traded = self._open_timeframes_and_traded_episodes(epoch_id)
        self.last_result = materialize_closed_bar_events(
            rows,
            journal=self.context_journal,
            provider_id=self.provider_id,
            epoch_id=epoch_id,
            current_bbo=current_bbo,
            bridge_activated_at=self.bridge_activated_at,
            active_positions_by_timeframe=open_tfs,
            traded_episodes=traded,
        )
        self.last_run_at = utc_now_iso()
        return self.last_result
