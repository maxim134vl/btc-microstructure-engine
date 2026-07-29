"""Research pipeline aggregators — decision layer, ML governance, validation memories."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import (
    CANONICAL_PIPELINE,
    EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,
    MODEL_DRIFT_MAX_AGE_HOURS,
    MODEL_ECONOMIC_MAX_AGE_HOURS,
    MODEL_GOVERNANCE_MAX_AGE_HOURS,
    MODEL_TOXIC_MAX_AGE_HOURS,
    MODEL_VALIDATION_MAX_AGE_HOURS,
    REPO_ROOT,
)
from app.services.dashboard_paths import resolve_dashboard_read
from app.services.model_summary_freshness import (
    STATUS_CURRENT,
    STATUS_MISSING,
    STATUS_STALE_DRIFT,
    STATUS_STALE_GOVERNANCE,
    STATUS_STALE_VALIDATION,
    apply_stale_block,
    apply_stale_governance,
    build_freshness,
    build_model_summary_with_freshness,
    resolve_existing_path,
)
from app.services.model_summary_sources import (
    STATUS_GOVERNANCE_MISSING,
    STATUS_LEGACY_ONLY,
    STATUS_MISSING_DATA,
    build_model_summary_sources,
    drift_fields_from_diagnostics,
    resolve_toxic_monitoring_sources,
)
from app.services.monitoring_kpis import (
    decision_level_and_label,
    drift_composite_level,
    governance_age_days,
    toxic_routing_is_bulk_backfill,
    toxic_severity_level,
)
from app.services.parquet_service import df_records, latest_row, read_parquet

ECONOMIC_ROLLING_WINDOW = 5000
SHADOW_MACRO_F1_PASS_THRESHOLD = 0.50

WIN_OUTCOMES = frozenset({"ECONOMIC_WIN", "ECONOMIC_WEAK_WIN"})
NEUTRAL_OUTCOMES = frozenset({"ECONOMIC_NEUTRAL"})
LOSS_OUTCOMES = frozenset({"ECONOMIC_LOSS", "ECONOMIC_SEVERE_LOSS"})

WATCH_TRADING_STATES = frozenset({"REVERSAL_WATCH", "OBSERVE"})


def _level_from_flags(*, missing: bool = False, stale: bool = False, warning: bool = False) -> str:
    if missing:
        return "RED"
    if stale or warning:
        return "YELLOW"
    return "GREEN"


def _psi_level(psi: float | None) -> str:
    if psi is None:
        return "GREY"
    if psi < 0.10:
        return "GREEN"
    if psi <= 0.25:
        return "YELLOW"
    return "RED"


def _to_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return bool(value)


def _format_pct(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(100.0 * count / total, 1)


def _outcome_bucket(outcome: str) -> str | None:
    if outcome in WIN_OUTCOMES:
        return "WIN"
    if outcome in NEUTRAL_OUTCOMES:
        return "NEUTRAL"
    if outcome in LOSS_OUTCOMES:
        return "LOSS"
    return None


def _decision_level(
    *,
    entry_eligible: bool | None,
    trading_state: str | None,
    execution_posture: str | None = None,
    missing: bool = False,
) -> str:
    level, _ = decision_level_and_label(
        entry_eligible=entry_eligible,
        trading_state=trading_state,
        execution_posture=execution_posture,
        missing=missing,
    )
    return level


def _decision_status_label(
    *,
    entry_eligible: bool | None,
    trading_state: str | None,
    execution_posture: str | None = None,
    missing: bool = False,
) -> str:
    _, label = decision_level_and_label(
        entry_eligible=entry_eligible,
        trading_state=trading_state,
        execution_posture=execution_posture,
        missing=missing,
    )
    return label


DECISION_SOURCE_FRESH_LAG_SECONDS = 30 * 60
LIVE1A_MAX_AGE_SECONDS = 120.0
LIVE1A_SOURCE_NAME = "LIVE1A_INTRABAR_CONTEXT"
LIVE1A_HEALTH_REL = Path("data") / "runtime" / "intrabar_cognition_health.json"
LIVE1B_HEALTH_REL = Path("data") / "runtime" / "intrabar_paper_health.json"
LIVE1A_CONTEXT_JOURNAL_REL = Path("data") / "cognition" / "intrabar_context_events" / "events.jsonl"
LIVE1A_TIMEFRAME_ORDER = ("M15", "M30", "H1", "H4")
DIRECTIONAL_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})
DIRECTIONAL_PAPER_ACTIONS = frozenset({"INTENT_OPEN_LONG", "INTENT_OPEN_SHORT"})
_OBSERVE_LIKE = frozenset({"", "OBSERVE", "STAND_ASIDE", "NONE", "NO_ACTIVE_CONTEXT", "NULL"})


def _clean_token(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null", "—", "-"}:
        return None
    return text


def _parse_utc_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def _format_utc_timestamp(value: pd.Timestamp | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _row_timestamp(row: dict[str, Any], keys: tuple[str, ...]) -> pd.Timestamp | None:
    for key in keys:
        ts = _parse_utc_timestamp(row.get(key))
        if ts is not None:
            return ts
    return None


def _source_lag_seconds(source_ts: pd.Timestamp | None, live_ts: pd.Timestamp | None) -> float | None:
    if source_ts is None or live_ts is None:
        return None
    return round(max((live_ts - source_ts).total_seconds(), 0.0), 3)


def _source_freshness(
    *,
    source_name: str,
    source_ts: pd.Timestamp | None,
    live_ts: pd.Timestamp | None,
) -> dict[str, Any]:
    lag = _source_lag_seconds(source_ts, live_ts)
    stale = source_ts is None or (lag is not None and lag > DECISION_SOURCE_FRESH_LAG_SECONDS)
    warning = None
    if stale:
        if lag is None:
            warning = f"Decision source {source_name} has no usable timestamp."
        else:
            warning = (
                f"Decision source {source_name} is stale: "
                f"{int(lag)}s behind latest live_market_feed.parquet."
            )
    return {
        "source_name": source_name,
        "source_timestamp": _format_utc_timestamp(source_ts),
        "source_reference_timestamp": _format_utc_timestamp(live_ts),
        "source_lag_seconds": lag,
        "source_stale": stale,
        "freshness_warning": warning,
        "freshness": {
            "source_name": source_name,
            "source_timestamp": _format_utc_timestamp(source_ts),
            "reference_timestamp": _format_utc_timestamp(live_ts),
            "lag_seconds": lag,
            "max_lag_seconds": DECISION_SOURCE_FRESH_LAG_SECONDS,
            "is_stale": stale,
            "warning": warning,
        },
    }


def _context_status_label(row: dict[str, Any]) -> str | None:
    active_context = _clean_token(row.get("active_market_context"))
    candidate_context = _clean_token(row.get("candidate_context"))
    paper_action = _clean_token(row.get("paper_action_candidate"))
    lifecycle_state = _clean_token(row.get("lifecycle_state"))

    if active_context and active_context != "OBSERVE":
        return active_context
    if candidate_context in DIRECTIONAL_CONTEXTS:
        return candidate_context
    if paper_action in DIRECTIONAL_PAPER_ACTIONS:
        return paper_action
    return active_context or lifecycle_state


def _read_runtime_json(relative: Path) -> dict[str, Any] | None:
    path = Path(REPO_ROOT) / relative
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_live1a_intrabar_health() -> dict[str, Any] | None:
    """Canonical LIVE1A health for OPS Trading State (overrideable in tests)."""
    return _read_runtime_json(LIVE1A_HEALTH_REL)


def load_live1b_paper_health() -> dict[str, Any] | None:
    """Canonical LIVE1B paper health for matching decision/intent fields."""
    return _read_runtime_json(LIVE1B_HEALTH_REL)


def _map_live1a_context_fields(
    market_context: str | None,
    lifecycle_state: str | None,
) -> tuple[str, str, str]:
    """Legacy helper: map a single context token to trading/market/bias.

    Prefer :func:`_build_live1a_timeframe_trading_state` dual-context path.
    """
    mc = (market_context or "OBSERVE").strip().upper()
    life = (lifecycle_state or "").strip().upper()
    if life == "NO_ACTIVE_CONTEXT" or mc in _OBSERVE_LIKE:
        return "OBSERVE", "OBSERVE", "NONE"
    if mc in {"LONG", "LONG_CONTEXT"} or mc.startswith("LONG"):
        return "LONG_CONTEXT", "LONG_CONTEXT", "LONG"
    if mc in {"SHORT", "SHORT_CONTEXT"} or mc.startswith("SHORT"):
        return "SHORT_CONTEXT", "SHORT_CONTEXT", "SHORT"
    return "OBSERVE", "OBSERVE", "NONE"


def _normalize_context_token(value: Any) -> str | None:
    token = _clean_token(value)
    if token is None:
        return None
    upper = token.upper()
    if upper in _OBSERVE_LIKE:
        return None
    if upper in {"LONG", "LONG_CONTEXT"} or upper.startswith("LONG"):
        return "LONG_CONTEXT"
    if upper in {"SHORT", "SHORT_CONTEXT"} or upper.startswith("SHORT"):
        return "SHORT_CONTEXT"
    if upper in {"OBSERVE", "STAND_ASIDE"}:
        return None
    return upper


def _provisional_context_token(value: Any) -> str:
    token = _clean_token(value)
    if token is None:
        return "OBSERVE"
    upper = token.upper()
    if upper in {"LONG", "LONG_CONTEXT"} or upper.startswith("LONG"):
        return "LONG_CONTEXT"
    if upper in {"SHORT", "SHORT_CONTEXT"} or upper.startswith("SHORT"):
        return "SHORT_CONTEXT"
    if upper in {"STAND_ASIDE"}:
        return "STAND_ASIDE"
    return "OBSERVE"


def _bias_from_active(active: str | None) -> str:
    if active == "LONG_CONTEXT":
        return "LONG"
    if active == "SHORT_CONTEXT":
        return "SHORT"
    return "NONE"


def _open_context_lineage_from_journal(timeframe: str) -> dict[str, Any] | None:
    """Last unfinished CONTEXT_START/FLIP for TF from durable LIVE1A journal."""
    path = Path(REPO_ROOT) / LIVE1A_CONTEXT_JOURNAL_REL
    if not path.exists():
        return None
    open_ev: dict[str, Any] | None = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            if str(raw.get("timeframe") or "").upper() != timeframe.upper():
                continue
            et = str(raw.get("event_type") or "").upper()
            if et in {"CONTEXT_START", "CONTEXT_FLIP"}:
                open_ev = raw
            elif et == "CONTEXT_END":
                open_ev = None
    except OSError:
        return None
    return open_ev


def _active_from_open_event(event: dict[str, Any] | None) -> str | None:
    if not isinstance(event, dict):
        return None
    return _normalize_context_token(
        event.get("new_context") or event.get("to_side") or event.get("direction")
    )


def _lineage_from_last_context_event(
    last_by_tf: dict[str, Any] | None,
    timeframe: str,
) -> dict[str, Any] | None:
    if not isinstance(last_by_tf, dict):
        return None
    row = last_by_tf.get(timeframe) or last_by_tf.get(timeframe.upper())
    if not isinstance(row, dict):
        # Flat legacy shape (single event).
        if str(last_by_tf.get("timeframe") or "").upper() == timeframe.upper():
            row = last_by_tf
        else:
            return None
    et = str(row.get("event_type") or "").upper()
    if et not in {"CONTEXT_START", "CONTEXT_FLIP"}:
        return None
    return row


def _resolve_active_context_lineage(
    *,
    timeframe: str,
    tip_row: dict[str, Any],
    active: str | None,
    last_context_event: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach unfinished START/FLIP lineage when active directional context exists."""
    empty = {
        "lifecycle_episode_id": None,
        "context_event_id": None,
        "context_started_at": None,
        "context_price": None,
    }
    if active not in DIRECTIONAL_CONTEXTS:
        return empty

    episode = _clean_token(tip_row.get("lifecycle_episode_id") or tip_row.get("episode_id"))
    event_id = _clean_token(tip_row.get("context_event_id") or tip_row.get("event_id"))
    started = _format_utc_timestamp(
        _parse_utc_timestamp(tip_row.get("context_started_at") or tip_row.get("active_context_started_at"))
    )
    price = None
    raw_price = tip_row.get("context_price") or tip_row.get("context_event_price")
    try:
        if raw_price is not None and str(raw_price).strip() != "":
            price = float(raw_price)
    except (TypeError, ValueError):
        price = None

    if not event_id or not episode or not started:
        last_ev = _lineage_from_last_context_event(last_context_event, timeframe)
        if last_ev is None:
            last_ev = _open_context_lineage_from_journal(timeframe)
        if isinstance(last_ev, dict):
            episode = episode or _clean_token(last_ev.get("lifecycle_episode_id"))
            event_id = event_id or _clean_token(last_ev.get("context_event_id"))
            started = started or _format_utc_timestamp(
                _parse_utc_timestamp(last_ev.get("event_timestamp") or last_ev.get("context_started_at"))
            )
            if price is None:
                try:
                    price = float(last_ev.get("context_event_price"))
                except (TypeError, ValueError):
                    price = None

    return {
        "lifecycle_episode_id": episode,
        "context_event_id": event_id,
        "context_started_at": started,
        "context_price": price,
    }


