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
from btc_ml.live.intrabar.context_event_freshness import (
    FRESHNESS_FRESH,
    FRESHNESS_STALE_AGE,
    annotate_event_provenance,
    evaluate_entry_freshness,
    is_recovery_delivery_event,
    is_restart_backfill_event,
    resolve_context_event_max_age_seconds,
)


PROVIDER_ID = "LIVE1A_CANONICAL_INTRABAR_CONTEXT"
MODEL_VERSION = "live1a_closed_bar_context_event_bridge_v1"
EVENT_TIME_CONTRACT = "CLOSED_BAR_DECISION_AVAILABLE_THEN_CAUSAL_BBO_V1"
ENTRY_INTENTS = frozenset({"INTENT_OPEN_LONG", "INTENT_OPEN_SHORT"})
ENTRY_EVENT_TYPES = frozenset({"CONTEXT_START", "CONTEXT_FLIP"})
DIRECTIONAL_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})
NON_DIRECTIONAL_CONTEXTS = frozenset({"", "OBSERVE", "NO_ACTIVE_CONTEXT", "STAND_ASIDE", "NONE", "NAN", "NAT"})
DELIVERY_MODE_LIVE = "LIVE"
DELIVERY_MODE_RECOVERY = "RECOVERY"
LIVE_PUBLICATION_RACE_GRACE_SECONDS = 5.0
RECOVERY_DECISION_LOOKBACK_ROWS = 4096
SUPPORTED_RECOVERY_TIMEFRAMES = frozenset({"M15", "M30", "H1", "H4"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_context_event_max_age_seconds(repo_root: Path) -> float:
    cfg_path = repo_root / "config" / "intrabar_paper_execution.json"
    configured: float | None = None
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            if raw.get("context_event_max_age_seconds") is not None:
                configured = float(raw["context_event_max_age_seconds"])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            configured = None
    return resolve_context_event_max_age_seconds(configured=configured)


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
    decision_iso = _iso(decision_available_at)
    return {
        "best_bid": bid_f,
        "best_ask": ask_f,
        "book_update_id": current_bbo.get("book_update_id"),
        "bbo_receive_monotonic_ns": mono_i,
        "bbo_receive_timestamp": _iso(bbo_ts),
        "event_timestamp": decision_iso,
        "event_monotonic_ns": mono_i,
        "bbo_age_ms": 0.0,
        "execution_not_before": _iso(bbo_ts),
    }, None


@dataclass(frozen=True)
class PerTfRecoveryWatermark:
    """Durable per-timeframe lineage from the published context journal."""

    timeframe: str
    active_context: str
    lifecycle_episode_id: str
    source_bar_timestamp: str
    decision_available_at: pd.Timestamp
    source_decision_id: str | None = None
    context_event_id: str | None = None
    event_identity_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "active_context": self.active_context,
            "lifecycle_episode_id": self.lifecycle_episode_id,
            "source_bar_timestamp": self.source_bar_timestamp,
            "decision_available_at": _iso(self.decision_available_at),
            "source_decision_id": self.source_decision_id,
            "context_event_id": self.context_event_id,
            "event_identity_key": self.event_identity_key,
        }


def _decision_available_ts(row: Mapping[str, Any]) -> pd.Timestamp | None:
    return _to_ts(row.get("decision_available_at") or row.get("decision_written_at_utc"))


def _source_bar_ts(row: Mapping[str, Any]) -> pd.Timestamp | None:
    return _to_ts(row.get("source_bar_timestamp") or row.get("candle_timestamp"))


def _row_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _decision_available_ts(row) or pd.Timestamp.min.tz_localize("UTC"),
        _source_bar_ts(row) or pd.Timestamp.min.tz_localize("UTC"),
        _clean(row.get("decision_id")),
    )


def _row_at_or_before_watermark(row: Mapping[str, Any], watermark: PerTfRecoveryWatermark) -> bool:
    row_da = _decision_available_ts(row)
    if row_da is None:
        return False
    if row_da < watermark.decision_available_at:
        return True
    if row_da > watermark.decision_available_at:
        return False
    row_bar = _source_bar_ts(row)
    wm_bar = _to_ts(watermark.source_bar_timestamp)
    if row_bar is None or wm_bar is None:
        return True
    if row_bar < wm_bar:
        return True
    if row_bar > wm_bar:
        return False
    row_id = _clean(row.get("decision_id"))
    wm_id = _clean(watermark.source_decision_id)
    if row_id and wm_id:
        return row_id <= wm_id
    return True


