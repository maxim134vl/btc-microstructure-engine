"""Per-timeframe point-in-time state adapter (S4.1).

Reuses the existing runtime planes without changing their semantics:

  * availability / clock  -> data/cognition/multi_timeframe_availability_memory.parquet
                             (writer: mtf_availability_runtime_engine_v1.py)
  * lifecycle / direction -> data/cognition/market_context_lifecycle_memory.parquet
  * synthesis metadata    -> data/cognition/multi_timeframe_synthesis.parquet

The same lifecycle contract is applied *independently per timeframe*: each
timeframe resolves at its own confirmed bar-close clock, so M15 and H1 can
legitimately report opposite directions.

Hard rules enforced here:
  source_bar_close <= evaluation_timestamp
  lifecycle row timestamp <= source_bar_close
  no cross-timeframe fallback, no synthetic direction, D1 is never live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

AVAILABILITY_MEMORY = ROOT / "data/cognition/multi_timeframe_availability_memory.parquet"
AVAILABILITY_LATEST = ROOT / "data/runtime/multi_timeframe_availability_latest.json"
LIFECYCLE_MEMORY = ROOT / "data/cognition/market_context_lifecycle_memory.parquet"
SYNTHESIS_MEMORY = ROOT / "data/cognition/multi_timeframe_synthesis.parquet"

SUPPORTED_TIMEFRAMES = ("M15", "M30", "H1", "H4")
UNSUPPORTED_TIMEFRAMES = ("D1",)

OPERATIONAL_AVAILABILITY = {
    "FRESH_EVENT",
    "AVAILABLE_LAST_CONFIRMED",
    "NO_EVENT_STATE_UNCHANGED",
}

NO_ACTION_AVAILABILITY = {
    "WAITING_FOR_BAR_CLOSE",
    "UPSTREAM_STALE",
    "WRITER_STALE",
    "DATASET_MISSING",
    "SCHEMA_INVALID",
    "TIMEFRAME_NOT_LIVE",
}

DIRECTION_LONG = "LONG"
DIRECTION_SHORT = "SHORT"
DIRECTION_FLAT = "NON_DIRECTIONAL"

TERMINAL_LIFECYCLE_PHASES = {"INVALIDATED", "NO_ACTIVE_CONTEXT", "EXPIRED", "TERMINATED"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ts(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        stamp = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(stamp):
        return None
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _iso(value: Any) -> str | None:
    stamp = _ts(value)
    return None if stamp is None else stamp.isoformat().replace("+00:00", "Z")


@dataclass
class TimeframeSources:
    availability: pd.DataFrame = field(default_factory=pd.DataFrame)
    lifecycle: pd.DataFrame = field(default_factory=pd.DataFrame)
    synthesis: pd.DataFrame = field(default_factory=pd.DataFrame)
    load_errors: dict[str, str] = field(default_factory=dict)


def load_sources(
    *,
    availability_path: Path | None = None,
    lifecycle_path: Path | None = None,
    synthesis_path: Path | None = None,
) -> TimeframeSources:
    sources = TimeframeSources()
    for name, path, attr in (
        ("availability", availability_path or AVAILABILITY_MEMORY, "availability"),
        ("lifecycle", lifecycle_path or LIFECYCLE_MEMORY, "lifecycle"),
        ("synthesis", synthesis_path or SYNTHESIS_MEMORY, "synthesis"),
    ):
        if not path.exists():
            sources.load_errors[name] = "DATASET_MISSING"
            continue
        try:
            setattr(sources, attr, pd.read_parquet(path))
        except Exception as exc:
            sources.load_errors[name] = f"SCHEMA_INVALID:{type(exc).__name__}"
    return sources


def _lifecycle_direction(row: dict[str, Any]) -> tuple[str, str]:
    """Direction from the existing lifecycle contract (unchanged semantics)."""
    active = str(row.get("active_market_context") or "").upper()
    if active == "LONG_CONTEXT":
        return DIRECTION_LONG, "ACTIVE_LONG_CONTEXT"
    if active == "SHORT_CONTEXT":
        return DIRECTION_SHORT, "ACTIVE_SHORT_CONTEXT"
    return DIRECTION_FLAT, f"NON_DIRECTIONAL_CONTEXT:{active or 'UNKNOWN'}"


def _availability_row(
    availability: pd.DataFrame,
    *,
    timeframe: str,
    evaluation_ts: pd.Timestamp,
) -> dict[str, Any] | None:
    if not len(availability) or "timeframe" not in availability.columns:
        return None
    frame = availability[availability["timeframe"].astype(str).str.upper() == timeframe]
    if not len(frame):
        return None
    stamps = pd.to_datetime(frame["evaluation_timestamp"], utc=True, errors="coerce")
    mask = stamps <= evaluation_ts
    if not bool(mask.any()):
        return None
    idx = stamps[mask].sort_values().index[-1]
    return frame.loc[idx].to_dict()


def resolve_timeframe_state(
    *,
    timeframe: str,
    evaluation_timestamp: Any,
    sources: TimeframeSources,
    allow_provisional: bool = False,
    evaluation_mode: str | None = None,
    provisional_lifecycle: dict[str, Any] | None = None,
    causal_cutoff_timestamp: Any = None,
    causal_cutoff_monotonic_ns: Any = None,
    model_version: str | None = None,
) -> dict[str, Any]:
    """Resolve per-TF state.

    Closed-bar default unchanged. Provisional intrabar path only when
    ``allow_provisional=True`` and ``evaluation_mode=PROVISIONAL_INTRABAR``.
    Provisional results are never treated as manager-actionable closed tips.
    """
    tf = str(timeframe or "").upper()
    evaluation_ts = _ts(evaluation_timestamp)
    provisional = bool(
        allow_provisional and str(evaluation_mode or "").upper() == "PROVISIONAL_INTRABAR"
    )
    base: dict[str, Any] = {
        "timeframe": tf,
        "evaluation_timestamp": _iso(evaluation_ts),
        "resolved_at": _utc_now(),
        "source_bar_open": None,
        "source_bar_close": None,
        "source_state_timestamp": None,
        "source_event_timestamp": None,
        "availability_status": "UNKNOWN",
        "availability_reason": None,
        "is_new_event": None,
        "writer_state": None,
        "timeframe_state": "UNKNOWN",
        "timeframe_direction": DIRECTION_FLAT,
        "direction_reason": None,
        "lifecycle_episode_id": None,
        "lifecycle_phase": None,
        "lifecycle_row_timestamp": None,
        "actionable": False,
        "no_action_reason": None,
        "confidence": None,
        "alignment_score": None,
        "persistence_score": None,
        "structural_rank": None,
        "location_bias": None,
        "is_closed": not provisional,
        "evaluation_mode": "PROVISIONAL_INTRABAR" if provisional else "CLOSED_BAR",
        "causal_cutoff_timestamp": _iso(causal_cutoff_timestamp) if causal_cutoff_timestamp else None,
        "causal_cutoff_monotonic_ns": causal_cutoff_monotonic_ns,
        "model_version": model_version,
        "source_lineage": {
            "availability": str(AVAILABILITY_MEMORY.relative_to(ROOT)),
            "lifecycle": str(LIFECYCLE_MEMORY.relative_to(ROOT)),
            "synthesis": str(SYNTHESIS_MEMORY.relative_to(ROOT)),
        },
    }

    if provisional and provisional_lifecycle is not None:
        direction, direction_reason = _lifecycle_direction(dict(provisional_lifecycle))
        phase = str(provisional_lifecycle.get("lifecycle_state") or "UNKNOWN").upper()
        raw_episode = provisional_lifecycle.get("context_episode_id")
        episode = None if raw_episode is None else f"{tf}:{raw_episode}"
        base.update(
            {
                "availability_status": "PROVISIONAL_INTRABAR",
                "availability_reason": "explicit provisional evaluation mode",
                "timeframe_state": str(provisional_lifecycle.get("active_market_context") or "UNKNOWN").upper(),
                "timeframe_direction": direction,
                "direction_reason": direction_reason,
                "lifecycle_episode_id": episode,
                "lifecycle_phase": phase,
                "lifecycle_row_timestamp": _iso(evaluation_ts),
                "actionable": False,  # never feed old manager
                "no_action_reason": "PROVISIONAL_NOT_ROUTED_TO_MANAGER",
                "is_closed": False,
            }
        )
        return base

    if tf in UNSUPPORTED_TIMEFRAMES:
        base.update(
            {
                "availability_status": "TIMEFRAME_NOT_LIVE",
                "availability_reason": "NO_LIVE_STAGE2_WRITER",
                "timeframe_state": "TIMEFRAME_NOT_LIVE",
                "no_action_reason": "TIMEFRAME_NOT_LIVE",
                "writer_state": "NOT_IMPLEMENTED_LIVE",
            }
        )
        return base
    if tf not in SUPPORTED_TIMEFRAMES:
        base["no_action_reason"] = "TIMEFRAME_NOT_SUPPORTED"
        return base
    if evaluation_ts is None:
        base["no_action_reason"] = "INVALID_EVALUATION_TIMESTAMP"
        return base
    if sources.load_errors.get("availability"):
        base["availability_status"] = sources.load_errors["availability"]
        base["no_action_reason"] = sources.load_errors["availability"]
        return base

    row = _availability_row(sources.availability, timeframe=tf, evaluation_ts=evaluation_ts)
    if row is None:
        base["availability_status"] = "DATASET_MISSING"
        base["no_action_reason"] = "NO_AVAILABILITY_ROW_AT_OR_BEFORE_EVALUATION"
        return base

    status = str(row.get("availability_status") or "UNKNOWN").upper()
    bar_close = _ts(row.get("source_bar_close"))
    base.update(
        {
            "availability_status": status,
            "availability_reason": row.get("availability_reason"),
            "is_new_event": bool(row.get("is_new_event")) if row.get("is_new_event") is not None else None,
            "writer_state": row.get("writer_state"),
            "source_bar_open": _iso(row.get("source_bar_open")),
            "source_bar_close": _iso(bar_close),
            "source_state_timestamp": _iso(row.get("source_state_timestamp")),
            "source_event_timestamp": _iso(row.get("source_event_timestamp")),
        }
    )

    if status in NO_ACTION_AVAILABILITY:
        base["no_action_reason"] = status
        base["timeframe_state"] = status
        return base
    if status not in OPERATIONAL_AVAILABILITY:
        base["no_action_reason"] = f"UNKNOWN_AVAILABILITY_STATUS:{status}"
        base["timeframe_state"] = "UNKNOWN"
        return base
    if bar_close is None:
        base["no_action_reason"] = "MISSING_SOURCE_BAR_CLOSE"
        return base
    if bar_close > evaluation_ts:
        base["no_action_reason"] = "UNCLOSED_BAR_REJECTED"
        base["timeframe_state"] = "WAITING_FOR_BAR_CLOSE"
        return base

    if sources.load_errors.get("lifecycle"):
        base["no_action_reason"] = sources.load_errors["lifecycle"]
        return base
    lifecycle = sources.lifecycle
    if not len(lifecycle) or "timestamp" not in lifecycle.columns:
        base["no_action_reason"] = "LIFECYCLE_DATASET_MISSING"
        return base
    life_stamps = pd.to_datetime(lifecycle["timestamp"], utc=True, errors="coerce")
    life_mask = life_stamps <= bar_close
    if not bool(life_mask.any()):
        base["no_action_reason"] = "NO_LIFECYCLE_ROW_AT_OR_BEFORE_BAR_CLOSE"
        return base
    life_idx = life_stamps[life_mask].sort_values().index[-1]
    life_row = lifecycle.loc[life_idx].to_dict()
    direction, direction_reason = _lifecycle_direction(life_row)
    phase = str(life_row.get("lifecycle_state") or "UNKNOWN").upper()
    raw_episode = life_row.get("context_episode_id")
    episode = None
    if raw_episode is not None and not (isinstance(raw_episode, float) and pd.isna(raw_episode)):
        try:
            episode = f"{tf}:{int(float(raw_episode))}"
        except Exception:
            episode = f"{tf}:{raw_episode}"

    base.update(
        {
            "timeframe_state": str(life_row.get("active_market_context") or "UNKNOWN").upper(),
            "timeframe_direction": direction,
            "direction_reason": direction_reason,
            "lifecycle_episode_id": episode,
            "lifecycle_phase": phase,
            "lifecycle_row_timestamp": _iso(life_stamps.loc[life_idx]),
            "context_started_at": _iso(life_row.get("active_context_started_at")),
            "invalidation_reason": life_row.get("invalidation_reason"),
            "context_origin_price": None
            if life_row.get("context_origin_price") is None
            else float(life_row.get("context_origin_price") or 0.0) or None,
            "actionable": direction in {DIRECTION_LONG, DIRECTION_SHORT} and phase not in TERMINAL_LIFECYCLE_PHASES,
        }
    )
    if not base["actionable"] and base["no_action_reason"] is None:
        base["no_action_reason"] = (
            "NON_DIRECTIONAL_TIMEFRAME_STATE"
            if direction == DIRECTION_FLAT
            else f"TERMINAL_LIFECYCLE_PHASE:{phase}"
        )

    synthesis = sources.synthesis
    if len(synthesis) and "timestamp" in synthesis.columns:
        syn_stamps = pd.to_datetime(synthesis["timestamp"], utc=True, errors="coerce")
        syn_mask = syn_stamps <= bar_close
        if bool(syn_mask.any()):
            syn_row = synthesis.loc[syn_stamps[syn_mask].sort_values().index[-1]].to_dict()
            base.update(
                {
                    "alignment_score": syn_row.get("alignment_score"),
                    "persistence_score": syn_row.get("persistence_score"),
                    "structural_rank": syn_row.get("structural_rank"),
                    "location_bias": syn_row.get("location_bias"),
                    "synthesis_state": syn_row.get("synthesis_state"),
                    "synthesis_row_timestamp": _iso(syn_stamps.loc[syn_stamps[syn_mask].sort_values().index[-1]]),
                }
            )
            try:
                base["confidence"] = float(syn_row.get("persistence_score"))
            except Exception:
                base["confidence"] = None
    return base


def resolve_all_states(
    *,
    evaluation_timestamp: Any,
    sources: TimeframeSources | None = None,
    timeframes: tuple[str, ...] = SUPPORTED_TIMEFRAMES,
) -> dict[str, dict[str, Any]]:
    src = sources or load_sources()
    return {
        tf: resolve_timeframe_state(timeframe=tf, evaluation_timestamp=evaluation_timestamp, sources=src)
        for tf in timeframes
    }