def _open_position_for_tf(paper: dict[str, Any] | None, timeframe: str) -> tuple[str | None, str | None]:
    if not isinstance(paper, dict):
        return None, None
    by_tf = paper.get("active_positions_by_timeframe")
    if isinstance(by_tf, dict):
        row = by_tf.get(timeframe) or by_tf.get(timeframe.upper())
        if isinstance(row, dict):
            return _clean_token(row.get("position_id")), _clean_token(row.get("side"))
    return None, None


def _live1b_candidate_for_timeframe(
    paper: dict[str, Any] | None,
    timeframe: str,
) -> dict[str, Any] | None:
    """Return LIVE1B decision/command for exactly one timeframe — never cross-TF."""
    if not paper:
        return None
    tf_key = timeframe.upper()
    by_tf = paper.get("decisions_by_timeframe") or paper.get("last_decision_by_timeframe")
    if isinstance(by_tf, dict):
        row = by_tf.get(timeframe) or by_tf.get(tf_key)
        if isinstance(row, dict):
            return row
    for key in ("last_decisions", "decisions", "recent_decisions"):
        rows = paper.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and str(row.get("timeframe") or "").upper() == tf_key:
                return row
    for key in ("last_decision", "last_command"):
        row = paper.get(key)
        if isinstance(row, dict) and str(row.get("timeframe") or "").upper() == tf_key:
            return row
    return None


def _live1b_decision_fields(
    paper: dict[str, Any] | None,
    *,
    timeframe: str,
    lifecycle_episode_id: str | None,
    context_event_id: str | None,
) -> tuple[bool, str, str | None]:
    """entry_eligible, intent/execution_posture, decision_reason from matching LIVE1B decision only."""
    candidate = _live1b_candidate_for_timeframe(paper, timeframe)
    if not isinstance(candidate, dict):
        return False, "NONE", None

    cand_tf = _clean_token(candidate.get("timeframe"))
    cand_episode = _clean_token(
        candidate.get("lifecycle_episode_id") or candidate.get("episode_id")
    )
    cand_event = _clean_token(
        candidate.get("context_event_id") or candidate.get("event_id")
    )
    paper_epoch = _clean_token(paper.get("paper_epoch_id")) if paper else None
    cand_epoch = _clean_token(candidate.get("paper_epoch_id"))

    if cand_tf and cand_tf.upper() != timeframe.upper():
        return False, "NONE", "TIMEFRAME_MISMATCH"
    if paper_epoch and cand_epoch and paper_epoch != cand_epoch:
        return False, "NONE", "PAPER_EPOCH_MISMATCH"
    if lifecycle_episode_id and cand_episode and cand_episode != lifecycle_episode_id:
        return False, "NONE", "EPISODE_MISMATCH"
    if context_event_id and cand_event and cand_event != context_event_id:
        return False, "NONE", "EVENT_MISMATCH"
    if lifecycle_episode_id and not cand_episode and not cand_event:
        return False, "NONE", None
    if context_event_id and not cand_event and not cand_episode:
        return False, "NONE", None

    intent = _clean_token(
        candidate.get("intent")
        or candidate.get("execution_posture")
        or candidate.get("paper_action_candidate")
    ) or "NONE"
    eligible = _to_bool(
        candidate.get("entry_eligible")
        if "entry_eligible" in candidate
        else candidate.get("action_allowed")
    )
    reason = _clean_token(
        candidate.get("decision_reason")
        or candidate.get("block_reason")
        or candidate.get("reason")
    )
    return bool(eligible) if eligible is not None else False, intent, reason