def load_per_tf_recovery_watermarks(journal_path: Path) -> dict[str, PerTfRecoveryWatermark]:
    """Load the latest published canonical context state per timeframe."""
    watermarks: dict[str, PerTfRecoveryWatermark] = {}
    if not journal_path.exists():
        return watermarks
    try:
        text = journal_path.read_text(encoding="utf-8")
    except OSError:
        return watermarks
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        tf = _timeframe(event.get("timeframe"))
        if tf not in SUPPORTED_RECOVERY_TIMEFRAMES:
            continue
        decision_available = _to_ts(event.get("decision_available_at") or event.get("event_timestamp"))
        source_bar = _iso(event.get("source_bar_timestamp"))
        if decision_available is None or not source_bar:
            continue
        candidate = PerTfRecoveryWatermark(
            timeframe=tf,
            active_context=_context(event.get("new_context")),
            lifecycle_episode_id=_clean(event.get("lifecycle_episode_id")),
            source_bar_timestamp=source_bar,
            decision_available_at=decision_available,
            source_decision_id=_clean(event.get("source_decision_id"))
            or _clean((event.get("extra_metadata") or {}).get("source_decision_id"))
            or None,
            context_event_id=_clean(event.get("context_event_id")) or None,
            event_identity_key=_clean(event.get("event_identity_key")) or None,
        )
        current = watermarks.get(tf)
        if current is None or _row_sort_key(
            {
                "decision_written_at_utc": candidate.decision_available_at,
                "candle_timestamp": candidate.source_bar_timestamp,
                "decision_id": candidate.source_decision_id,
            }
        ) >= _row_sort_key(
            {
                "decision_written_at_utc": current.decision_available_at,
                "candle_timestamp": current.source_bar_timestamp,
                "decision_id": current.source_decision_id,
            }
        ):
            watermarks[tf] = candidate
    return watermarks


def _candidate_decision_rows(
    frame: pd.DataFrame,
    recovery_watermarks: Mapping[str, PerTfRecoveryWatermark] | None,
) -> list[dict[str, Any]]:
    if frame is None or len(frame) == 0:
        return []
    rows = _rows_from_frame(frame)
    if recovery_watermarks:
        min_wm = min(wm.decision_available_at for wm in recovery_watermarks.values())
        rows = [
            row
            for row in rows
            if (_decision_available_ts(row) or pd.Timestamp.min.tz_localize("UTC")) >= (min_wm - pd.Timedelta(seconds=1))
        ]
    rows = sorted(rows, key=_row_sort_key)
    if len(rows) > RECOVERY_DECISION_LOOKBACK_ROWS:
        rows = rows[-RECOVERY_DECISION_LOOKBACK_ROWS:]
    return rows


def _classify_delivery_mode(
    *,
    event_type: str,
    extra: Mapping[str, Any],
    decision_available: pd.Timestamp,
    previous_bridge_invocation_at: pd.Timestamp | None,
    bridge_activated_at: pd.Timestamp,
) -> str:
    """Classify whether an entry event is live or recovery delivery.

    Recovery is deterministic from explicit materialization markers and the
    durable previous-bridge-invocation watermark. A small publication grace is
    required because ``decision_written_at_utc`` is captured before the atomic
    Parquet replacement becomes visible to the bridge. Without it, a decision
    published immediately after one poll is misclassified as recovery by the
    next poll. It does not depend on batch cardinality or timeframe count.
    """
    if str(event_type or "").upper() not in ENTRY_EVENT_TYPES:
        return DELIVERY_MODE_LIVE

    if bool(extra.get("restart_backfill")):
        return DELIVERY_MODE_RECOVERY
    if str(extra.get("materialization_class") or "").upper() == "RESTART_BACKFILL":
        return DELIVERY_MODE_RECOVERY
    if bool(extra.get("revalidated_after_restart")):
        return DELIVERY_MODE_RECOVERY
    if bool(extra.get("recovered_after_restart")):
        return DELIVERY_MODE_RECOVERY
    if str(extra.get("materialization_class") or "").upper() == "DURABLE_CONTEXT_RECOVERY":
        return DELIVERY_MODE_RECOVERY

    watermark = previous_bridge_invocation_at or bridge_activated_at
    recovery_cutoff = watermark - pd.Timedelta(seconds=LIVE_PUBLICATION_RACE_GRACE_SECONDS)
    if decision_available < recovery_cutoff:
        return DELIVERY_MODE_RECOVERY

    return DELIVERY_MODE_LIVE


def _recovery_source_bar_close(row: Mapping[str, Any]) -> Any:
    """Historical attribution price for recovery events (never execution fill price)."""
    for key in ("close", "candle_close", "context_origin_price"):
        value = row.get(key)
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        return value
    return None


def _live_context_occurrence_price(row: Mapping[str, Any]) -> tuple[float | None, str]:
    """Context-occurrence price for provenance / audit; never invent from BBO or bar close.

    Missing occurrence price is not a LIVE execution blocker. Paper ENTRY is
    priced from execution-time BBO in LIVE1B.
    """
    for key, source in (
        ("context_event_price", "context_event_price"),
        ("context_origin_price", "context_origin_price"),
        ("historical_context_event_price", "historical_context_event_price"),
    ):
        value = row.get(key)
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        text = _clean(value)
        if not text:
            continue
        try:
            px = float(text)
        except (TypeError, ValueError):
            continue
        if px > 0.0 and px == px:
            return px, source
    return None, "MISSING_CONTEXT_OCCURRENCE_PRICE"


def _context_occurrence_timestamp(
    row: Mapping[str, Any],
    *,
    source_bar_ts: pd.Timestamp,
    decision_available: pd.Timestamp,
) -> pd.Timestamp:
    """Timestamp of context occurrence for event_timestamp (not delayed materialization)."""
    for key in (
        "context_event_timestamp",
        "context_origin_timestamp",
        "lifecycle_episode_start_time",
        "active_context_started_at",
        "candidate_started_at",
    ):
        ts = _to_ts(row.get(key))
        if ts is not None:
            return ts
    return source_bar_ts if source_bar_ts is not None else decision_available