def _build_live1a_timeframe_trading_state(
    *,
    timeframe: str,
    evals: dict[str, Any],
    bars: dict[str, Any],
    paper: dict[str, Any] | None,
    updated_at: pd.Timestamp | None,
    stale: bool,
    age_s: float | None,
    last_context_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = evals.get(timeframe)
    if not isinstance(row, dict):
        return {
            "timeframe": timeframe,
            "provisional_market_context": "UNAVAILABLE",
            "active_market_context": None,
            "trading_state": "UNAVAILABLE",
            "market_state": "UNAVAILABLE",
            "directional_bias": "NONE",
            "lifecycle_state": "UNAVAILABLE",
            "lifecycle_episode_id": None,
            "context_event_id": None,
            "context_started_at": None,
            "context_price": None,
            "open_position_id": None,
            "open_position_side": None,
            "entry_eligible": False,
            "intent": "NONE",
            "decision_reason": "MISSING_LIVE1A_TIMEFRAME",
            "causal_cutoff_timestamp": None,
            "last_evaluated_at": _format_utc_timestamp(updated_at),
            "source": LIVE1A_SOURCE_NAME,
            "stale": True,
            "level": "RED",
        }

    bar = bars.get(timeframe) if isinstance(bars.get(timeframe), dict) else {}
    provisional = _provisional_context_token(
        row.get("provisional_market_context") or row.get("market_context")
    )
    active = _normalize_context_token(
        row.get("active_market_context") if "active_market_context" in row else row.get("active")
    )
    # Tip may still stamp OBSERVE into `active`; treat that as no active context.
    if active not in DIRECTIONAL_CONTEXTS:
        active = None

    # Recover unfinished directional context from tip last_event / durable journal.
    # LIVE1A process restart can reset in-memory lifecycle while journal START remains open.
    open_ev = None
    if active not in DIRECTIONAL_CONTEXTS:
        open_ev = _lineage_from_last_context_event(last_context_event, timeframe)
        if open_ev is None:
            open_ev = _open_context_lineage_from_journal(timeframe)
        recovered = _active_from_open_event(open_ev)
        if recovered in DIRECTIONAL_CONTEXTS:
            active = recovered

    raw_life = _clean_token(row.get("lifecycle_state") or row.get("lifecycle"))
    if active in DIRECTIONAL_CONTEXTS:
        lifecycle_state = raw_life or "ACTIVE"
        if lifecycle_state.upper() in _OBSERVE_LIKE:
            # Tip lost lifecycle after restart; unfinished START ⇒ still active.
            lifecycle_state = "ACTIVE"
    else:
        lifecycle_state = "NO_ACTIVE_CONTEXT"

    # CHALLENGED requires an active directional context.
    if str(lifecycle_state).upper() == "CHALLENGED" and active not in DIRECTIONAL_CONTEXTS:
        lifecycle_state = "NO_ACTIVE_CONTEXT"

    lineage = _resolve_active_context_lineage(
        timeframe=timeframe,
        tip_row=row,
        active=active,
        last_context_event=last_context_event,
    )
    lifecycle_episode_id = lineage["lifecycle_episode_id"]
    context_event_id = lineage["context_event_id"]
    context_started_at = lineage["context_started_at"]
    context_price = lineage["context_price"]

    bias = _bias_from_active(active)
    # Compat trading_state: active directional context wins over provisional OBSERVE.
    trading_state = active if active in DIRECTIONAL_CONTEXTS else provisional
    market_state = provisional

    causal_cutoff = _format_utc_timestamp(
        _parse_utc_timestamp(bar.get("causal_cutoff_timestamp") or row.get("causal_cutoff_timestamp"))
    ) or _format_utc_timestamp(updated_at)
    last_evaluated_at = _format_utc_timestamp(
        _parse_utc_timestamp(row.get("last_evaluated_at") or row.get("evaluation_timestamp"))
    ) or _format_utc_timestamp(updated_at)

    open_position_id, open_position_side = _open_position_for_tf(paper, timeframe)

    entry_eligible, intent, decision_reason = _live1b_decision_fields(
        paper,
        timeframe=timeframe,
        lifecycle_episode_id=lifecycle_episode_id,
        context_event_id=context_event_id,
    )
    # New entries require a directional provisional evaluation; CHALLENGED blocks new entry.
    if provisional not in DIRECTIONAL_CONTEXTS or str(lifecycle_state).upper() == "CHALLENGED":
        entry_eligible = False
        if provisional not in DIRECTIONAL_CONTEXTS:
            intent = "NONE"

    if stale:
        level = "YELLOW"
    elif active in DIRECTIONAL_CONTEXTS:
        level = "GREEN"
    else:
        level = "GREY"

    return {
        "timeframe": timeframe,
        "provisional_market_context": provisional,
        "active_market_context": active,
        "trading_state": trading_state,
        "market_state": market_state,
        "directional_bias": bias,
        "lifecycle_state": lifecycle_state,
        "lifecycle_episode_id": lifecycle_episode_id,
        "context_event_id": context_event_id,
        "context_started_at": context_started_at,
        "context_price": context_price,
        "open_position_id": open_position_id,
        "open_position_side": open_position_side,
        "entry_eligible": entry_eligible,
        "intent": intent,
        "decision_reason": decision_reason,
        "causal_cutoff_timestamp": causal_cutoff,
        "last_evaluated_at": last_evaluated_at,
        "source": LIVE1A_SOURCE_NAME,
        "stale": stale,
        "source_lag_seconds": age_s,
        "level": level,
    }


def build_live1a_decision_layer_payload(
    cog: dict[str, Any] | None,
    paper: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Build Trading State from LIVE1A provisional/lifecycle for all M15/M30/H1/H4."""
    if not isinstance(cog, dict):
        return None
    evals = cog.get("last_provisional_eval")
    if not isinstance(evals, dict) or not evals:
        return None

    now_utc = pd.Timestamp(now or datetime.now(timezone.utc))
    if now_utc.tzinfo is None:
        now_utc = now_utc.tz_localize("UTC")
    else:
        now_utc = now_utc.tz_convert("UTC")
    updated_at = _parse_utc_timestamp(cog.get("updated_at"))
    age_s = None if updated_at is None else max((now_utc - updated_at).total_seconds(), 0.0)
    stale = updated_at is None or (age_s is not None and age_s > LIVE1A_MAX_AGE_SECONDS)

    bars = cog.get("partial_bars") if isinstance(cog.get("partial_bars"), dict) else {}
    last_context_event = cog.get("last_context_event") if isinstance(cog.get("last_context_event"), dict) else {}
    timeframes: dict[str, Any] = {}
    for tf in LIVE1A_TIMEFRAME_ORDER:
        timeframes[tf] = _build_live1a_timeframe_trading_state(
            timeframe=tf,
            evals=evals,
            bars=bars,
            paper=paper,
            updated_at=updated_at,
            stale=stale,
            age_s=age_s,
            last_context_event=last_context_event,
        )

    active_directional_count = sum(
        1 for row in timeframes.values() if row.get("active_market_context") in DIRECTIONAL_CONTEXTS
    )
    current_directional_eval_count = sum(
        1
        for row in timeframes.values()
        if row.get("provisional_market_context") in DIRECTIONAL_CONTEXTS
    )
    # Compat: directional_timeframes tracks active contexts (not provisional OBSERVE).
    directional_count = active_directional_count
    # Ribbon/summary still needs one status_label — prefer first active directional TF, else M15.
    primary_tf = next(
        (
            tf
            for tf in LIVE1A_TIMEFRAME_ORDER
            if timeframes[tf].get("active_market_context") in DIRECTIONAL_CONTEXTS
        ),
        "M15",
    )
    primary = timeframes.get(primary_tf) or timeframes["M15"]
    trading_state = primary.get("trading_state")
    market_state = primary.get("market_state")
    bias = primary.get("directional_bias")
    lifecycle_state = primary.get("lifecycle_state")
    entry_eligible = bool(primary.get("entry_eligible"))
    intent = primary.get("intent") or "NONE"
    source_ts = _parse_utc_timestamp(primary.get("causal_cutoff_timestamp")) or updated_at

    level = "GREY" if stale else ("GREEN" if entry_eligible else "YELLOW")
    status_label = "STALE_LIVE1A" if stale else str(trading_state)

    trading_states = {
        "source": LIVE1A_SOURCE_NAME,
        "directional_timeframes": directional_count,
        "active_directional_contexts": active_directional_count,
        "current_directional_evaluations": current_directional_eval_count,
        "total_timeframes": len(LIVE1A_TIMEFRAME_ORDER),
        "timeframes": timeframes,
    }

    return {
        "level": level,
        "status_label": status_label,
        "market_state": market_state,
        "market_bias": bias,
        "rule_id": None,
        "market_state_confidence": None,
        "trend_confidence": None,
        # Scalar retained for ribbon/backward compat; UI cards use trading_states.timeframes.
        "trading_state": trading_state,
        "trading_states": trading_states,
        "confidence_band": lifecycle_state,
        "entry_eligible": entry_eligible,
        "execution_posture": intent,
        "snapshot_id": _clean_token(cog.get("pid")) or "live1a",
        "timestamp": _format_utc_timestamp(source_ts),
        "active_market_context": trading_state,
        "lifecycle_state": lifecycle_state,
        "candidate_context": None,
        "paper_action_candidate": intent,
        "intended_side": bias,
        "timeframe": None,  # no single primary display TF
        "lifecycle_episode_id": primary.get("lifecycle_episode_id"),
        "context_event_id": primary.get("context_event_id"),
        "context_started_at": primary.get("context_started_at"),
        "causal_cutoff_timestamp": primary.get("causal_cutoff_timestamp"),
        "context_source_timestamp": _format_utc_timestamp(source_ts),
        "decision_reason": primary.get("decision_reason"),
        "source": LIVE1A_SOURCE_NAME,
        "source_name": LIVE1A_SOURCE_NAME,
        "source_timestamp": _format_utc_timestamp(source_ts),
        "source_reference_timestamp": _format_utc_timestamp(updated_at),
        "source_lag_seconds": age_s,
        "source_stale": stale,
        "stale": stale,
        "freshness_warning": (
            f"LIVE1A health is stale: {int(age_s)}s since updated_at."
            if stale and age_s is not None
            else ("LIVE1A health has no usable updated_at." if stale else None)
        ),
        "freshness": {
            "source_name": LIVE1A_SOURCE_NAME,
            "source_timestamp": _format_utc_timestamp(source_ts),
            "reference_timestamp": _format_utc_timestamp(updated_at),
            "lag_seconds": age_s,
            "max_lag_seconds": LIVE1A_MAX_AGE_SECONDS,
            "is_stale": stale,
            "warning": (
                f"LIVE1A health is stale: {int(age_s)}s since updated_at."
                if stale and age_s is not None
                else None
            ),
        },
        "rows": {
            "live1a_intrabar_cognition_health": 1,
            "live1b_intrabar_paper_health": 1 if paper else 0,
        },
        "by_timeframe": timeframes,
    }


def _build_context_decision_payload(
    *,
    source_name: str,
    row: dict[str, Any],
    source_ts: pd.Timestamp | None,
    live_ts: pd.Timestamp | None,
    rows: dict[str, int],
    probabilistic_latest: dict[str, Any],
) -> dict[str, Any]:
    label = _context_status_label(row)
    missing = label is None
    entry_eligible = _to_bool(
        row.get("paper_loop_allowed")
        if "paper_loop_allowed" in row
        else row.get("paper_signal_write_allowed")
        if "paper_signal_write_allowed" in row
        else row.get("action_allowed")
    )
    source = _source_freshness(source_name=source_name, source_ts=source_ts, live_ts=live_ts)
    level = "GREY" if missing else ("GREEN" if entry_eligible is True else "YELLOW")

    payload = {
        "level": level,
        "status_label": label or "UNAVAILABLE",
        "market_state": _clean_token(row.get("raw_market_context")) or _clean_token(row.get("active_market_context")),
        "market_bias": _clean_token(row.get("intended_side")),
        "rule_id": _clean_token(row.get("edge_signal_rule")),
        "market_state_confidence": _to_float(row.get("confidence")),
        "trend_confidence": _to_float(probabilistic_latest.get("trend_confidence")),
        "trading_state": label,
        "confidence_band": _clean_token(row.get("lifecycle_state")),
        "entry_eligible": entry_eligible,
        "execution_posture": _clean_token(row.get("paper_action_candidate")) or _clean_token(row.get("action_reason")),
        "snapshot_id": _clean_token(row.get("decision_id")),
        "timestamp": _format_utc_timestamp(source_ts),
        "active_market_context": _clean_token(row.get("active_market_context")),
        "lifecycle_state": _clean_token(row.get("lifecycle_state")),
        "candidate_context": _clean_token(row.get("candidate_context")),
        "paper_action_candidate": _clean_token(row.get("paper_action_candidate")),
        "intended_side": _clean_token(row.get("intended_side")),
        "rows": rows,
    }
    payload.update(source)
    return payload


def _build_legacy_decision_payload(
    *,
    market_latest: dict[str, Any],
    trading_latest: dict[str, Any],
    snapshot_latest: dict[str, Any],
    probabilistic_latest: dict[str, Any],
    live_ts: pd.Timestamp | None,
    rows: dict[str, int],
    missing: bool,
) -> dict[str, Any]:
    trading_state = trading_latest.get("trading_state") or snapshot_latest.get("trading_state")
    market_state = market_latest.get("market_state") or trading_latest.get("market_state") or snapshot_latest.get("market_state")
    rule_id = market_latest.get("rule_id") or snapshot_latest.get("rule_id")
    market_state_confidence = _to_float(
        market_latest.get("market_state_confidence")
        or trading_latest.get("market_state_confidence")
        or snapshot_latest.get("market_state_confidence")
    )
    trend_confidence = _to_float(probabilistic_latest.get("trend_confidence"))
    entry_eligible = _to_bool(trading_latest.get("entry_eligible") if "entry_eligible" in trading_latest else snapshot_latest.get("entry_eligible"))
    execution_posture = trading_latest.get("execution_posture") or snapshot_latest.get("execution_posture")

    if trading_latest:
        source_name = "trading_state_memory.parquet"
        source_ts = _row_timestamp(trading_latest, ("timestamp",))
    elif snapshot_latest:
        source_name = "trading_state_feature_snapshots.parquet"
        source_ts = _row_timestamp(snapshot_latest, ("timestamp",))
    elif market_latest:
        source_name = "market_state_memory.parquet"
        source_ts = _row_timestamp(market_latest, ("timestamp",))
    else:
        source_name = "decision_layer"
        source_ts = None

    source = _source_freshness(source_name=source_name, source_ts=source_ts, live_ts=live_ts)
    source_stale = bool(source.get("source_stale"))
    level = _decision_level(
        entry_eligible=entry_eligible,
        trading_state=trading_state,
        execution_posture=str(execution_posture) if execution_posture is not None else None,
        missing=missing,
    )
    status_label = _decision_status_label(
        entry_eligible=entry_eligible,
        trading_state=trading_state,
        execution_posture=str(execution_posture) if execution_posture is not None else None,
        missing=missing,
    )
    if source_stale and not missing:
        level = "YELLOW"
        status_label = "STALE_DECISION"

    payload = {
        "level": level,
        "status_label": status_label,
        "market_state": market_state,
        "market_bias": market_latest.get("market_bias") or snapshot_latest.get("market_bias"),
        "rule_id": rule_id,
        "market_state_confidence": market_state_confidence,
        "trend_confidence": trend_confidence,
        "trading_state": None if source_stale and not missing else trading_state,
        "stale_trading_state": trading_state if source_stale and not missing else None,
        "confidence_band": trading_latest.get("confidence_band") or snapshot_latest.get("confidence_band"),
        "entry_eligible": entry_eligible,
        "execution_posture": trading_latest.get("execution_posture") or snapshot_latest.get("execution_posture"),
        "snapshot_id": snapshot_latest.get("snapshot_id"),
        "timestamp": _format_utc_timestamp(source_ts),
        "rows": rows,
    }
    payload.update(source)
    return payload


def _derive_governance_status(
    *,
    active_model: str | None,
    candidate_model: str | None,
    promotion_eligible: bool,
    rollback_warning: bool,
    psi: float | None,
    rollback_reasons: Any,
    macro_f1: float | None = None,
    loss_recall: float | None = None,
) -> tuple[str, str]:
    reasons_text = ""
    if isinstance(rollback_reasons, list):
        reasons_text = " ".join(str(r) for r in rollback_reasons).upper()
    elif rollback_reasons:
        reasons_text = str(rollback_reasons).upper()

    drift_level, _ = drift_composite_level(
        psi=psi,
        macro_f1=macro_f1,
        loss_recall=loss_recall,
    )
    psi_drift = (psi or 0.0) > 0.25 or "PSI" in reasons_text

    if promotion_eligible:
        return "PROMOTION_ELIGIBLE", "GREEN"
    if drift_level == "RED" or (rollback_warning and psi_drift and drift_level != "YELLOW"):
        return "DRIFT_WARNING", drift_level if drift_level in ("RED", "YELLOW") else "RED"
    if drift_level == "YELLOW" or rollback_warning:
        return "DRIFT_WARNING", "YELLOW"
    if rollback_warning:
        return "REVIEW_REQUIRED", "YELLOW"
    if candidate_model and candidate_model != active_model:
        return "CANDIDATE", "YELLOW"
    return "ACTIVE", "GREEN"


def _repo_path(relative: str) -> str:
    return os.path.join(str(REPO_ROOT), relative)


def _cycle_durations(records: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    step_count = len(CANONICAL_PIPELINE)
    if not records:
        return None, None

    last_records = records[-step_count:]
    last_durations = [_to_float(row.get("duration")) for row in last_records]
    last_durations = [value for value in last_durations if value is not None]
    last_cycle_duration = round(sum(last_durations), 2) if last_durations else None

    recent_records = records[-step_count * 3 :]
    all_durations = [_to_float(row.get("duration")) for row in recent_records]
    all_durations = [value for value in all_durations if value is not None]
    avg_cycle_duration = round(sum(all_durations) / len(all_durations), 2) if all_durations else None
    return last_cycle_duration, avg_cycle_duration


async def build_pipeline_sync_status() -> dict[str, Any]:
    engine_state = await read_parquet("runtime_engine_state.parquet", tail=500)
    records = df_records(engine_state)
    last_cycle_duration, avg_cycle_duration = _cycle_durations(records)

    return {
        "step_count": len(CANONICAL_PIPELINE),
        "expected_step_count": EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,
        "in_sync": len(CANONICAL_PIPELINE) == EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,
        "engines": CANONICAL_PIPELINE,
        "last_cycle_duration_s": last_cycle_duration,
        "average_cycle_duration_s": avg_cycle_duration,
    }


async def build_decision_layer_snapshot() -> dict[str, Any]:
    # LIVE1A provisional/lifecycle is the only authoritative Trading State source.
    live1a_payload = build_live1a_decision_layer_payload(
        load_live1a_intrabar_health(),
        load_live1b_paper_health(),
    )
    if live1a_payload is not None:
        return live1a_payload

    live_feed = await read_parquet("live_market_feed.parquet", tail=1)
    decision_log = await read_parquet("context_decision_log.parquet", tail=1)
    lifecycle = await read_parquet("market_context_lifecycle_memory.parquet", tail=1)
    market = await read_parquet("market_state_memory.parquet", tail=1)
    trading = await read_parquet("trading_state_memory.parquet", tail=1)
    snapshots = await read_parquet("trading_state_feature_snapshots.parquet", tail=1)
    probabilistic = await read_parquet("probabilistic_auction_memory.parquet", tail=1)

    live_latest = latest_row(live_feed) or {}
    decision_latest = latest_row(decision_log) or {}
    lifecycle_latest = latest_row(lifecycle) or {}
    market_latest = latest_row(market) or {}
    trading_latest = latest_row(trading) or {}
    snapshot_latest = latest_row(snapshots) or {}
    probabilistic_latest = latest_row(probabilistic) or {}

    live_ts = _row_timestamp(live_latest, ("timestamp",))
    rows = {
        "live_market_feed": len(live_feed),
        "context_decision_log": len(decision_log),
        "market_context_lifecycle_memory": len(lifecycle),
        "market_state_memory": len(market),
        "trading_state_memory": len(trading),
        "feature_snapshots": len(snapshots),
    }

    decision_ts = _row_timestamp(decision_latest, ("candle_timestamp", "decision_written_at_utc"))
    decision_source = _source_freshness(
        source_name="context_decision_log.parquet",
        source_ts=decision_ts,
        live_ts=live_ts,
    )
    if decision_latest and not decision_source["source_stale"]:
        return _build_context_decision_payload(
            source_name="context_decision_log.parquet",
            row=decision_latest,
            source_ts=decision_ts,
            live_ts=live_ts,
            rows=rows,
            probabilistic_latest=probabilistic_latest,
        )

    lifecycle_ts = _row_timestamp(lifecycle_latest, ("timestamp",))
    lifecycle_source = _source_freshness(
        source_name="market_context_lifecycle_memory.parquet",
        source_ts=lifecycle_ts,
        live_ts=live_ts,
    )
    if lifecycle_latest and not lifecycle_source["source_stale"]:
        return _build_context_decision_payload(
            source_name="market_context_lifecycle_memory.parquet",
            row=lifecycle_latest,
            source_ts=lifecycle_ts,
            live_ts=live_ts,
            rows=rows,
            probabilistic_latest=probabilistic_latest,
        )

    missing = len(market) == 0 and len(trading) == 0 and len(snapshots) == 0
    return _build_legacy_decision_payload(
        market_latest=market_latest,
        trading_latest=trading_latest,
        snapshot_latest=snapshot_latest,
        probabilistic_latest=probabilistic_latest,
        live_ts=live_ts,
        rows=rows,
        missing=missing,
    )


async def build_drift_monitoring_snapshot(
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = sources or build_model_summary_sources()
    diagnostics = sources.get("_diagnostics") or {}
    legacy = sources.get("_legacy") or {}
    metrics = sources.get("metrics") or {}

    psi_m = metrics.get("psi") or {}
    macro_m = metrics.get("macro_f1") or {}
    loss_m = metrics.get("loss_recall") or {}

    psi = psi_m.get("value")
    macro_f1 = macro_m.get("value")
    loss_recall = loss_m.get("value")

    diag_fields = drift_fields_from_diagnostics(diagnostics)
    freshness = diagnostics.get("freshness") or build_freshness(
        source_path=diagnostics.get("source_path"),
        source_timestamp=diagnostics.get("generated_at"),
        max_age_hours=MODEL_DRIFT_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_DRIFT,
    )

    # Classic ML metrics absent from benchmark → MISSING_DATA (not June legacy as current).
    # Cognition/benchmark severity is informational only when classic drift metrics are missing;
    # missing PSI/F1 must not become SEVERE.
    has_classic = any(v is not None for v in (psi, macro_f1, loss_recall))
    if has_classic:
        level, severity_label = drift_composite_level(
            psi=psi,
            macro_f1=macro_f1,
            loss_recall=loss_recall,
            macro_f1_trend=None,
            loss_recall_trend=None,
        )
    elif diagnostics.get("payload") is not None:
        level, severity_label = "YELLOW", STATUS_MISSING
    else:
        # No fresh diagnostics — only then may legacy drive the block, marked legacy.
        legacy_row = legacy.get("row") or {}
        psi = _to_float(legacy_row.get("psi_label") if psi is None else psi)
        macro_f1 = _to_float(legacy_row.get("macro_f1") if macro_f1 is None else macro_f1)
        loss_recall = _to_float(legacy_row.get("loss_recall") if loss_recall is None else loss_recall)
        freshness = legacy.get("freshness") or build_freshness(
            source_path=legacy.get("source_path"),
            source_timestamp=legacy.get("timestamp"),
            max_age_hours=MODEL_DRIFT_MAX_AGE_HOURS,
            stale_status=STATUS_STALE_DRIFT,
        )
        if any(v is not None for v in (psi, macro_f1, loss_recall)):
            level, severity_label = drift_composite_level(
                psi=psi,
                macro_f1=macro_f1,
                loss_recall=loss_recall,
            )
        else:
            level, severity_label = "GREY", STATUS_MISSING

    if (
        freshness.get("is_stale")
        and severity_label not in {STATUS_MISSING, STATUS_STALE_DRIFT}
        and has_classic
    ):
        severity_label = f"{severity_label}+STALE"

    source_freshness = (
        STATUS_CURRENT
        if diagnostics.get("payload") is not None and not diagnostics.get("is_stale")
        else ("STALE" if diagnostics.get("is_stale") else (freshness.get("freshness_status") or STATUS_MISSING))
    )
    if has_classic:
        metric_availability = "AVAILABLE"
    elif diagnostics.get("payload") is not None:
        metric_availability = "LEGACY_ONLY" if psi_m.get("legacy_value") is not None else "MISSING_DATA"
    else:
        metric_availability = "LEGACY_ONLY" if legacy.get("row") else STATUS_MISSING

    payload = {
        "level": level,
        "severity_label": severity_label,
        "psi": psi,
        "psi_feature_max": None,
        "macro_f1": macro_f1,
        "loss_recall": loss_recall,
        "macro_f1_trend": None,
        "loss_recall_trend": None,
        "last_monitoring_at": diagnostics.get("generated_at") or legacy.get("timestamp"),
        "latest_diagnostics_at": diagnostics.get("generated_at"),
        "monitoring_rows": 0 if not legacy.get("row") else 1,
        "psi_meta": psi_m,
        "macro_f1_meta": macro_m,
        "loss_recall_meta": loss_m,
        "benchmark_drift_severity": diag_fields.get("benchmark_drift_severity"),
        "cognition_health": diag_fields.get("cognition_health"),
        "metric_source": diagnostics.get("source_path_display") or diagnostics.get("source_path"),
        "legacy_psi": (psi_m.get("legacy_value") if psi_m else None),
        "legacy_source_timestamp": (psi_m.get("legacy_source_timestamp") if psi_m else legacy.get("timestamp")),
        "legacy_is_stale": True if legacy.get("row") else None,
        "source_freshness": source_freshness,
        "metric_availability": metric_availability,
        "status_note": (
            "Current drift metrics are not present in benchmark_primary_v1."
            if not has_classic and diagnostics.get("payload") is not None
            else None
        ),
    }
    if not has_classic and diagnostics.get("payload") is not None:
        for key in ("psi_meta", "macro_f1_meta", "loss_recall_meta"):
            meta = payload.get(key) or {}
            if meta.get("value") is None:
                meta = {
                    **meta,
                    "status": STATUS_MISSING,
                    "metric_freshness": STATUS_MISSING,
                    "metric_is_legacy": False,
                }
                payload[key] = meta
    out = apply_stale_block(payload, freshness)
    if not has_classic and diagnostics.get("payload") is not None:
        out["severity_label"] = STATUS_MISSING
        out["level"] = "YELLOW"
        out["metrics_scope"] = "missing"
        out["stale_warning"] = None
        out["refresh_hint"] = None
    return out


async def build_model_governance_snapshot(
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = sources or build_model_summary_sources()
    gov_src = sources.get("_governance") or {}
    diagnostics = sources.get("_diagnostics") or {}
    legacy = sources.get("_legacy") or {}
    governance = gov_src.get("payload") or {}

    active_model = governance.get("active_model")
    candidate_model = governance.get("candidate_model")

    if gov_src.get("status") == STATUS_GOVERNANCE_MISSING or not gov_src.get("payload"):
        freshness = gov_src.get("freshness") or build_freshness(
            source_path=None,
            source_timestamp=None,
            max_age_hours=MODEL_GOVERNANCE_MAX_AGE_HOURS,
            missing_status=STATUS_MISSING,
        )
        payload = {
            "level": "YELLOW",
            "governance_status": STATUS_GOVERNANCE_MISSING,
            "active_model": None,
            "candidate_model": None,
            "active_model_display": "MISSING",
            "candidate_model_display": "MISSING",
            "shadow_model": None,
            "last_retrain_at": None,
            "last_validation_at": None,
            "governance_validation_at": None,
            "latest_diagnostics_at": diagnostics.get("generated_at"),
            "last_promotion_at": None,
            "active_model_registered_at": None,
            "active_model_age_days": None,
            "promotion_eligible": False,
            "promotion_eligible_label": "NO",
            "promotion_reasons": ["governance artifact missing"],
            "missing_reason": "governance artifact missing",
            "next_retrain_note": "Manual — scripts/retrain_models.py (weekly)",
            "shadow_macro_f1": None,
            "shadow_balanced_accuracy": None,
            "shadow_loss_recall": None,
            "shadow_rows": None,
            "rollback_warning": False,
            "rollback_reasons": None,
            "monitoring_rows": 0,
            "diagnostics_status": (sources.get("diagnostics_primary") or {}).get("freshness_status"),
        }
        out = apply_stale_governance(payload, freshness)
        out["governance_status"] = STATUS_GOVERNANCE_MISSING
        out["metrics_scope"] = "missing"
        out["stale_warning"] = "governance artifact missing"
        out["refresh_hint"] = (
            "Provide exports/model_governance_dashboard.json or run manual governance export."
        )
        out["action"] = out["refresh_hint"]
        return out

    shadow_metrics = governance.get("shadow_metrics_last_5000") or {}
    rollback_warning = bool(governance.get("rollback_warning"))
    promotion_eligible = bool(governance.get("promotion_eligible"))
    # Prefer governance JSON metrics; do not pull June legacy as current.
    metrics = sources.get("metrics") or {}
    psi = (metrics.get("psi") or {}).get("value")
    eval_macro_f1 = _to_float(shadow_metrics.get("macro_f1")) or (metrics.get("macro_f1") or {}).get("value")
    eval_loss_recall = _to_float(shadow_metrics.get("loss_recall")) or (metrics.get("loss_recall") or {}).get("value")

    governance_status, governance_level = _derive_governance_status(
        active_model=active_model,
        candidate_model=candidate_model,
        promotion_eligible=promotion_eligible,
        rollback_warning=rollback_warning,
        psi=psi,
        rollback_reasons=governance.get("rollback_reasons"),
        macro_f1=eval_macro_f1,
        loss_recall=eval_loss_recall,
    )

    registry_path = resolve_existing_path(_repo_path("model_registry.json"))
    active_registered_at = None
    if registry_path:
        with open(registry_path, encoding="utf-8") as handle:
            registry = json.load(handle)
            for model in registry.get("models", []):
                if model.get("id") == active_model:
                    active_registered_at = model.get("registered_at")
                    break

    active_since = governance.get("last_retrain_at") or active_registered_at
    active_model_age_days = governance_age_days(active_since)
    last_validation_at = governance.get("last_validation_at")

    freshness = gov_src.get("freshness") or build_freshness(
        source_path=gov_src.get("source_path"),
        source_timestamp=last_validation_at,
        max_age_hours=MODEL_GOVERNANCE_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_GOVERNANCE,
    )

    payload = {
        "level": governance_level,
        "governance_status": governance_status,
        "active_model": active_model,
        "candidate_model": candidate_model,
        "shadow_model": governance.get("shadow_model"),
        "last_retrain_at": governance.get("last_retrain_at"),
        "last_validation_at": last_validation_at,
        "governance_validation_at": last_validation_at,
        "latest_diagnostics_at": diagnostics.get("generated_at"),
        "last_promotion_at": governance.get("last_promotion_at"),
        "active_model_registered_at": active_registered_at,
        "active_model_age_days": active_model_age_days,
        "promotion_eligible_label": "YES" if promotion_eligible else "NO",
        "next_retrain_note": "Manual — scripts/retrain_models.py (weekly)",
        "active_metrics": governance.get("active_metrics"),
        "candidate_metrics": governance.get("candidate_metrics"),
        "candidate_comparison": governance.get("candidate_comparison"),
        "shadow_macro_f1": _to_float(shadow_metrics.get("macro_f1")),
        "shadow_balanced_accuracy": _to_float(shadow_metrics.get("balanced_accuracy")),
        "shadow_loss_recall": _to_float(shadow_metrics.get("loss_recall")),
        "shadow_rows": shadow_metrics.get("rows"),
        "rollback_warning": rollback_warning,
        "rollback_reasons": governance.get("rollback_reasons"),
        "promotion_eligible": promotion_eligible,
        "promotion_reasons": governance.get("promotion_reasons"),
        "monitoring_rows": 1 if legacy.get("row") else 0,
        "diagnostics_status": (sources.get("diagnostics_primary") or {}).get("freshness_status"),
        "missing_reason": None,
    }
    return apply_stale_governance(payload, freshness)


async def build_economic_validation_snapshot() -> dict[str, Any]:
    economic = await read_parquet(
        "economic_validation_memory.parquet",
        tail=ECONOMIC_ROLLING_WINDOW + 5000,
    )
    validation = await read_parquet("trading_state_validation_memory.parquet", tail=5000)

    if len(economic) == 0:
        economic_path = resolve_existing_path(resolve_dashboard_read("economic_validation_memory.parquet"))
        freshness = build_freshness(
            source_path=economic_path,
            source_timestamp=None,
            max_age_hours=MODEL_ECONOMIC_MAX_AGE_HOURS,
            stale_status=STATUS_STALE_VALIDATION,
        )
        return apply_stale_block(
            {
                "level": "GREY",
                "status": "NOT_EVALUATED",
                "rows": 0,
                "complete_h4h": 0,
                "pending_h4h": 0,
                "rolling_window": ECONOMIC_ROLLING_WINDOW,
                "win_pct": None,
                "neutral_pct": None,
                "loss_pct": None,
                "outcome_distribution": {},
                "source_path": economic_path,
                "missing_reason": "economic source missing" if economic_path is None else "economic data empty",
            },
            freshness,
            stale_status_field="status",
            stale_status_value=STATUS_MISSING if economic_path is None else (
                STATUS_STALE_VALIDATION if freshness.get("is_stale") else "NOT_EVALUATED"
            ),
        )

    frame = economic.copy()
    if "validation_horizon" in frame.columns:
        h4h = frame[frame["validation_horizon"] == "H4H"]
    else:
        h4h = frame

    if "validation_status" in h4h.columns:
        complete = h4h[h4h["validation_status"] == "COMPLETE"]
    else:
        complete = h4h

    rolling = complete.tail(ECONOMIC_ROLLING_WINDOW) if len(complete) else complete
    win_count = neutral_count = loss_count = 0
    if "economic_outcome" in rolling.columns and len(rolling):
        for outcome in rolling["economic_outcome"].astype(str):
            bucket = _outcome_bucket(outcome)
            if bucket == "WIN":
                win_count += 1
            elif bucket == "NEUTRAL":
                neutral_count += 1
            elif bucket == "LOSS":
                loss_count += 1

    rolling_total = win_count + neutral_count + loss_count
    pending = int(len(h4h) - len(complete)) if len(h4h) else 0
    if len(complete) == 0 and pending == 0:
        level = "GREY"
        status = "NOT_EVALUATED"
    else:
        level = _level_from_flags(missing=False, warning=pending > max(len(complete), 1) * 0.5)
        status = "EVALUATED"

    outcome_dist: dict[str, int] = {}
    if "economic_outcome" in complete.columns:
        outcome_dist = complete["economic_outcome"].value_counts().head(8).astype(int).to_dict()

    latest_completed_at = complete.iloc[-1].get("completed_at") if len(complete) else None
    if latest_completed_at is None or (isinstance(latest_completed_at, float) and pd.isna(latest_completed_at)):
        latest_completed_at = complete.iloc[-1].get("timestamp") if len(complete) else None
    if latest_completed_at is None or (isinstance(latest_completed_at, float) and pd.isna(latest_completed_at)):
        latest_completed_at = (
            economic.iloc[-1].get("lineage_propagation_timestamp")
            if len(economic) and "lineage_propagation_timestamp" in economic.columns
            else None
        )

    economic_path = resolve_existing_path(resolve_dashboard_read("economic_validation_memory.parquet"))
    freshness = build_freshness(
        source_path=economic_path,
        source_timestamp=latest_completed_at,
        max_age_hours=MODEL_ECONOMIC_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
    )
    payload = {
        "level": level,
        "status": status,
        "rows": int(len(economic)),
        "validation_rows": int(len(validation)),
        "complete_h4h": int(len(complete)),
        "pending_h4h": pending,
        "rolling_window": ECONOMIC_ROLLING_WINDOW,
        "rolling_complete_count": int(len(rolling)),
        "win_pct": _format_pct(win_count, rolling_total),
        "neutral_pct": _format_pct(neutral_count, rolling_total),
        "loss_pct": _format_pct(loss_count, rolling_total),
        "win_count": win_count,
        "neutral_count": neutral_count,
        "loss_count": loss_count,
        "outcome_distribution": outcome_dist,
        "latest_completed_at": latest_completed_at,
        "source_path": economic_path,
    }
    if freshness.get("is_stale"):
        payload["status"] = STATUS_STALE_VALIDATION
    return apply_stale_block(payload, freshness)


async def build_shadow_inference_snapshot(
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = sources or build_model_summary_sources()
    diagnostics = sources.get("_diagnostics") or {}
    gov_src = sources.get("_governance") or {}
    legacy = sources.get("_legacy") or {}
    metrics = sources.get("metrics") or {}
    governance = gov_src.get("payload") or {}

    shadow = await read_parquet("shadow_inference_memory.parquet", tail=10000)
    shadow_metrics = governance.get("shadow_metrics_last_5000") or {}

    macro_m = metrics.get("macro_f1") or {}
    bal_m = metrics.get("balanced_accuracy") or {}
    loss_m = metrics.get("loss_recall") or {}

    # Prefer governance JSON metrics, then fresh benchmark extraction — never June as current.
    macro_f1 = _to_float(shadow_metrics.get("macro_f1"))
    if macro_f1 is None:
        macro_f1 = macro_m.get("value")
    balanced_accuracy = _to_float(shadow_metrics.get("balanced_accuracy"))
    if balanced_accuracy is None:
        balanced_accuracy = bal_m.get("value")
    loss_recall = _to_float(shadow_metrics.get("loss_recall"))
    if loss_recall is None:
        loss_recall = loss_m.get("value")

    latest_diagnostics_at = diagnostics.get("generated_at")
    last_validation_time = governance.get("last_validation_at") or latest_diagnostics_at

    evaluated = (
        shadow[shadow["evaluation_status"] == "COMPLETE"]
        if "evaluation_status" in shadow.columns
        else shadow.iloc[0:0]
    )
    pred_dist: dict[str, int] = {}
    if "predicted_class" in evaluated.columns and len(evaluated):
        pred_dist = evaluated["predicted_class"].value_counts().astype(int).to_dict()

    evaluated_rows = int(shadow_metrics.get("rows") or len(evaluated))
    metric_is_legacy = False

    if macro_f1 is None and balanced_accuracy is None and loss_recall is None and not shadow_metrics:
        # Metrics missing from fresh sources — expose legacy separately only.
        legacy_row = legacy.get("row") or {}
        legacy_macro = _to_float(legacy_row.get("macro_f1"))
        freshness = diagnostics.get("freshness") or build_freshness(
            source_path=diagnostics.get("source_path"),
            source_timestamp=latest_diagnostics_at,
            max_age_hours=MODEL_VALIDATION_MAX_AGE_HOURS,
            stale_status=STATUS_STALE_VALIDATION,
        )
        validation_status = STATUS_MISSING if diagnostics.get("payload") is not None else "NOT_EVALUATED"
        if diagnostics.get("payload") is not None and not diagnostics.get("is_stale"):
            # Fresh diagnostics exist but classic shadow metrics are absent.
            level = "YELLOW"
            validation_status = STATUS_MISSING
        elif diagnostics.get("is_stale"):
            level = "YELLOW"
            validation_status = STATUS_STALE_VALIDATION
        else:
            level = "GREY"
        payload = {
            "level": level,
            "validation_status": validation_status,
            "rows": int(len(shadow)),
            "evaluated_rows": evaluated_rows,
            "pending_rows": int(len(shadow) - len(evaluated)) if len(shadow) else 0,
            "macro_f1": None,
            "balanced_accuracy": None,
            "loss_recall": None,
            "last_validation_time": last_validation_time,
            "latest_diagnostics_at": latest_diagnostics_at,
            "registry_id": shadow.iloc[-1].get("registry_id") if len(shadow) else None,
            "model_version": shadow.iloc[-1].get("model_version") if len(shadow) else None,
            "prediction_distribution": pred_dist,
            "latest_prediction_at": shadow.iloc[-1].get("prediction_timestamp") if len(shadow) else None,
            "metric_is_legacy": False,
            "legacy_macro_f1": legacy_macro,
            "legacy_source_timestamp": legacy.get("timestamp"),
            "legacy_is_stale": True if legacy_macro is not None else None,
            "macro_f1_meta": macro_m,
            "metric_source": diagnostics.get("source_path_display") or diagnostics.get("source_path"),
            "source_freshness": (
                STATUS_CURRENT
                if diagnostics.get("payload") is not None and not diagnostics.get("is_stale")
                else ("STALE" if diagnostics.get("is_stale") else STATUS_MISSING)
            ),
            "metric_availability": STATUS_MISSING,
            "status_note": "Classic shadow metrics are not present in current benchmark payload.",
        }
        out = apply_stale_block(payload, freshness)
        out["metrics_scope"] = "missing"
        out["stale_warning"] = None
        out["refresh_hint"] = None
        return out

    validation_status = "PASS" if macro_f1 is not None and macro_f1 >= SHADOW_MACRO_F1_PASS_THRESHOLD else "WARNING"
    level = "GREEN" if validation_status == "PASS" else "YELLOW"
    if macro_f1 is None and len(evaluated) == 0:
        level = "GREY"
        validation_status = "NOT_EVALUATED"

    freshness = diagnostics.get("freshness") or build_freshness(
        source_path=gov_src.get("source_path") or diagnostics.get("source_path"),
        source_timestamp=last_validation_time or latest_diagnostics_at,
        max_age_hours=MODEL_VALIDATION_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
    )
    # When diagnostics are current, shadow block freshness follows diagnostics — not June legacy.
    if diagnostics.get("payload") is not None and not diagnostics.get("is_stale"):
        freshness = diagnostics["freshness"]
        if validation_status not in {"PASS", "WARNING", "FAIL"}:
            validation_status = validation_status
    elif diagnostics.get("is_stale"):
        validation_status = STATUS_STALE_VALIDATION
        level = "YELLOW"

    payload = {
        "level": level,
        "validation_status": validation_status,
        "rows": int(len(shadow)),
        "evaluated_rows": evaluated_rows,
        "pending_rows": int(len(shadow) - len(evaluated)) if len(shadow) else 0,
        "macro_f1": macro_f1,
        "balanced_accuracy": balanced_accuracy,
        "loss_recall": loss_recall,
        "last_validation_time": last_validation_time,
        "latest_diagnostics_at": latest_diagnostics_at,
        "registry_id": shadow.iloc[-1].get("registry_id") if len(shadow) else None,
        "model_version": shadow.iloc[-1].get("model_version") if len(shadow) else None,
        "prediction_distribution": pred_dist,
        "latest_prediction_at": shadow.iloc[-1].get("prediction_timestamp") if len(shadow) else None,
        "metric_is_legacy": metric_is_legacy,
        "legacy_macro_f1": (macro_m.get("legacy_value") if macro_m else None),
        "legacy_source_timestamp": (macro_m.get("legacy_source_timestamp") if macro_m else legacy.get("timestamp")),
        "legacy_is_stale": True if legacy.get("row") else None,
        "macro_f1_meta": macro_m,
        "metric_source": diagnostics.get("source_path_display") or diagnostics.get("source_path"),
    }
    return apply_stale_block(payload, freshness)


async def build_toxic_box_snapshot(sources: dict[str, Any] | None = None) -> dict[str, Any]:
    sources = sources or build_model_summary_sources()
    diagnostics = sources.get("_diagnostics")
    toxic_path = resolve_existing_path(resolve_dashboard_read("toxic_box_memory.parquet"))
    toxic = await read_parquet("toxic_box_memory.parquet", tail=10000)

    def _attach_source_truth(
        payload: dict[str, Any],
        *,
        historical_available: bool,
        historical_ts: Any = None,
        historical_age_days: float | None = None,
    ) -> dict[str, Any]:
        truth = resolve_toxic_monitoring_sources(
            diagnostics=diagnostics,
            historical_source_path=toxic_path,
            historical_timestamp=historical_ts,
            historical_age_days=historical_age_days,
            historical_metrics_available=historical_available,
        )
        payload["current"] = truth["current"]
        payload["historical"] = truth["historical"]
        payload["display_status"] = truth["display_status"]
        payload["display_reason"] = truth["display_reason"]

        current = truth["current"]
        historical = truth["historical"]
        display_status = truth["display_status"]

        if display_status == STATUS_CURRENT and current.get("metrics_available"):
            metrics = current.get("metrics") or {}
            def _m(name: str) -> Any:
                entry = metrics.get(name) or {}
                return entry.get("value")

            if _m("events") is not None:
                payload["events"] = int(_m("events"))
            if _m("events_last_7d") is not None:
                payload["events_last_7d"] = int(_m("events_last_7d"))
            if _m("toxic_rate_7d") is not None:
                payload["toxic_rate_7d"] = float(_m("toxic_rate_7d"))
            if _m("toxic_rate_30d") is not None:
                payload["toxic_rate_30d"] = float(_m("toxic_rate_30d"))
            if _m("trend") is not None:
                payload["trend"] = str(_m("trend"))
            payload["source_path"] = current.get("source_path")
            payload["severity_label"] = STATUS_CURRENT
            payload["status"] = STATUS_CURRENT
            payload["metrics_scope"] = "current"
            payload["stale_warning"] = None
            payload["refresh_hint"] = None
            # Keep historical parquet path for UI "Historical source" line.
            payload["historical_source_path"] = historical.get("source_path")
            payload["historical_timestamp"] = historical.get("timestamp")
            payload["historical_age_days"] = historical.get("age_days")
        else:
            payload["severity_label"] = (
                f"{STATUS_LEGACY_ONLY} / STALE"
                if display_status == STATUS_LEGACY_ONLY
                else STATUS_MISSING_DATA
            )
            payload["status"] = display_status
            # Do not keep rate-based Elevated/Critical when only legacy baseline exists.
            payload["level"] = "GREY" if display_status == STATUS_LEGACY_ONLY else "GREY"
            payload["metrics_scope"] = "historical" if historical_available else "missing"
            payload["source_path"] = historical.get("source_path") or toxic_path
            payload["historical_source_path"] = historical.get("source_path") or toxic_path
            payload["historical_timestamp"] = historical.get("timestamp")
            payload["historical_age_days"] = historical.get("age_days")
            if display_status == STATUS_LEGACY_ONLY:
                payload["display_status"] = "HISTORICAL_ONLY"
                payload["severity_label"] = "HISTORICAL_ONLY / NON_BLOCKING"
                payload["stale_warning"] = (
                    "Current S4 trades are not classified by this legacy Toxic Box. "
                    "Zero recent events means that current monitoring is not connected, "
                    "not that current toxic activity equals zero."
                )
                payload["refresh_hint"] = (
                    "Future work: connect current context and trade outcome intelligence."
                )
        return payload

    if len(toxic) == 0 or toxic_path is None:
        freshness = build_freshness(
            source_path=toxic_path,
            source_timestamp=None,
            max_age_hours=MODEL_TOXIC_MAX_AGE_HOURS,
            stale_status=STATUS_STALE_VALIDATION,
            missing_status=STATUS_MISSING,
        )
        base = apply_stale_block(
            {
                "level": "GREY",
                "severity_label": STATUS_MISSING,
                "status": STATUS_MISSING,
                "rows": 0,
                "events": 0,
                "events_last_7d": 0,
                "toxic_rate_7d": 0.0,
                "trend": "STABLE",
                "type_distribution": {},
                "source_path": toxic_path,
                "missing_reason": "toxic source missing" if toxic_path is None else "toxic data empty",
            },
            freshness,
            stale_status_field="severity_label",
            stale_status_value=STATUS_MISSING,
        )
        return _attach_source_truth(base, historical_available=False)

    frame = toxic.copy()
    now = pd.Timestamp.now(tz=timezone.utc)

    prop_col = None
    for candidate in ("lineage_propagation_timestamp", "created_at", "timestamp"):
        if candidate in frame.columns:
            prop_col = candidate
            break
    if prop_col is None:
        prop_col = "timestamp" if "timestamp" in frame.columns else "created_at"

    frame["_routed_at"] = pd.to_datetime(frame[prop_col], utc=True, errors="coerce")
    t0_col = "timestamp" if "timestamp" in frame.columns else prop_col
    frame["_t0_at"] = pd.to_datetime(frame[t0_col], utc=True, errors="coerce")

    cutoff_7d = now - timedelta(days=7)
    cutoff_14d = now - timedelta(days=14)
    cutoff_30d = now - timedelta(days=30)

    bulk_backfill = toxic_routing_is_bulk_backfill(frame["_routed_at"].dropna().tolist())
    latest_routed = frame["_routed_at"].max()
    hours_since_last_routed = None
    if pd.notna(latest_routed):
        hours_since_last_routed = (now - latest_routed).total_seconds() / 3600.0

    if bulk_backfill and pd.notna(latest_routed):
        backfill_peak = latest_routed
        live_frame = frame[frame["_routed_at"] > backfill_peak + pd.Timedelta(seconds=1)]
    else:
        live_frame = frame

    recent_7d = live_frame[live_frame["_routed_at"] >= cutoff_7d]
    prior_7d = live_frame[(live_frame["_routed_at"] >= cutoff_14d) & (live_frame["_routed_at"] < cutoff_7d)]
    recent_30d = live_frame[live_frame["_routed_at"] >= cutoff_30d]

    events_last_7d = int(len(recent_7d))
    events_prior_7d = int(len(prior_7d))
    events_last_30d = int(len(recent_30d))
    toxic_rate_7d = round(events_last_7d / 7.0, 2)
    toxic_rate_30d = round(events_last_30d / 30.0, 2)

    t0_recent_7d = int((frame["_t0_at"] >= cutoff_7d).sum())
    t0_recent_30d = int((frame["_t0_at"] >= cutoff_30d).sum())

    if events_last_7d > events_prior_7d:
        trend = "UP"
    elif events_last_7d < events_prior_7d:
        trend = "DOWN"
    else:
        trend = "STABLE"

    type_dist: dict[str, int] = {}
    if "toxic_type" in frame.columns:
        type_dist = frame["toxic_type"].value_counts().head(8).astype(int).to_dict()

    level, severity_label = toxic_severity_level(
        events_last_7d=events_last_7d,
        events_last_30d=events_last_30d,
        trend=trend,
        hours_since_last_routed=hours_since_last_routed,
        is_bulk_backfill=bulk_backfill,
    )

    freshness_ts = latest_routed if pd.notna(latest_routed) else frame.iloc[-1].get(t0_col)
    freshness = build_freshness(
        source_path=toxic_path,
        source_timestamp=freshness_ts,
        max_age_hours=MODEL_TOXIC_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
    )
    payload = {
        "level": level,
        "severity_label": severity_label,
        "rows": int(len(frame)),
        "events": int(len(frame)),
        "events_last_7d": events_last_7d,
        "events_prior_7d": events_prior_7d,
        "events_last_30d": events_last_30d,
        "events_t0_last_7d": t0_recent_7d,
        "events_t0_last_30d": t0_recent_30d,
        "toxic_rate_7d": toxic_rate_7d,
        "toxic_rate_30d": toxic_rate_30d,
        "monitoring_mode": "bulk_backfill" if bulk_backfill else "live",
        "hours_since_last_routed": round(hours_since_last_routed, 1) if hours_since_last_routed is not None else None,
        "trend": trend,
        "type_distribution": type_dist,
        "latest_timestamp": frame.iloc[-1].get(t0_col) if len(frame) else None,
        "latest_routed_at": latest_routed.isoformat() if pd.notna(latest_routed) else None,
        "source_path": toxic_path,
    }
    out = apply_stale_block(payload, freshness)
    age_days = freshness.get("age_days")
    out = _attach_source_truth(
        out,
        historical_available=True,
        historical_ts=freshness_ts,
        historical_age_days=float(age_days) if age_days is not None else None,
    )
    return out


async def build_model_summary_snapshot(
    governance: dict[str, Any],
    drift: dict[str, Any],
    shadow: dict[str, Any],
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = sources or build_model_summary_sources()
    metrics = sources.get("metrics") or {}
    macro_f1 = (metrics.get("macro_f1") or {}).get("value")
    loss_recall = (metrics.get("loss_recall") or {}).get("value")
    psi = (metrics.get("psi") or {}).get("value")

    diagnostics_status = (sources.get("diagnostics_primary") or {}).get("freshness_status")
    gov_status = str(governance.get("governance_status") or STATUS_GOVERNANCE_MISSING)

    base = {
        "level": "YELLOW",
        "status": "ATTENTION",
        "model": governance.get("active_model"),
        "shadow_macro_f1": macro_f1,
        "loss_recall": loss_recall,
        "psi": psi,
        "governance_status": gov_status,
        "diagnostics_status": diagnostics_status,
    }
    return build_model_summary_with_freshness(
        governance=governance,
        drift=drift,
        shadow=shadow,
        base_summary=base,
        sources=sources,
    )


def _model_assurance_missing(*, reason: str) -> dict[str, Any]:
    return {
        "status": "MISSING_SOURCE",
        "overall_assurance_status": "MISSING_SOURCE",
        "runtime_safety_status": "UNKNOWN",
        "runtime_impact": "NON_BLOCKING",
        "promotion_control": "GOVERNANCE_GATE",
        "scope": "CURRENT_ACTIVE_MODEL_ONLY",
        "error_reason": reason,
        "missing_sources": ["latest_summary"],
        "stale_sources": [],
        "promotion_blockers": [],
        "environment_blockers": [],
        "current_blockers": [],
        "current_incidents": [],
        "current_toxic_events": [],
    }


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    """Coerce MODEL-9 payload values to JSON-serializable primitives."""
    if depth > 12:
        return None
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # NaN/Inf
            return None
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v, depth=depth + 1) for v in value]
    if isinstance(value, set):
        return sorted(_json_safe(v, depth=depth + 1) for v in value)
    # numpy / enum / unexpected objects
    try:
        import numpy as np  # type: ignore

        if isinstance(value, np.generic):
            py = value.item()
            return _json_safe(py, depth=depth + 1)
    except Exception:
        pass
    if hasattr(value, "value") and not isinstance(value, (bytes, bytearray)):
        try:
            return _json_safe(getattr(value, "value"), depth=depth + 1)
        except Exception:
            pass
    return str(value)


def load_model_assurance_payload() -> dict[str, Any]:
    """Read canonical MODEL-9 summary only — never raise into the OPS endpoint."""
    path = Path(REPO_ROOT) / "data" / "model_assurance" / "summary" / "latest_summary.json"
    try:
        if not path.exists():
            return _model_assurance_missing(reason="latest_summary.json not found")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _model_assurance_missing(reason="latest_summary.json is not an object")
        safe = _json_safe(payload)
        if not isinstance(safe, dict):
            return _model_assurance_missing(reason="latest_summary.json failed JSON sanitization")
        # Prove serializability before attaching to OPS response.
        json.dumps(safe, allow_nan=False)
        return safe
    except Exception as exc:
        return {
            **_model_assurance_missing(reason=f"{type(exc).__name__}: {exc}"),
            "status": "ERROR",
            "overall_assurance_status": "ERROR",
        }


async def build_research_pipeline_snapshot() -> dict[str, Any]:
    sources = build_model_summary_sources()
    pipeline = await build_pipeline_sync_status()
    decision = await build_decision_layer_snapshot()
    drift = await build_drift_monitoring_snapshot(sources)
    governance = await build_model_governance_snapshot(sources)
    economic = await build_economic_validation_snapshot()
    shadow = await build_shadow_inference_snapshot(sources)
    toxic = await build_toxic_box_snapshot(sources)
    model_summary = await build_model_summary_snapshot(governance, drift, shadow, sources)
    try:
        model_assurance = load_model_assurance_payload()
    except Exception as exc:
        model_assurance = {
            **_model_assurance_missing(reason=f"{type(exc).__name__}: {exc}"),
            "status": "ERROR",
            "overall_assurance_status": "ERROR",
        }

    ribbon_extensions = [
        {
            "key": "decision_layer",
            "label": "DECISION",
            "level": decision["level"],
            "value": str(decision.get("status_label") or decision.get("trading_state") or "—"),
        },
        {
            "key": "model_governance",
            "label": "ML GOVERNANCE",
            "level": governance["level"],
            "value": str(governance.get("governance_status") or governance.get("active_model") or "—"),
        },
        {
            "key": "economic_validation",
            "label": "ECONOMIC",
            "level": economic["level"],
            "value": (
                "STALE_VALIDATION / HISTORICAL"
                if (
                    (economic.get("freshness") or {}).get("is_stale")
                    or "STALE" in str(economic.get("status") or "").upper()
                )
                else (
                    f"W{economic.get('win_pct')}% N{economic.get('neutral_pct')}% L{economic.get('loss_pct')}%"
                    if economic.get("win_pct") is not None
                    else str(economic.get("status") or f"complete {economic.get('complete_h4h', 0)}")
                )
            ),
        },
        {
            "key": "shadow_inference",
            "label": "SHADOW",
            "level": shadow["level"],
            "value": str(shadow.get("validation_status") or shadow.get("metric_availability") or "—"),
        },
        {
            "key": "toxic_box",
            "label": "TOXIC",
            "level": toxic["level"],
            "value": str(
                toxic.get("severity_label")
                or toxic.get("display_status")
                or f"{toxic.get('events_last_7d', 0)}/7d"
            ),
        },
        {
            "key": "pipeline_sync",
            "label": "PIPELINE",
            "level": "GREEN" if pipeline["in_sync"] else "RED",
            "value": f"{pipeline['step_count']}/{pipeline['expected_step_count']}",
        },
    ]

    return {
        "generated_at": datetime.now().isoformat(),
        "model_summary_source_version": model_summary.get("model_summary_source_version"),
        "pipeline": pipeline,
        "decision_layer": decision,
        "model_governance": governance,
        "economic_validation": economic,
        "shadow_inference": shadow,
        "toxic_box": toxic,
        "drift_monitoring": drift,
        "model_summary": model_summary,
        "model_assurance": model_assurance,
        "ribbon_extensions": ribbon_extensions,
    }