def _valid_recovery_bbo(
    current_bbo: Mapping[str, Any] | None,
    *,
    decision_available_at: pd.Timestamp,
    source_bar_close: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Recovery events keep historical decision time/price separate from execution BBO."""
    if not current_bbo:
        return None, "MISSING_RECOVERY_BBO"
    bid = current_bbo.get("best_bid") or current_bbo.get("best_bid_price")
    ask = current_bbo.get("best_ask") or current_bbo.get("best_ask_price")
    mono = current_bbo.get("bbo_receive_monotonic_ns") or current_bbo.get("local_receive_monotonic_ns")
    ts = current_bbo.get("bbo_receive_timestamp") or current_bbo.get("local_receive_timestamp")
    bbo_ts = _to_ts(ts)
    try:
        bid_f = float(bid)
        ask_f = float(ask)
        mono_i = int(mono)
        historical_price = float(source_bar_close)
    except (TypeError, ValueError):
        return None, "MISSING_RECOVERY_HISTORICAL_PRICE"
    if bid_f <= 0 or ask_f <= 0 or ask_f < bid_f or bbo_ts is None or historical_price <= 0:
        return None, "INVALID_RECOVERY_BBO"
    decision_iso = _iso(decision_available_at)
    return {
        "best_bid": bid_f,
        "best_ask": ask_f,
        "book_update_id": current_bbo.get("book_update_id"),
        "bbo_receive_monotonic_ns": mono_i,
        "bbo_receive_timestamp": _iso(bbo_ts),
        "event_timestamp": decision_iso,
        "event_monotonic_ns": mono_i,
        "bbo_age_ms": 0.0,
        "execution_not_before": _iso(bbo_ts),
        "historical_context_event_price": historical_price,
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
    recovery: dict[str, Any] = field(
        default_factory=lambda: {
            "mode_active": False,
            "per_tf_watermarks": {},
            "rows_scanned": 0,
            "transitions_reconstructed": 0,
            "duplicates_skipped": 0,
            "last_recovered_source_decision_id": None,
            "last_run_result": "idle",
        }
    )

    @property
    def emitted_count(self) -> int:
        return len(self.emitted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "emitted_count": self.emitted_count,
            "duplicate_events": self.duplicate_events,
            "emitted_event_ids": [str(e.get("context_event_id")) for e in self.emitted],
            "skipped": self.skipped[-20:],
            "recovery": dict(self.recovery),
        }


def _journal_events(journal: ContextEventJournal) -> list[dict[str, Any]]:
    path = getattr(journal, "path", None)
    if path is None or not Path(path).exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
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


def _episode_entry_key(timeframe: str, episode_id: str) -> tuple[str, str]:
    return (str(timeframe).upper(), str(episode_id))


def _is_stale_blocked_live_unfilled_entry(event: Mapping[str, Any]) -> bool:
    etype = str(event.get("event_type") or "").upper()
    if etype not in ENTRY_EVENT_TYPES:
        return False
    if is_restart_backfill_event(event) or is_recovery_delivery_event(event):
        return False
    if str(event.get("delivery_mode") or "").upper() == DELIVERY_MODE_RECOVERY:
        return False
    if str(event.get("delivery_mode") or "LIVE").upper() != DELIVERY_MODE_LIVE:
        return False
    freshness = str(event.get("freshness_status") or "").upper()
    if event.get("execution_eligible") is False or freshness == FRESHNESS_STALE_AGE:
        return True
    return False


def _index_episode_entry_states(
    events: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Track last LIVE entry and whether a stale-blocked retry already fired."""
    states: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        tf = _timeframe(event.get("timeframe"))
        episode_id = _clean(event.get("lifecycle_episode_id") or event.get("episode_id"))
        if not tf or not episode_id:
            continue
        key = _episode_entry_key(tf, episode_id)
        state = states.setdefault(key, {"last_entry": None, "retry_emitted": False})
        if bool(event.get("stale_blocked_entry_retry")):
            state["retry_emitted"] = True
        if str(event.get("event_type") or "").upper() in ENTRY_EVENT_TYPES:
            state["last_entry"] = dict(event)
    return states


def _stale_blocked_retry_extra(
    *,
    row: Mapping[str, Any],
    timeframe: str,
    episode_id: str,
    decision_available: pd.Timestamp,
    context_origin: str | None,
    source_bar_ts: pd.Timestamp,
    max_age_seconds: float,
    is_recovery_delivery: bool,
    open_tfs: set[str],
    traded: set[str],
    episode_states: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    """One LIVE retry for a stale-blocked unfilled episode; never a START flood.

    Does not require ``action_allowed``: production sticky episodes stay ACTIVE with
    ``action_allowed=False`` after a stale-blocked LIVE FLIP, and that gate would
    permanently freeze the unfilled episode.
    """
    if is_recovery_delivery:
        return None
    current = _context(row.get("active_market_context") or row.get("candidate_context"))
    if current not in DIRECTIONAL_CONTEXTS:
        return None
    if timeframe in open_tfs:
        return None
    if episode_id in traded:
        return None
    state = episode_states.get(_episode_entry_key(timeframe, episode_id))
    if not state or state.get("retry_emitted"):
        return None
    prior = state.get("last_entry")
    if not isinstance(prior, Mapping) or not _is_stale_blocked_live_unfilled_entry(prior):
        return None
    probe = {
        "event_type": str(prior.get("event_type") or "CONTEXT_FLIP"),
        "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
        "materialization_source": "closed_bar_context_decision",
        "decision_available_at": _iso(decision_available),
        "event_timestamp": _iso(decision_available),
        "original_context_timestamp": context_origin,
        "context_origin_timestamp": context_origin,
        "source_bar_timestamp": _iso(source_bar_ts),
        "restart_backfill": False,
        "delivery_mode": DELIVERY_MODE_LIVE,
        "lifecycle_episode_id": episode_id,
        "paper_action_candidate": row.get("paper_action_candidate"),
        "signal_eligibility_status": row.get("signal_eligibility_status"),
    }
    if evaluate_entry_freshness(probe, max_age_seconds=max_age_seconds) != FRESHNESS_FRESH:
        return None
    prior_type = str(prior.get("event_type") or "CONTEXT_FLIP").upper()
    if prior_type not in ENTRY_EVENT_TYPES:
        prior_type = "CONTEXT_FLIP"
    return {
        "event_type": prior_type,
        "stale_blocked_entry_retry": True,
        "retry_of_context_event_id": prior.get("context_event_id"),
        "retry_reason": "STALE_BLOCKED_LIVE_ENTRY_UNFILLED",
    }


def materialize_closed_bar_events(
    rows: Iterable[Mapping[str, Any]],
    *,
    journal: ContextEventJournal,
    provider_id: str,
    epoch_id: str,
    current_bbo: Mapping[str, Any] | None,
    bridge_activated_at: Any,
    previous_bridge_invocation_at: Any = None,
    recovery_watermarks: Mapping[str, PerTfRecoveryWatermark] | None = None,
    active_positions_by_timeframe: set[str] | None = None,
    traded_episodes: set[str] | None = None,
    context_event_max_age_seconds: float | None = None,
) -> MaterializationResult:
    result = MaterializationResult()
    activation_ts = _to_ts(bridge_activated_at)
    if activation_ts is None:
        raise ValueError("bridge_activated_at must be a valid UTC timestamp")
    max_age_seconds = float(
        context_event_max_age_seconds
        if context_event_max_age_seconds is not None
        else resolve_context_event_max_age_seconds()
    )
    previous_invocation_ts = _to_ts(previous_bridge_invocation_at)
    open_tfs = {str(x).upper() for x in (active_positions_by_timeframe or set())}
    traded = {str(x) for x in (traded_episodes or set())}
    watermarks = dict(recovery_watermarks or {})
    episode_states = _index_episode_entry_states(_journal_events(journal))
    result.recovery["mode_active"] = bool(watermarks)
    result.recovery["per_tf_watermarks"] = {
        tf: wm.to_dict() for tf, wm in sorted(watermarks.items())
    }

    # Causal lineage from earlier already-published decisions in this batch.
    # Seed from durable journal watermarks so missed transitions can be reconstructed.
    last_published_context_by_tf: dict[str, str] = {
        tf: wm.active_context for tf, wm in watermarks.items() if wm.active_context
    }
    pending_events: list[dict[str, Any]] = []

    ordered = sorted(list(rows), key=_row_sort_key)
    result.recovery["rows_scanned"] = len(ordered)
    for row in ordered:
        tf = _source_timeframe(row)
        source_bar_ts = _source_bar_ts(row)
        decision_available = _decision_available_ts(row)
        if source_bar_ts is None or decision_available is None:
            result.skipped.append({"reason": "MISSING_SOURCE_OR_DECISION_TIME", "timeframe": tf})
            continue

        watermark = watermarks.get(tf)
        if watermark and _row_at_or_before_watermark(row, watermark):
            result.skipped.append(
                {
                    "reason": "BEFORE_RECOVERY_WATERMARK",
                    "timeframe": tf,
                    "source_bar_timestamp": _iso(source_bar_ts),
                }
            )
            continue

        is_recovery_delivery = False
        if watermark and decision_available < activation_ts:
            is_recovery_delivery = True
        elif (
            not watermark
            and decision_available < activation_ts
        ):
            result.skipped.append(
                {
                    "reason": "PRE_BRIDGE_ACTIVATION_ROW",
                    "timeframe": tf,
                    "source_bar_timestamp": _iso(source_bar_ts),
                }
            )
            continue

        if decision_available < source_bar_ts:
            result.skipped.append({"reason": "DECISION_BEFORE_SOURCE_BAR", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue
        if not _fresh_enough(row):
            result.skipped.append({"reason": "STALE_OR_PENDING_INPUT", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue

        current = _context(row.get("active_market_context") or row.get("candidate_context"))
        previous = _context(row.get("previous_active_market_context"))

        lineage_previous = last_published_context_by_tf.get(tf, "")
        previous_context_source = "decision_row"
        if previous in {"", "NONE", "NAN", "NAT", "NULL"} and lineage_previous:
            previous = lineage_previous
            previous_context_source = "previous_published_decision"

        direction = _direction(current)
        prev_direction = _direction(previous)
        context_origin = _iso(
            row.get("context_origin_timestamp")
            or row.get("lifecycle_episode_start_time")
            or row.get("active_context_started_at")
            or row.get("candidate_started_at")
        )
        episode_id = _episode_id(row, tf, direction or prev_direction)
        retry_extra: dict[str, Any] | None = None
        if current and lineage_previous and current == lineage_previous:
            if episode_id:
                retry_extra = _stale_blocked_retry_extra(
                    row=row,
                    timeframe=tf,
                    episode_id=episode_id,
                    decision_available=decision_available,
                    context_origin=context_origin,
                    source_bar_ts=source_bar_ts,
                    max_age_seconds=max_age_seconds,
                    is_recovery_delivery=is_recovery_delivery,
                    open_tfs=open_tfs,
                    traded=traded,
                    episode_states=episode_states,
                )
            if retry_extra is None:
                result.skipped.append(
                    {
                        "reason": "SAME_CONTEXT_CONTINUATION",
                        "timeframe": tf,
                        "source_bar_timestamp": _iso(source_bar_ts),
                    }
                )
                continue

        # The row already passed causal timestamp/freshness checks above.
        # It therefore becomes the previous immutable decision for this TF,
        # regardless of whether materialization below emits or skips it.
        if current:
            last_published_context_by_tf[tf] = current
        if not episode_id:
            result.skipped.append({"reason": "MISSING_EPISODE_ID", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue

        event_type = None
        new_context = current or "OBSERVE"
        previous_context = previous or "OBSERVE"
        extra: dict[str, Any] = {}
        if retry_extra is not None:
            # Retry intentionally ignores action_allowed: sticky ACTIVE episodes
            # after a stale-blocked LIVE FLIP often carry action_allowed=False.
            event_type = str(retry_extra["event_type"])
            extra = {k: v for k, v in retry_extra.items() if k != "event_type"}
        elif current in DIRECTIONAL_CONTEXTS:
            directional_flip = (
                previous in DIRECTIONAL_CONTEXTS
                and previous != current
            )
            action_allowed = _event_action_allowed(row)
            if not action_allowed:
                retry_extra = _stale_blocked_retry_extra(
                    row=row,
                    timeframe=tf,
                    episode_id=episode_id,
                    decision_available=decision_available,
                    context_origin=context_origin,
                    source_bar_ts=source_bar_ts,
                    max_age_seconds=max_age_seconds,
                    is_recovery_delivery=is_recovery_delivery,
                    open_tfs=open_tfs,
                    traded=traded,
                    episode_states=episode_states,
                )
                if retry_extra is None:
                    result.skipped.append({"reason": "ACTION_NOT_ALLOWED", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
                    continue
                event_type = str(retry_extra["event_type"])
                extra = {k: v for k, v in retry_extra.items() if k != "event_type"}
            else:
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
                        "restart_backfill": True,
                        "materialization_class": "RESTART_BACKFILL",
                        "revalidation_event_type": "CONTEXT_START",
                        "historical_context_origin_timestamp": context_origin,
                        "revalidation_reason": "PRE_EXISTING_ACTIVE_CONTEXT_CONFIRMED_ON_FRESH_BAR",
                    }
                elif previous not in DIRECTIONAL_CONTEXTS:
                    event_type = "CONTEXT_START"
                else:
                    retry_extra = _stale_blocked_retry_extra(
                        row=row,
                        timeframe=tf,
                        episode_id=episode_id,
                        decision_available=decision_available,
                        context_origin=context_origin,
                        source_bar_ts=source_bar_ts,
                        max_age_seconds=max_age_seconds,
                        is_recovery_delivery=is_recovery_delivery,
                        open_tfs=open_tfs,
                        traded=traded,
                        episode_states=episode_states,
                    )
                    if retry_extra is None:
                        result.skipped.append({"reason": "SAME_CONTEXT_CONTINUATION", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
                        continue
                    event_type = str(retry_extra["event_type"])
                    extra = {k: v for k, v in retry_extra.items() if k != "event_type"}
        elif previous in DIRECTIONAL_CONTEXTS and current in NON_DIRECTIONAL_CONTEXTS:
            event_type = "CONTEXT_END"
            direction = prev_direction
        else:
            result.skipped.append({"reason": "NON_DIRECTIONAL", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
            continue

        source_bar_close = _recovery_source_bar_close(row)
        occurrence_ts = _context_occurrence_timestamp(
            row,
            source_bar_ts=source_bar_ts,
            decision_available=decision_available,
        )
        if is_recovery_delivery:
            bbo, bbo_reason = _valid_recovery_bbo(
                current_bbo,
                decision_available_at=decision_available,
                source_bar_close=source_bar_close,
            )
            if bbo is None:
                result.skipped.append(
                    {
                        "reason": bbo_reason or "NO_RECOVERY_BBO",
                        "timeframe": tf,
                        "source_bar_timestamp": _iso(source_bar_ts),
                    }
                )
                continue
            extra.update(
                {
                    "recovered_after_restart": True,
                    "materialization_class": "DURABLE_CONTEXT_RECOVERY",
                    "recovery_reason": "MISSED_CANONICAL_TRANSITION_AFTER_JOURNAL_WATERMARK",
                    "historical_context_event_price": bbo["historical_context_event_price"],
                    "recovery_execution_bbo_timestamp": bbo["execution_not_before"],
                    "context_occurrence_timestamp": _iso(occurrence_ts) or str(bbo["event_timestamp"]),
                }
            )
            context_event_price = str(bbo["historical_context_event_price"])
            context_event_price_source = (
                "context_origin_price_recovery"
                if row.get("close") is None and row.get("candle_close") is None
                else "source_bar_close_recovery"
            )
            event_timestamp = str(bbo["event_timestamp"])
        else:
            bbo, bbo_reason = _valid_bbo(current_bbo, decision_available)
            if bbo is None:
                result.skipped.append({"reason": bbo_reason or "NO_CAUSAL_BBO", "timeframe": tf, "source_bar_timestamp": _iso(source_bar_ts)})
                continue
            occurrence_price, context_event_price_source = _live_context_occurrence_price(row)
            if occurrence_price is None:
                context_event_price = ""
                extra["entry_price_status"] = "MISSING_CONTEXT_OCCURRENCE_PRICE"
                extra["context_event_price_missing"] = True
            else:
                context_event_price = str(occurrence_price)
            # Occurrence clock for provenance; BBO mono remains causal gate.
            # Missing occurrence price is audit information, not a LIVE blocker.
            event_timestamp = _iso(occurrence_ts) or str(bbo["event_timestamp"])
            extra["context_occurrence_timestamp"] = _iso(occurrence_ts) or event_timestamp

        metadata = {
            "event_time_contract": EVENT_TIME_CONTRACT,
            "source": "closed_bar_context_decision",
            "context_event_price_source": context_event_price_source,
            "source_bar_close": source_bar_close,
            "source_bar_close_not_execution_price": True,
            "execution_not_before": bbo["execution_not_before"],
            "paper_action_candidate": row.get("paper_action_candidate"),
            "intended_side": row.get("intended_side"),
            "signal_eligibility_status": row.get("signal_eligibility_status"),
            "source_decision_id": row.get("decision_id"),
            "previous_context_source": previous_context_source,
            **extra,
        }
        event = journal.build_event(
            timeframe=tf,
            event_type=event_type,
            previous_context=previous_context,
            new_context=new_context,
            event_timestamp=event_timestamp,
            event_monotonic_ns=int(bbo["event_monotonic_ns"]),
            context_event_price=context_event_price,
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
                "previous_active_market_context_source": previous_context_source,
                "lifecycle_state": row.get("lifecycle_state"),
                "transition_reason": row.get("transition_reason"),
            },
            provider_id=provider_id,
            epoch_id=epoch_id,
            source_bar_timestamp=_iso(source_bar_ts),
            decision_available_at=_iso(decision_available),
            context_origin_timestamp=context_origin,
            execution_not_before=bbo["execution_not_before"],
            direction=direction,
            evaluation_mode="CLOSED_BAR_CONTEXT_DECISION",
            extra_metadata=metadata,
        )
        event["delivery_mode"] = _classify_delivery_mode(
            event_type=str(event_type),
            extra=extra,
            decision_available=decision_available,
            previous_bridge_invocation_at=previous_invocation_ts,
            bridge_activated_at=activation_ts,
        )
        provenance = annotate_event_provenance(
            event,
            materialization_source="closed_bar_context_decision",
            max_age_seconds=max_age_seconds,
            materialized_timestamp=utc_now_iso(),
        )
        event.update(provenance)
        if (
            str(event_type or "").upper() in ENTRY_EVENT_TYPES
            and bool(event.get("context_event_price_missing"))
        ):
            result.skipped.append(
                {
                    "reason": "MISSING_CONTEXT_OCCURRENCE_PRICE",
                    "context_event_price_source": event.get("context_event_price_source"),
                    "timeframe": tf,
                    "source_bar_timestamp": _iso(source_bar_ts),
                    "context_event_id": event.get("context_event_id"),
                    "note": "provenance_only_not_live_execution_blocker",
                }
            )
        elif (
            str(event_type or "").upper() in ENTRY_EVENT_TYPES
            and provenance.get("freshness_status") != FRESHNESS_FRESH
        ):
            result.skipped.append(
                {
                    "reason": "NON_EXECUTABLE_CONTEXT_EVENT",
                    "freshness_status": provenance.get("freshness_status"),
                    "event_age_seconds": provenance.get("event_age_seconds"),
                    "timeframe": tf,
                    "source_bar_timestamp": _iso(source_bar_ts),
                    "context_event_id": event.get("context_event_id"),
                }
            )
        if is_recovery_delivery:
            result.recovery["transitions_reconstructed"] += 1
            result.recovery["last_recovered_source_decision_id"] = _clean(row.get("decision_id")) or None
            result.recovery["last_run_result"] = "recovered"
        pending_events.append(event)
        state_key = _episode_entry_key(tf, str(episode_id))
        state = episode_states.setdefault(state_key, {"last_entry": None, "retry_emitted": False})
        if bool(event.get("stale_blocked_entry_retry")):
            state["retry_emitted"] = True
        if str(event_type or "").upper() in ENTRY_EVENT_TYPES:
            state["last_entry"] = event

        # Keep only batch-local OPEN/CLOSED state coherent. Do NOT mutate the
        # persistent traded-episode set here: lifecycle episode identifiers are
        # not globally unique across timeframes.
        if event_type in {"CONTEXT_START", "CONTEXT_FLIP"}:
            if event.get("execution_eligible") is not False:
                open_tfs.add(tf)
        elif event_type == "CONTEXT_END":
            open_tfs.discard(tf)

    entry_event_count = sum(
        1
        for event in pending_events
        if str(event.get("event_type") or "").upper() in ENTRY_EVENT_TYPES
    )
    if entry_event_count > 1:
        for event in pending_events:
            if str(event.get("event_type") or "").upper() in ENTRY_EVENT_TYPES:
                event["materialization_batch_entry_count"] = entry_event_count

    for event in pending_events:
        if journal.append(event):
            result.emitted.append(event)
        else:
            result.duplicate_events += 1
            result.recovery["duplicates_skipped"] += 1

    if result.recovery["last_run_result"] == "idle" and ordered:
        result.recovery["last_run_result"] = "scanned_no_recovery_needed"

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
        self.context_event_max_age_seconds = _load_context_event_max_age_seconds(self.repo_root)
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
            if ep and str(row.get("exit_reason") or "").upper().startswith("CONTEXT_END"):
                traded.add(ep)
        open_tfs = {
            _timeframe(row.get("timeframe"))
            for row in latest.values()
            if _clean(row.get("status")).upper() == "OPEN"
        }
        for row in self._jsonl_rows(root / "trades.jsonl"):
            ep = _clean(row.get("lifecycle_episode_id"))
            if ep and str(row.get("exit_reason") or "").upper().startswith("CONTEXT_END"):
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
        recovery_watermarks = load_per_tf_recovery_watermarks(self.context_journal.path)
        rows = _candidate_decision_rows(frame, recovery_watermarks)
        epoch_id = str(epoch["paper_epoch_id"])
        open_tfs, traded = self._open_timeframes_and_traded_episodes(epoch_id)
        self.last_result = materialize_closed_bar_events(
            rows,
            journal=self.context_journal,
            provider_id=self.provider_id,
            epoch_id=epoch_id,
            current_bbo=current_bbo,
            bridge_activated_at=self.bridge_activated_at,
            previous_bridge_invocation_at=self.last_run_at,
            recovery_watermarks=recovery_watermarks,
            active_positions_by_timeframe=open_tfs,
            traded_episodes=traded,
            context_event_max_age_seconds=self.context_event_max_age_seconds,
        )
        self.last_run_at = utc_now_iso()
        return self.last_result
