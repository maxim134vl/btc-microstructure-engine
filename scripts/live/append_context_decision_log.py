#!/usr/bin/env python3
"""Shadow-only append-only market context decision logger.

Records what the context stack knew at decision time for the latest available
closed candle that has lifecycle context.

Does NOT enable execution.
Does NOT rewrite historical context artifacts.
Does NOT use visual JSON as a decision source.
Does NOT mutate previously written decision rows.

Required statement:
  This logger records shadow-only market context decisions. It does not enable
  execution and must not be used to place orders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"
AUCTION_PATH = ROOT / "data" / "cognition" / "auction_episode_memory.parquet"
COGNITIVE_PATH = ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet"
FINAL_PATH = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
LIFECYCLE_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
RUNTIME_LOG = ROOT / "logs" / "runtime_stack" / "runtime.log"
SHADOW_STATUS = ROOT / "data" / "cognition" / "market_context_shadow_chain_status.json"
DECISION_LOG_PATH = ROOT / "data" / "live" / "context_decision_log.parquet"

SCHEMA_VERSION = "context_decision_log_v1_start_event"
LOGGER_VERSION = "append_context_decision_log_v1_start_event"
SOURCE_TIMEFRAME = "15m"
PIPELINE_CYCLE_RE = re.compile(r"PIPELINE CYCLE:\s*(\d+)")

REQUIRED_SOURCE_FILES = (
    LIVE_FEED,
    AUCTION_PATH,
    COGNITIVE_PATH,
    FINAL_PATH,
    LIFECYCLE_PATH,
)

DECISION_COLUMNS_BASE = [
    "decision_id",
    "decision_written_at_utc",
    "candle_timestamp",
    "candle_close_time_utc",
    "source_timeframe",
    "runtime_pid",
    "pipeline_cycle",
    "runtime_segments",
    "total_runtime_log_cycles",
    "live_feed_latest_timestamp",
    "auction_latest_timestamp",
    "cognitive_latest_timestamp",
    "final_context_latest_timestamp",
    "lifecycle_latest_timestamp",
    "live_to_auction_lag_seconds",
    "live_to_cognitive_lag_seconds",
    "live_to_final_context_lag_seconds",
    "live_to_lifecycle_lag_seconds",
    "decision_lag_vs_live_seconds",
    "decision_lag_vs_lifecycle_seconds",
    "auction_episode",
    "auction_episode_status",
    "cognitive_market_state",
    "cognitive_state_status",
    "cognitive_state_direction",
    "raw_market_context",
    "raw_context_status",
    "active_market_context",
    "lifecycle_state",
    "active_context_age_bars",
    "active_context_started_at",
    "lifecycle_episode_id",
    "lifecycle_episode_start_time",
    "lifecycle_episode_end_time",
    "candidate_context",
    "candidate_started_at",
    "previous_active_market_context",
    "transition_reason",
    "lifecycle_state_reason",
    "state_entered_at",
    "state_age_minutes",
    "transition_block_reason",
    "cognition_state_age_minutes",
    "upstream_cognition_freshness_minutes",
    "market_feed_age_minutes",
    "market_activity_score",
    "observe_escape_candidate",
    "observe_block_reason",
    # Phase-1 context origin price diagnostics (not used as synthetic fill).
    "context_origin_price",
    "context_entered_at",
    "context_episode_id",
    "context_direction",
    "context_distance_bps",
    "context_favorable_distance_bps",
    "context_adverse_distance_bps",
    "context_start_event",
    "context_start_event_source",
    "directional_flip_detected",
    "context_end_event",
    "invalidation_type",
    "action_allowed",
    "shadow_only",
    "execution_enabled",
    "visual_json_used_for_execution",
    "orders_created",
    "paper_orders_created",
    "technical_refresh_lag_present",
    "pipeline_pending",
    "decision_stale",
    "decision_freshness_status",
    "decision_stale_reason",
    "execution_readiness_blocked",
    "source_files_hash",
    "decision_payload_hash",
    "schema_version",
    "logger_version",
]

# Additive-only signal readiness fields (research patch). Never invent confidence/edge.
SIGNAL_FIELD_COLUMNS = [
    "decision_signal_schema_version",
    "decision_age_seconds",
    "freshness_status",
    "confidence",
    "confidence_source",
    "confidence_available",
    "expected_edge_bps",
    "expected_edge_source",
    "expected_edge_available",
    "expected_edge_basis",
    "edge_signal_rule",
    "edge_signal_pass",
    "total_roundtrip_model_cost_bps",
    "cost_source",
    "cost_handling",
    "edge_above_cost",
    "lookup_bucket_id",
    "confidence_bucket_id",
    "expected_edge_bucket_id",
    "corrected_lookup_snapshot_id",
    "edge_lookup_snapshot_id",
    "edge_lookup_cutoff_ts",
    "lookup_valid_for_decisions_after_ts_utc",
    "lookup_applied",
    "instrument_source",
    "signal_eligibility_status",
    "signal_block_reasons",
    "paper_action_candidate",
    "intended_side",
    "order_side",
    "position_intent",
    "paper_signal_write_allowed",
    "paper_loop_allowed",
    "signal_fields_patch_status",
    "signal_fields_patch_mode",
    "signal_fields_generated_at_utc",
]

# Additive metadata for historical catch-up rows (existing rows keep None/"LIVE").
BACKFILL_META_COLUMNS = [
    "record_origin",
    "backfilled_at_utc",
]

DECISION_COLUMNS = DECISION_COLUMNS_BASE + SIGNAL_FIELD_COLUMNS + BACKFILL_META_COLUMNS

RECORD_ORIGIN_LIVE = "LIVE"
RECORD_ORIGIN_BACKFILL = "BACKFILL"

DETERMINISTIC_TOTAL_ROUNDTRIP_MODEL_COST_BPS = 20.0
DETERMINISTIC_COST_SOURCE = "DETERMINISTIC_PAPER_SIMULATOR_SPEC"
SIGNAL_SCHEMA_VERSION = "v1"
SIGNAL_FIELDS_PATCH_STATUS = "ADDITIVE_PATCH_APPLIED"
SIGNAL_FIELDS_PATCH_MODE = "RESEARCH_ONLY_ADDITIVE"
LOOKUP_INTEGRATION_PATCH_MARKER = "LOGGER_LOOKUP_INTEGRATION_PATCH_ADDITIVE_V1"
STALE_MAX_AGE_HOURS = 6.0
# Canonical M15 closed-bar pipeline grace: live may advance one bar before lifecycle/decision catch-up.
PIPELINE_GRACE_SECONDS = 900.0
NO_CONFIDENCE_SOURCE = "NO_CONFIDENCE_SOURCE_AVAILABLE"
NO_EXPECTED_EDGE_SOURCE = "NO_EXPECTED_EDGE_SOURCE_AVAILABLE"
DEFAULT_LOOKUP_INSTRUMENT = "BTCUSDT"
DEFAULT_INSTRUMENT_SOURCE = "DEFAULT_BTCUSDT"
COST_HANDLING_AUDIT_ONLY = "AUDIT_REFERENCE_ONLY_ALREADY_INCLUDED_IN_NET_EDGE"

# Fields hashed for mutation/conflict detection (stable decision content).
PAYLOAD_HASH_FIELDS = [
    "candle_timestamp",
    "auction_episode",
    "auction_episode_status",
    "cognitive_market_state",
    "cognitive_state_status",
    "cognitive_state_direction",
    "raw_market_context",
    "raw_context_status",
    "active_market_context",
    "lifecycle_state",
    "active_context_age_bars",
    "active_context_started_at",
    "candidate_context",
    "candidate_started_at",
    "lifecycle_state_reason",
    "state_entered_at",
    "state_age_minutes",
    "transition_block_reason",
    "cognition_state_age_minutes",
    "upstream_cognition_freshness_minutes",
    "market_feed_age_minutes",
    "market_activity_score",
    "observe_escape_candidate",
    "observe_block_reason",
    "context_start_event",
    "context_start_event_source",
    "invalidation_type",
    "pipeline_pending",
    "decision_stale",
    "decision_freshness_status",
    "decision_stale_reason",
    "action_allowed",
    "shadow_only",
    "execution_enabled",
    "visual_json_used_for_execution",
    "orders_created",
    "paper_orders_created",
    "schema_version",
    "logger_version",
]


class DecisionLoggerError(RuntimeError):
    """Safe failure for missing sources / mutation conflicts."""


def _clean(value: Any, default: str = "UNKNOWN") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    return text


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_utc_ts(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    out = pd.Timestamp(ts)
    if out.tzinfo is None:
        out = out.tz_localize("UTC")
    else:
        out = out.tz_convert("UTC")
    return out


def _iso(ts: pd.Timestamp | None) -> str | None:
    if ts is None or pd.isna(ts):
        return None
    aware = _to_utc_ts(ts)
    if aware is None:
        return None
    return aware.isoformat().replace("+00:00", "Z")


def _lag_seconds(newer: pd.Timestamp | None, older: pd.Timestamp | None) -> float | None:
    newer_ts = _to_utc_ts(newer)
    older_ts = _to_utc_ts(older)
    if newer_ts is None or older_ts is None:
        return None
    return round((newer_ts - older_ts).total_seconds(), 3)


def load_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise DecisionLoggerError(f"Missing required source: {path}")
    frame = pd.read_parquet(path)
    for col in ("timestamp", "active_context_started_at"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], utc=True, errors="coerce")
    return frame


def latest_timestamp(frame: pd.DataFrame, col: str = "timestamp") -> pd.Timestamp | None:
    if frame is None or len(frame) == 0 or col not in frame.columns:
        return None
    series = pd.to_datetime(frame[col], utc=True, errors="coerce").dropna()
    if len(series) == 0:
        return None
    return _to_utc_ts(series.max())


def row_at_timestamp(frame: pd.DataFrame, ts: pd.Timestamp, col: str = "timestamp") -> pd.Series | None:
    if frame is None or len(frame) == 0 or col not in frame.columns:
        return None
    target = _to_utc_ts(ts)
    if target is None:
        return None
    series = pd.to_datetime(frame[col], utc=True, errors="coerce")
    matched = frame.loc[series == target]
    if len(matched) == 0:
        # Exact match failed — try nearest prior within 2h (no fabrication forward).
        prior_mask = series.notna() & (series <= target)
        prior = frame.loc[prior_mask].assign(_ts=series.loc[prior_mask]).sort_values("_ts")
        if len(prior) == 0:
            return None
        candidate = prior.iloc[-1]
        lag = (target - _to_utc_ts(candidate["_ts"])).total_seconds()
        if lag > 2 * 3600:
            return None
        return candidate.drop(labels=["_ts"], errors="ignore")
    return matched.iloc[-1]


def parse_runtime_cycles(log_path: Path = RUNTIME_LOG) -> dict[str, Any]:
    empty = {
        "pipeline_cycle": None,
        "runtime_segments": 0,
        "total_runtime_log_cycles": 0,
        "log_exists": False,
    }
    if not log_path.exists():
        return empty
    cycles: list[int] = []
    segments = 0
    prev: int | None = None
    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            match = PIPELINE_CYCLE_RE.search(line)
            if not match:
                continue
            n = int(match.group(1))
            cycles.append(n)
            if prev is None or n < prev:
                segments += 1
            prev = n
    if not cycles:
        return {**empty, "log_exists": True}
    return {
        "pipeline_cycle": cycles[-1],
        "runtime_segments": segments,
        "total_runtime_log_cycles": len(cycles),
        "log_exists": True,
    }


def source_files_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: str(p)):
        digest.update(str(path).encode("utf-8"))
        if not path.exists():
            digest.update(b"MISSING")
            continue
        # Hash file mtime + size + trailing bytes for stability without full-file cost.
        stat = path.stat()
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        digest.update(str(stat.st_size).encode("utf-8"))
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 65536), os.SEEK_SET)
            digest.update(handle.read())
    return digest.hexdigest()


def decision_payload_hash(payload: dict[str, Any]) -> str:
    material = {key: payload.get(key) for key in PAYLOAD_HASH_FIELDS}
    encoded = json.dumps(material, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def enforce_safety_fields(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["action_allowed"] = False
    row["shadow_only"] = True
    row["execution_enabled"] = False
    row["visual_json_used_for_execution"] = False
    row["orders_created"] = False
    row["paper_orders_created"] = False
    row["execution_readiness_blocked"] = True
    return row


def _parse_iso_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            s = str(value).strip()
            if not s or s.lower() in {"nan", "nat", "none", "null"}:
                return None
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _nullable_float(value: Any) -> float | None:
    """Return float only for real numeric sources; never invent values."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, str) and value.strip().lower() in {
            "",
            "nan",
            "none",
            "null",
            "nat",
        }:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def default_corrected_lookup_path() -> Path:
    """Default research path for corrected lagged context edge lookup snapshot."""
    return (
        ROOT
        / "data"
        / "research"
        / "paper_simulator"
        / "corrected_lagged_context_edge_lookup_snapshot.parquet"
    )


def normalize_lookup_timestamp(value: Any) -> datetime | None:
    """Normalize lookup/decision timestamps to UTC datetime (no fabrication)."""
    return _parse_iso_ts(value)


def load_corrected_context_edge_lookup(
    path: Path | str | None = None,
) -> pd.DataFrame:
    """Read-only loader. Never raises on missing/malformed lookup; returns empty frame.

    Import-time side-effect free: does not read files until called.
    """
    lookup_path = Path(path) if path is not None else default_corrected_lookup_path()
    empty_cols = [
        "corrected_lookup_snapshot_id",
        "lookup_bucket_id",
        "instrument",
        "context_type",
        "lifecycle_state",
        "action_candidate",
        "confidence",
        "confidence_source",
        "confidence_available",
        "expected_edge_bps",
        "expected_edge_source",
        "expected_edge_available",
        "expected_edge_basis",
        "edge_signal_rule",
        "edge_signal_pass",
        "total_roundtrip_model_cost_bps",
        "cost_source",
        "cost_handling",
        "sample_status",
        "lookup_cutoff_ts_utc",
        "lookup_valid_for_decisions_after_ts_utc",
    ]
    if not lookup_path.exists():
        return pd.DataFrame(columns=empty_cols)
    try:
        frame = pd.read_parquet(lookup_path)
    except Exception:
        return pd.DataFrame(columns=empty_cols)
    if frame is None or len(frame) == 0:
        return pd.DataFrame(columns=empty_cols)
    required = {
        "instrument",
        "context_type",
        "lifecycle_state",
        "action_candidate",
        "confidence",
        "expected_edge_bps",
        "expected_edge_basis",
    }
    if not required.issubset(set(frame.columns)):
        return pd.DataFrame(columns=empty_cols)
    return frame


def get_lookup_cutoff_ts(lookup_df: pd.DataFrame | None) -> datetime | None:
    """Return max lookup_valid_for_decisions_after_ts_utc from lookup frame."""
    if lookup_df is None or len(lookup_df) == 0:
        return None
    col = "lookup_valid_for_decisions_after_ts_utc"
    if col not in lookup_df.columns:
        return None
    times = [normalize_lookup_timestamp(v) for v in lookup_df[col].tolist()]
    times = [t for t in times if t is not None]
    if not times:
        return None
    return max(times)


def build_lookup_bucket_key(
    instrument: str,
    context_type: str,
    lifecycle_state: str,
    action_candidate: str,
) -> str:
    """Deterministic bucket key for matching (pipe-delimited fields)."""
    return "|".join(
        [
            str(instrument).strip(),
            str(context_type).strip(),
            str(lifecycle_state).strip(),
            str(action_candidate).strip(),
        ]
    )


def map_context_to_action_candidate(context_type: str | None) -> str | None:
    if context_type == "LONG_CONTEXT":
        return "INTENT_OPEN_LONG"
    if context_type == "SHORT_CONTEXT":
        return "INTENT_OPEN_SHORT"
    if context_type in {"LONG_CONTEXT_REFERENCE"}:
        return "INTENT_OPEN_LONG"
    if context_type in {"SHORT_CONTEXT_REFERENCE"}:
        return "INTENT_OPEN_SHORT"
    return None


def normalize_signal_context_label(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().upper()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    if text == "LONG_CONTEXT_REFERENCE":
        return "LONG_CONTEXT"
    if text == "SHORT_CONTEXT_REFERENCE":
        return "SHORT_CONTEXT"
    return text


def resolve_signal_context(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return effective signal context and source field for paper action mapping.

    Paper policy treats directional CANDIDATE rows as tradable even while the
    exported active context remains OBSERVE. Keep active directional contexts
    unchanged, and only promote candidate_context for CANDIDATE lifecycle rows.
    """
    active = normalize_signal_context_label(
        row.get("active_market_context") or row.get("context_type")
    )
    if active in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
        return active, "active_market_context"
    lifecycle = str(row.get("lifecycle_state") or "").strip().upper()
    candidate = normalize_signal_context_label(row.get("candidate_context"))
    if lifecycle == "CANDIDATE" and candidate in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
        return candidate, "candidate_context"
    return active, "active_market_context"


def resolve_lookup_instrument(row: dict[str, Any]) -> tuple[str, str]:
    for key in ("instrument", "symbol"):
        raw = row.get(key)
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        text = str(raw).strip()
        if text and text.lower() not in {"nan", "none", "null"}:
            return text, f"ROW_FIELD_{key}"
    return DEFAULT_LOOKUP_INSTRUMENT, DEFAULT_INSTRUMENT_SOURCE


def resolve_lookup_lifecycle(row: dict[str, Any]) -> tuple[str | None, str]:
    for key in (
        "lifecycle_state",
        "active_lifecycle_state",
        "context_lifecycle_state",
    ):
        raw = row.get(key)
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        text = str(raw).strip()
        if text and text.lower() not in {"nan", "none", "null"}:
            return text, f"ROW_FIELD_{key}"
    return None, "MISSING"


def resolve_decision_ts_for_lookup(row: dict[str, Any]) -> datetime | None:
    for key in (
        "decision_timestamp_utc",
        "candle_close_time_utc",
        "candle_timestamp",
        "decision_written_at_utc",
    ):
        ts = normalize_lookup_timestamp(row.get(key))
        if ts is not None:
            return ts
    return None


def classify_decision_freshness(
    *,
    decision_market_ts: Any,
    lifecycle_ts: Any,
    live_ts: Any,
    now_utc: datetime | None = None,
    pipeline_grace_seconds: float = PIPELINE_GRACE_SECONDS,
) -> dict[str, Any]:
    """Classify decision freshness from data timestamps (not wall-clock alone).

    Canonical axes:
      - latest closed market bar (live feed)
      - latest lifecycle bar
      - decision market bar

    live > lifecycle with decision == lifecycle means PIPELINE_PENDING for the
    next bar, not that the current decision is data-stale.
    """
    decision_ts = _to_utc_ts(decision_market_ts)
    life_ts = _to_utc_ts(lifecycle_ts)
    market_ts = _to_utc_ts(live_ts)
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    live_to_lifecycle_lag_seconds = _lag_seconds(market_ts, life_ts)
    lifecycle_to_decision_lag_seconds = _lag_seconds(life_ts, decision_ts)
    live_ahead = bool(
        market_ts is not None and life_ts is not None and market_ts > life_ts
    )
    lifecycle_ahead = bool(
        life_ts is not None and decision_ts is not None and life_ts > decision_ts
    )
    decision_matches_lifecycle = bool(
        decision_ts is not None and life_ts is not None and decision_ts == life_ts
    )
    market_stale = False
    if market_ts is not None:
        market_age = (now - market_ts.to_pydatetime()).total_seconds()
        # Stalled market feed: no newer live bar than lifecycle and wall-clock lag exceeded.
        market_stale = (not live_ahead) and market_age > float(pipeline_grace_seconds) * 2.0

    status = "UNKNOWN"
    reason = "UNKNOWN"
    decision_stale = False
    pipeline_pending = False

    if decision_ts is None or life_ts is None or market_ts is None:
        status = "DEGRADED_MISSING_TIMESTAMPS"
        reason = "MISSING_MARKET_OR_LIFECYCLE_OR_DECISION_TIMESTAMP"
        decision_stale = True
    elif lifecycle_ahead:
        lag = float(lifecycle_to_decision_lag_seconds or 0.0)
        if lag <= float(pipeline_grace_seconds):
            status = "PIPELINE_PENDING"
            reason = "PIPELINE_PENDING_LIFECYCLE_AHEAD_OF_DECISION"
            pipeline_pending = True
            decision_stale = False
        else:
            status = "STALE_DECISION"
            reason = "STALE_DECISION"
            decision_stale = True
            pipeline_pending = False
    elif live_ahead and decision_matches_lifecycle:
        status = "PIPELINE_PENDING"
        reason = "PIPELINE_PENDING_LIVE_AHEAD_OF_LIFECYCLE"
        pipeline_pending = True
        decision_stale = False
    elif decision_matches_lifecycle and not live_ahead:
        # Data-aligned closed-bar decision is FRESH even if bars are historical.
        # market_feed_stale remains a separate diagnostic for stalled live feeds.
        status = "FRESH"
        reason = "FRESH_DECISION"
        decision_stale = False
        pipeline_pending = False
    elif decision_ts is not None and life_ts is not None and decision_ts < life_ts:
        status = "STALE_DECISION"
        reason = "STALE_DECISION"
        decision_stale = True
    else:
        status = "DEGRADED_TIMESTAMP_MISMATCH"
        reason = "DECISION_LIFECYCLE_MISMATCH"
        decision_stale = True

    return {
        "decision_market_timestamp": decision_ts,
        "lifecycle_timestamp": life_ts,
        "live_timestamp": market_ts,
        "decision_stale": bool(decision_stale),
        "pipeline_pending": bool(pipeline_pending),
        "technical_refresh_lag_present": bool(live_ahead),
        "decision_freshness_status": status,
        "decision_stale_reason": reason,
        "live_to_lifecycle_lag_seconds": live_to_lifecycle_lag_seconds,
        "lifecycle_to_decision_lag_seconds": lifecycle_to_decision_lag_seconds,
        "decision_matches_lifecycle": bool(decision_matches_lifecycle),
        "market_feed_stale": bool(market_stale),
        "new_entries_blocked": bool(decision_stale or pipeline_pending or market_stale),
    }


def is_decision_stale_for_lookup(
    row: dict[str, Any],
    *,
    now_utc: datetime | None = None,
    decision_ts: datetime | None = None,
) -> tuple[bool, float | None, str]:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    flag_stale = bool(row.get("decision_stale")) if row.get("decision_stale") is not None else False
    pipeline_pending = bool(row.get("pipeline_pending")) if row.get("pipeline_pending") is not None else False
    freshness = str(row.get("freshness_status") or "").upper()
    freshness_status = str(row.get("decision_freshness_status") or "").upper()
    is_stale_flag = bool(row.get("is_stale")) if row.get("is_stale") is not None else False
    age_seconds: float | None = None
    age_stale = False
    # Wall-clock age uses decision write time when available — not candle open/close —
    # so a decision that matches the latest closed bar is not stale merely because
    # the bar itself is in the past.
    age_anchor = _parse_iso_ts(row.get("decision_written_at_utc")) or decision_ts
    if age_anchor is not None:
        if age_anchor.tzinfo is None:
            age_anchor = age_anchor.replace(tzinfo=timezone.utc)
        age_seconds = (now - age_anchor).total_seconds()
        age_stale = (age_seconds / 3600.0) > STALE_MAX_AGE_HOURS
    # Pipeline pending / fresh data-aligned decisions are not permanent decision-data stale.
    data_fresh = freshness_status in {"FRESH", "PIPELINE_PENDING"}
    stale = bool(
        ((flag_stale and not pipeline_pending) or is_stale_flag or freshness == "STALE" or freshness_status == "STALE_DECISION")
        or (age_stale and not data_fresh)
    )
    if stale:
        freshness_out = "STALE"
    elif pipeline_pending or freshness_status == "PIPELINE_PENDING":
        freshness_out = "PIPELINE_PENDING"
    elif decision_ts is not None:
        freshness_out = "FRESH"
    else:
        freshness_out = "UNKNOWN"
    return stale, age_seconds, freshness_out


def match_lookup_bucket(
    decision_row: dict[str, Any],
    lookup_df: pd.DataFrame | None,
) -> pd.Series | None:
    """Match instrument/context_type/lifecycle_state/action_candidate exactly."""
    if lookup_df is None or len(lookup_df) == 0:
        return None
    ctx, _ctx_source = resolve_signal_context(decision_row)
    if not ctx:
        return None
    action = map_context_to_action_candidate(ctx)
    lifecycle, _ = resolve_lookup_lifecycle(decision_row)
    instrument, _ = resolve_lookup_instrument(decision_row)
    if action is None or lifecycle is None:
        return None
    mask = (
        (lookup_df["instrument"].astype(str) == instrument)
        & (lookup_df["context_type"].astype(str) == ctx)
        & (lookup_df["lifecycle_state"].astype(str) == lifecycle)
        & (lookup_df["action_candidate"].astype(str) == action)
    )
    hits = lookup_df.loc[mask]
    if len(hits) == 0:
        return None
    return hits.iloc[0]


def derive_basis_aware_edge_signal(
    expected_edge_bps: float | None,
    expected_edge_basis: str | None,
    total_roundtrip_model_cost_bps: float | None,
) -> tuple[bool | None, str | None, str | None]:
    """Return (edge_signal_pass, edge_signal_rule, block_reason_if_unknown)."""
    if expected_edge_bps is None or expected_edge_basis is None:
        return None, None, None
    basis = str(expected_edge_basis).strip()
    if basis == "NET_AFTER_COST":
        return (
            float(expected_edge_bps) > 0.0,
            "NET_EXPECTED_EDGE_GT_ZERO",
            None,
        )
    if basis == "GROSS_BEFORE_COST":
        cost = float(
            total_roundtrip_model_cost_bps
            if total_roundtrip_model_cost_bps is not None
            else DETERMINISTIC_TOTAL_ROUNDTRIP_MODEL_COST_BPS
        )
        return (
            float(expected_edge_bps) > cost,
            "GROSS_EXPECTED_EDGE_GT_COST",
            None,
        )
    return None, None, "UNKNOWN_EDGE_BASIS"


def apply_lookup_to_signal_fields(
    decision_row: dict[str, Any],
    lookup_df: pd.DataFrame | None,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Populate signal fields from corrected lookup with basis-aware / future-only rules.

    Never invents confidence/edge. paper_signal_write_allowed / paper_loop_allowed
    always false. LOOKUP_INTEGRATION_PATCH_MARKER.
    """
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    ts = resolve_decision_ts_for_lookup(decision_row)
    ctx, ctx_source = resolve_signal_context(decision_row)
    ctx_match = ctx

    stale, age_seconds, freshness = is_decision_stale_for_lookup(
        decision_row, now_utc=now, decision_ts=ts
    )
    instrument, instrument_source = resolve_lookup_instrument(decision_row)
    lifecycle, _life_src = resolve_lookup_lifecycle(decision_row)
    action = map_context_to_action_candidate(ctx_match)
    lookup_cutoff = get_lookup_cutoff_ts(lookup_df)
    observe_block = str(decision_row.get("observe_block_reason") or "").strip().upper()
    transition_block = str(decision_row.get("transition_block_reason") or "").strip().upper()
    stale_cognition_blocked = (
        str(lifecycle or "").strip().upper() == "STALE_COGNITION"
        or observe_block in {"STALE_COGNITION", "STALE_MARKET_AND_COGNITION"}
        or transition_block in {"STALE_COGNITION", "STALE_MARKET_AND_COGNITION"}
    )
    pipeline_pending = bool(decision_row.get("pipeline_pending")) or freshness == "PIPELINE_PENDING"

    conf = None
    conf_src = None
    conf_avail = False
    edge = None
    edge_src = None
    edge_avail = False
    edge_basis = None
    edge_rule = None
    edge_pass = None
    cost = float(DETERMINISTIC_TOTAL_ROUNDTRIP_MODEL_COST_BPS)
    cost_source = DETERMINISTIC_COST_SOURCE
    cost_handling = None
    lookup_applied = False
    bucket_id = None
    snapshot_id = None
    edge_cutoff = None
    valid_after = None

    block_reasons: list[str] = []
    eligibility = "ELIGIBLE_DIRECTIONAL_SIGNAL"
    paper_action = "NO_TRADE_MISSING_FIELDS"
    intended = "NONE"
    order_side = "NONE"
    position_intent = "NONE"

    # Precedence (logger lookup integration):
    # 1 missing timestamp/context
    # 2 pipeline pending
    # 3 stale cognition / stale decision
    # 4 decision_ts <= lookup cutoff
    # 5 OBSERVE/STAND_ASIDE/non-directional
    # 6 missing lifecycle/bucket fields
    # 7 no bucket match
    # 8 sample too small / stale lookup
    # 9 missing confidence / missing expected edge
    # 10 unknown edge basis
    # 11 edge_signal_pass false
    # 12 eligible directional signal
    if ts is None and ctx is None:
        eligibility = "BLOCKED_MISSING_CONTEXT"
        block_reasons.extend(["MISSING_CONTEXT", "MISSING_TIMESTAMP"])
    elif ctx is None:
        eligibility = "BLOCKED_MISSING_CONTEXT"
        block_reasons.append("MISSING_CONTEXT")
    elif ts is None:
        eligibility = "BLOCKED_MISSING_TIMESTAMP"
        block_reasons.append("MISSING_TIMESTAMP")
    elif pipeline_pending:
        eligibility = "BLOCKED_PIPELINE_PENDING"
        block_reasons.append("PIPELINE_PENDING")
        paper_action = "NO_TRADE_PIPELINE_PENDING"
        if ctx == "OBSERVE":
            block_reasons.append("OBSERVE_CONTEXT")
    elif stale_cognition_blocked:
        eligibility = "BLOCKED_STALE_COGNITION"
        block_reasons.append("STALE_COGNITION")
        paper_action = "NO_TRADE_STALE_COGNITION"
        if stale:
            block_reasons.append("STALE_CONTEXT")
        if ctx == "OBSERVE":
            block_reasons.append("OBSERVE_CONTEXT")
    elif stale:
        eligibility = "BLOCKED_STALE_CONTEXT"
        block_reasons.append("STALE_CONTEXT")
        paper_action = "NO_TRADE_STALE_CONTEXT"
        if ctx == "OBSERVE":
            block_reasons.append("OBSERVE_CONTEXT")
    elif ctx_source == "candidate_context" and ctx_match in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
        eligibility = "ELIGIBLE_DIRECTIONAL_SIGNAL"
        if ctx_match == "LONG_CONTEXT":
            paper_action = "INTENT_OPEN_LONG"
            intended = "LONG"
            order_side = "BUY"
            position_intent = "OPEN_LONG"
        else:
            paper_action = "INTENT_OPEN_SHORT"
            intended = "SHORT"
            order_side = "SELL"
            position_intent = "OPEN_SHORT"
    elif lookup_cutoff is not None and ts <= lookup_cutoff:
        eligibility = "BLOCKED_LOOKUP_NOT_VALID_FOR_DECISION_TIME"
        block_reasons.append("LOOKUP_NOT_VALID_FOR_DECISION_TIME")
        paper_action = "NO_TRADE_LOOKUP_NOT_VALID"
        valid_after = lookup_cutoff.isoformat().replace("+00:00", "Z")
    elif ctx == "OBSERVE":
        eligibility = "BLOCKED_OBSERVE_CONTEXT"
        block_reasons.append("OBSERVE_CONTEXT")
        paper_action = "NO_TRADE_OBSERVE"
    elif ctx == "STAND_ASIDE":
        eligibility = "BLOCKED_STAND_ASIDE"
        block_reasons.append("STAND_ASIDE")
        paper_action = "NO_TRADE_STAND_ASIDE"
    elif ctx_match not in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
        eligibility = "BLOCKED_NOT_DIRECTIONAL"
        block_reasons.append("NOT_DIRECTIONAL")
    elif lifecycle is None:
        eligibility = "BLOCKED_MISSING_LIFECYCLE_STATE"
        block_reasons.append("MISSING_LIFECYCLE_STATE")
    elif action is None:
        eligibility = "BLOCKED_NOT_DIRECTIONAL"
        block_reasons.append("NOT_DIRECTIONAL")
    else:
        hit = match_lookup_bucket(
            {
                **decision_row,
                "active_market_context": ctx_match,
                "lifecycle_state": lifecycle,
                "instrument": instrument,
            },
            lookup_df,
        )
        if hit is None:
            eligibility = "BLOCKED_NO_EDGE_BUCKET"
            block_reasons.append("NO_EDGE_BUCKET")
        else:
            sample_status = str(hit.get("sample_status") or "")
            if sample_status == "SAMPLE_TOO_SMALL":
                eligibility = "BLOCKED_SAMPLE_TOO_SMALL"
                block_reasons.append("SAMPLE_TOO_SMALL")
            else:
                conf = _nullable_float(hit.get("confidence"))
                conf_src = hit.get("confidence_source")
                conf_avail = bool(hit.get("confidence_available")) and conf is not None
                edge = _nullable_float(hit.get("expected_edge_bps"))
                edge_src = hit.get("expected_edge_source")
                edge_avail = bool(hit.get("expected_edge_available")) and edge is not None
                edge_basis = (
                    None
                    if hit.get("expected_edge_basis") is None
                    or (
                        isinstance(hit.get("expected_edge_basis"), float)
                        and pd.isna(hit.get("expected_edge_basis"))
                    )
                    else str(hit.get("expected_edge_basis"))
                )
                cost_val = _nullable_float(hit.get("total_roundtrip_model_cost_bps"))
                if cost_val is not None:
                    cost = float(cost_val)
                if hit.get("cost_source") is not None and not (
                    isinstance(hit.get("cost_source"), float) and pd.isna(hit.get("cost_source"))
                ):
                    cost_source = str(hit.get("cost_source"))
                if hit.get("cost_handling") is not None and not (
                    isinstance(hit.get("cost_handling"), float)
                    and pd.isna(hit.get("cost_handling"))
                ):
                    cost_handling = str(hit.get("cost_handling"))
                else:
                    cost_handling = COST_HANDLING_AUDIT_ONLY
                bucket_id = (
                    None
                    if hit.get("lookup_bucket_id") is None
                    or (
                        isinstance(hit.get("lookup_bucket_id"), float)
                        and pd.isna(hit.get("lookup_bucket_id"))
                    )
                    else str(hit.get("lookup_bucket_id"))
                )
                snapshot_id = (
                    None
                    if hit.get("corrected_lookup_snapshot_id") is None
                    or (
                        isinstance(hit.get("corrected_lookup_snapshot_id"), float)
                        and pd.isna(hit.get("corrected_lookup_snapshot_id"))
                    )
                    else str(hit.get("corrected_lookup_snapshot_id"))
                )
                edge_cutoff_ts = normalize_lookup_timestamp(
                    hit.get("lookup_cutoff_ts_utc")
                )
                valid_after_ts = normalize_lookup_timestamp(
                    hit.get("lookup_valid_for_decisions_after_ts_utc")
                )
                edge_cutoff = (
                    edge_cutoff_ts.isoformat().replace("+00:00", "Z")
                    if edge_cutoff_ts
                    else None
                )
                valid_after = (
                    valid_after_ts.isoformat().replace("+00:00", "Z")
                    if valid_after_ts
                    else (
                        lookup_cutoff.isoformat().replace("+00:00", "Z")
                        if lookup_cutoff
                        else None
                    )
                )
                edge_pass, edge_rule, unknown_reason = derive_basis_aware_edge_signal(
                    edge, edge_basis, cost
                )
                if edge_rule is None and hit.get("edge_signal_rule") is not None:
                    edge_rule = str(hit.get("edge_signal_rule"))
                lookup_applied = True

                if not conf_avail:
                    eligibility = "BLOCKED_MISSING_CONFIDENCE"
                    block_reasons.append("MISSING_CONFIDENCE")
                    if not edge_avail:
                        block_reasons.append("MISSING_EXPECTED_EDGE")
                elif not edge_avail:
                    eligibility = "BLOCKED_MISSING_EXPECTED_EDGE"
                    block_reasons.append("MISSING_EXPECTED_EDGE")
                elif unknown_reason == "UNKNOWN_EDGE_BASIS":
                    eligibility = "BLOCKED_UNKNOWN_EDGE_BASIS"
                    block_reasons.append("UNKNOWN_EDGE_BASIS")
                elif edge_pass is False:
                    if edge_basis == "NET_AFTER_COST":
                        eligibility = "BLOCKED_EDGE_BELOW_NET_ZERO_THRESHOLD"
                        block_reasons.append("EDGE_BELOW_NET_ZERO_THRESHOLD")
                    else:
                        eligibility = "BLOCKED_EDGE_BELOW_COST"
                        block_reasons.append("EDGE_BELOW_COST")
                    paper_action = "NO_TRADE_EDGE_BELOW_THRESHOLD"
                else:
                    eligibility = "ELIGIBLE_DIRECTIONAL_SIGNAL"
                    if ctx_match == "LONG_CONTEXT":
                        paper_action = "INTENT_OPEN_LONG"
                        intended = "LONG"
                        order_side = "BUY"
                        position_intent = "OPEN_LONG"
                    else:
                        paper_action = "INTENT_OPEN_SHORT"
                        intended = "SHORT"
                        order_side = "SELL"
                        position_intent = "OPEN_SHORT"

    if not conf_avail:
        conf_src = conf_src or NO_CONFIDENCE_SOURCE
    if not edge_avail:
        edge_src = edge_src or NO_EXPECTED_EDGE_SOURCE

    # Legacy audit field: edge_above_cost compares to cost (not used for NET_AFTER_COST pass).
    edge_above = (float(edge) > cost) if edge_avail else None

    return {
        "decision_signal_schema_version": SIGNAL_SCHEMA_VERSION,
        "decision_age_seconds": age_seconds,
        "freshness_status": freshness,
        "confidence": conf,
        "confidence_source": conf_src,
        "confidence_available": conf_avail,
        "expected_edge_bps": edge,
        "expected_edge_source": edge_src,
        "expected_edge_available": edge_avail,
        "expected_edge_basis": edge_basis,
        "edge_signal_rule": edge_rule,
        "edge_signal_pass": edge_pass,
        "total_roundtrip_model_cost_bps": cost,
        "cost_source": cost_source,
        "cost_handling": cost_handling,
        "edge_above_cost": edge_above,
        "lookup_bucket_id": bucket_id,
        "confidence_bucket_id": bucket_id,
        "expected_edge_bucket_id": bucket_id,
        "corrected_lookup_snapshot_id": snapshot_id,
        "edge_lookup_snapshot_id": snapshot_id,
        "edge_lookup_cutoff_ts": edge_cutoff,
        "lookup_valid_for_decisions_after_ts_utc": valid_after,
        "lookup_applied": lookup_applied,
        "instrument_source": instrument_source,
        "signal_eligibility_status": eligibility,
        "signal_block_reasons": json.dumps(block_reasons, separators=(",", ":")),
        "paper_action_candidate": paper_action,
        "intended_side": intended,
        "order_side": order_side,
        "position_intent": position_intent,
        "paper_signal_write_allowed": False,
        "paper_loop_allowed": False,
        "signal_fields_patch_status": SIGNAL_FIELDS_PATCH_STATUS,
        "signal_fields_patch_mode": SIGNAL_FIELDS_PATCH_MODE,
        "signal_fields_generated_at_utc": now.isoformat().replace("+00:00", "Z"),
    }


def derive_signal_fields(
    row: dict[str, Any],
    *,
    now_utc: datetime | None = None,
    confidence: float | None = None,
    expected_edge_bps: float | None = None,
    confidence_source: str | None = None,
    expected_edge_source: str | None = None,
    lookup_df: pd.DataFrame | None = None,
    use_lookup: bool = True,
) -> dict[str, Any]:
    """Derive additive signal-readiness fields. Never invents confidence/edge.

    When use_lookup is True (default), applies corrected lookup integration.
    Explicit confidence/expected_edge kwargs still override via row merge first.
    """
    working = dict(row)
    if confidence is not None:
        working["confidence"] = confidence
    if expected_edge_bps is not None:
        working["expected_edge_bps"] = expected_edge_bps
    if confidence_source is not None:
        working["confidence_source"] = confidence_source
    if expected_edge_source is not None:
        working["expected_edge_source"] = expected_edge_source

    if use_lookup:
        frame = lookup_df
        if frame is None:
            frame = load_corrected_context_edge_lookup()
        return apply_lookup_to_signal_fields(working, frame, now_utc=now_utc)

    # Legacy non-lookup path (tests / explicit disable).
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    ts_raw = working.get("decision_written_at_utc") or working.get(
        "candle_close_time_utc"
    ) or working.get("candle_timestamp")
    ts = _parse_iso_ts(ts_raw)
    ctx, ctx_source = resolve_signal_context(working)

    stale, age_seconds, freshness = is_decision_stale_for_lookup(
        working, now_utc=now, decision_ts=ts
    )
    lifecycle_state = str(working.get("lifecycle_state") or "").strip().upper()
    observe_block = str(working.get("observe_block_reason") or "").strip().upper()
    transition_block = str(working.get("transition_block_reason") or "").strip().upper()
    stale_cognition_blocked = (
        lifecycle_state == "STALE_COGNITION"
        or observe_block in {"STALE_COGNITION", "STALE_MARKET_AND_COGNITION"}
        or transition_block in {"STALE_COGNITION", "STALE_MARKET_AND_COGNITION"}
    )
    pipeline_pending = bool(working.get("pipeline_pending")) or freshness == "PIPELINE_PENDING"

    conf = _nullable_float(working.get("confidence"))
    edge = _nullable_float(working.get("expected_edge_bps"))
    conf_avail = conf is not None
    edge_avail = edge is not None
    cost = float(DETERMINISTIC_TOTAL_ROUNDTRIP_MODEL_COST_BPS)
    edge_above = (float(edge) > cost) if edge_avail else None

    conf_src = working.get("confidence_source")
    edge_src = working.get("expected_edge_source")
    if not conf_avail:
        conf_src = conf_src or NO_CONFIDENCE_SOURCE
    if not edge_avail:
        edge_src = edge_src or NO_EXPECTED_EDGE_SOURCE

    block_reasons: list[str] = []
    eligibility = "ELIGIBLE_DIRECTIONAL_SIGNAL"
    action = "NO_TRADE_MISSING_FIELDS"
    intended = "NONE"
    order_side = "NONE"
    position_intent = "NONE"

    if ts is None and ctx is None:
        eligibility = "BLOCKED_MISSING_CONTEXT"
        block_reasons.extend(["MISSING_CONTEXT", "MISSING_TIMESTAMP"])
        action = "NO_TRADE_MISSING_FIELDS"
    elif ctx is None:
        eligibility = "BLOCKED_MISSING_CONTEXT"
        block_reasons.append("MISSING_CONTEXT")
        action = "NO_TRADE_MISSING_FIELDS"
    elif pipeline_pending:
        eligibility = "BLOCKED_PIPELINE_PENDING"
        block_reasons.append("PIPELINE_PENDING")
        action = "NO_TRADE_PIPELINE_PENDING"
        if ctx == "OBSERVE":
            block_reasons.append("OBSERVE_CONTEXT")
    elif stale_cognition_blocked:
        eligibility = "BLOCKED_STALE_COGNITION"
        block_reasons.append("STALE_COGNITION")
        action = "NO_TRADE_STALE_COGNITION"
        if stale:
            block_reasons.append("STALE_CONTEXT")
        if ctx == "OBSERVE":
            block_reasons.append("OBSERVE_CONTEXT")
        if not conf_avail:
            block_reasons.append("MISSING_CONFIDENCE")
        if not edge_avail:
            block_reasons.append("MISSING_EXPECTED_EDGE")
    elif stale:
        eligibility = "BLOCKED_STALE_CONTEXT"
        block_reasons.append("STALE_CONTEXT")
        action = "NO_TRADE_STALE_CONTEXT"
        if ctx == "OBSERVE":
            block_reasons.append("OBSERVE_CONTEXT")
        if not conf_avail:
            block_reasons.append("MISSING_CONFIDENCE")
        if not edge_avail:
            block_reasons.append("MISSING_EXPECTED_EDGE")
    elif ctx_source == "candidate_context" and ctx in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
        eligibility = "ELIGIBLE_DIRECTIONAL_SIGNAL"
        if ctx == "LONG_CONTEXT":
            action = "INTENT_OPEN_LONG"
            intended = "LONG"
            order_side = "BUY"
            position_intent = "OPEN_LONG"
        else:
            action = "INTENT_OPEN_SHORT"
            intended = "SHORT"
            order_side = "SELL"
            position_intent = "OPEN_SHORT"
    elif ctx == "OBSERVE":
        eligibility = "BLOCKED_OBSERVE_CONTEXT"
        block_reasons.append("OBSERVE_CONTEXT")
        action = "NO_TRADE_OBSERVE"
    elif ctx == "STAND_ASIDE":
        eligibility = "BLOCKED_STAND_ASIDE"
        block_reasons.append("STAND_ASIDE")
        action = "NO_TRADE_STAND_ASIDE"
    elif ctx not in {
        "LONG_CONTEXT",
        "SHORT_CONTEXT",
        "LONG_CONTEXT_REFERENCE",
        "SHORT_CONTEXT_REFERENCE",
    }:
        eligibility = "BLOCKED_NOT_DIRECTIONAL"
        block_reasons.append("NOT_DIRECTIONAL")
        action = "NO_TRADE_MISSING_FIELDS"
    elif not conf_avail:
        eligibility = "BLOCKED_MISSING_CONFIDENCE"
        block_reasons.append("MISSING_CONFIDENCE")
        action = "NO_TRADE_MISSING_FIELDS"
        if not edge_avail:
            block_reasons.append("MISSING_EXPECTED_EDGE")
    elif not edge_avail:
        eligibility = "BLOCKED_MISSING_EXPECTED_EDGE"
        block_reasons.append("MISSING_EXPECTED_EDGE")
        action = "NO_TRADE_MISSING_FIELDS"
    elif edge_above is False:
        eligibility = "BLOCKED_EDGE_BELOW_COST"
        block_reasons.append("EDGE_BELOW_COST")
        action = "NO_TRADE_EDGE_BELOW_COST"
    elif ctx in {"LONG_CONTEXT", "LONG_CONTEXT_REFERENCE"}:
        eligibility = "ELIGIBLE_DIRECTIONAL_SIGNAL"
        action = "INTENT_OPEN_LONG"
        intended = "LONG"
        order_side = "BUY"
        position_intent = "OPEN_LONG"
    else:
        eligibility = "ELIGIBLE_DIRECTIONAL_SIGNAL"
        action = "INTENT_OPEN_SHORT"
        intended = "SHORT"
        order_side = "SELL"
        position_intent = "OPEN_SHORT"

    return {
        "decision_signal_schema_version": SIGNAL_SCHEMA_VERSION,
        "decision_age_seconds": age_seconds,
        "freshness_status": freshness,
        "confidence": conf,
        "confidence_source": conf_src,
        "confidence_available": conf_avail,
        "expected_edge_bps": edge,
        "expected_edge_source": edge_src,
        "expected_edge_available": edge_avail,
        "expected_edge_basis": None,
        "edge_signal_rule": None,
        "edge_signal_pass": None,
        "total_roundtrip_model_cost_bps": cost,
        "cost_source": DETERMINISTIC_COST_SOURCE,
        "cost_handling": None,
        "edge_above_cost": edge_above,
        "lookup_bucket_id": None,
        "confidence_bucket_id": None,
        "expected_edge_bucket_id": None,
        "corrected_lookup_snapshot_id": None,
        "edge_lookup_snapshot_id": None,
        "edge_lookup_cutoff_ts": None,
        "lookup_valid_for_decisions_after_ts_utc": None,
        "lookup_applied": False,
        "instrument_source": None,
        "signal_eligibility_status": eligibility,
        "signal_block_reasons": json.dumps(block_reasons, separators=(",", ":")),
        "paper_action_candidate": action,
        "intended_side": intended,
        "order_side": order_side,
        "position_intent": position_intent,
        "paper_signal_write_allowed": False,
        "paper_loop_allowed": False,
        "signal_fields_patch_status": SIGNAL_FIELDS_PATCH_STATUS,
        "signal_fields_patch_mode": SIGNAL_FIELDS_PATCH_MODE,
        "signal_fields_generated_at_utc": now.isoformat().replace("+00:00", "Z"),
    }


def apply_signal_fields(
    row: dict[str, Any],
    *,
    now_utc: datetime | None = None,
    confidence: float | None = None,
    expected_edge_bps: float | None = None,
    lookup_df: pd.DataFrame | None = None,
    lookup_path: Path | str | None = None,
    use_lookup: bool = True,
) -> dict[str, Any]:
    """Attach additive signal fields to a decision row (no mutation of base fields)."""
    out = dict(row)
    frame = lookup_df
    if use_lookup and frame is None:
        frame = load_corrected_context_edge_lookup(lookup_path)
    signal = derive_signal_fields(
        out,
        now_utc=now_utc,
        confidence=confidence,
        expected_edge_bps=expected_edge_bps,
        lookup_df=frame,
        use_lookup=use_lookup,
    )
    out.update(signal)
    return out



def _directional_label(value: Any) -> str | None:
    text = _clean(value, default="")
    if text in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
        return text
    return None


def _lookup_lifecycle_episode(decision_candle: pd.Timestamp, life_row: pd.Series) -> dict[str, Any]:
    """Map decision candle to lifecycle episode ids/times (read-only)."""
    empty = {
        "lifecycle_episode_id": None,
        "lifecycle_episode_start_time": None,
        "lifecycle_episode_end_time": None,
    }
    ep_path = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"
    if not ep_path.exists():
        return empty
    try:
        eps = pd.read_parquet(ep_path)
    except Exception:
        return empty
    if eps.empty or "start_time" not in eps.columns:
        return empty
    tmp = eps.copy()
    tmp["_start"] = pd.to_datetime(tmp["start_time"], utc=True, errors="coerce")
    tmp["_end"] = pd.to_datetime(tmp["end_time"], utc=True, errors="coerce")
    ctx = _clean(life_row.get("active_market_context"), default="")
    if ctx not in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
        cand = _directional_label(life_row.get("candidate_context"))
        ctx = cand or ctx
    hit = tmp[
        (tmp["active_market_context"].map(lambda x: _clean(x, default="")) == ctx)
        & (tmp["_start"] <= decision_candle)
        & ((tmp["_end"].isna()) | (tmp["_end"] >= decision_candle))
    ]
    if hit.empty:
        hit = tmp[tmp["_start"] == decision_candle]
    if hit.empty:
        return empty
    row = hit.sort_values("_start").iloc[-1]
    eid = row.get("episode_id")
    return {
        "lifecycle_episode_id": None if eid is None or pd.isna(eid) else int(eid),
        "lifecycle_episode_start_time": _iso(row.get("_start")),
        "lifecycle_episode_end_time": _iso(row.get("_end")),
    }


def _derive_decision_start_fields(
    *,
    life_row: pd.Series,
    decision_candle: pd.Timestamp,
    previous_active: str | None,
) -> dict[str, Any]:
    active = _directional_label(life_row.get("active_market_context"))
    candidate = _directional_label(life_row.get("candidate_context"))
    cand_started = _to_utc_ts(life_row.get("candidate_started_at"))
    active_started = _to_utc_ts(life_row.get("active_context_started_at"))
    episode_start = _to_utc_ts(life_row.get("lifecycle_episode_start_time"))
    age = _safe_int(life_row.get("active_context_age_bars"), default=None)

    exported_active = _clean(life_row.get("active_market_context"), default="OBSERVE")
    if active:
        exported_active = active

    prev = _clean(previous_active, default="") if previous_active else _clean(
        life_row.get("previous_active_market_context"), default=""
    )
    if not prev or prev in {"UNKNOWN", "NAN", "NONE", "NULL", "<NA>"}:
        prev = "NONE"

    effective_current = active or candidate
    start = False
    source = None
    if bool(life_row.get("context_start_event")) is True:
        start = True
        source = "decision_log.context_start_event"
    if not start and episode_start is not None and episode_start == decision_candle and effective_current:
        start = True
        source = "lifecycle_episode_start_time"
    if not start and cand_started is not None and cand_started == decision_candle and candidate:
        start = True
        source = "candidate_started_at"
    if not start and active_started is not None and active_started == decision_candle and active:
        if cand_started is None or cand_started == decision_candle:
            start = True
            source = "active_context_started_at"
    if not start and effective_current and prev != effective_current:
        if age == 0 or (active_started is not None and active_started == decision_candle) or (
            cand_started is not None and cand_started == decision_candle
        ):
            start = True
            source = "previous_active_context_differs"

    flip = bool(
        prev in {"LONG_CONTEXT", "SHORT_CONTEXT"}
        and effective_current in {"LONG_CONTEXT", "SHORT_CONTEXT"}
        and prev != effective_current
    )
    end_event = bool(
        prev in {"LONG_CONTEXT", "SHORT_CONTEXT"}
        and (
            effective_current is None
            or exported_active in {"OBSERVE", "NO_ACTIVE_CONTEXT"}
            or flip
        )
    )
    return {
        "active_market_context": exported_active,
        "candidate_context": candidate,
        "candidate_started_at": _iso(cand_started),
        "active_context_started_at": _iso(active_started),
        "previous_active_market_context": None if prev == "UNKNOWN" else prev,
        "transition_reason": _clean(life_row.get("transition_reason"), default="NONE"),
        "context_start_event": bool(start),
        "context_start_event_source": source,
        "directional_flip_detected": bool(flip),
        "context_end_event": bool(end_event),
    }


def _asof_source_timestamp(frame: pd.DataFrame, ts: pd.Timestamp) -> pd.Timestamp | None:
    """Point-in-time source timestamp at/before ts (no forward fabrication)."""
    row = row_at_timestamp(frame, ts)
    if row is None:
        return None
    if "timestamp" in getattr(row, "index", []):
        return _to_utc_ts(row.get("timestamp"))
    return _to_utc_ts(ts)


def build_decision_row(
    *,
    live: pd.DataFrame,
    auction: pd.DataFrame,
    cognitive: pd.DataFrame,
    final: pd.DataFrame,
    lifecycle: pd.DataFrame,
    runtime: dict[str, Any],
    source_hash: str,
    written_at: pd.Timestamp | None = None,
    runtime_pid: int | None = None,
    previous_decision: dict[str, Any] | None = None,
    decision_candle: Any | None = None,
    point_in_time: bool = False,
    record_origin: str = RECORD_ORIGIN_LIVE,
) -> dict[str, Any]:
    """Build one decision row without writing to disk.

    Live tip mode (default): decision refers to latest lifecycle bar; freshness
    compares current live vs lifecycle tip.

    Point-in-time / historical backfill mode: decision refers to an explicit
    lifecycle timestamp; freshness axes are aligned to that bar so historical
    live-ahead does not mark the row PIPELINE_PENDING.
    """
    lifecycle_tip = latest_timestamp(lifecycle)
    live_tip = latest_timestamp(live)

    if lifecycle_tip is None:
        raise DecisionLoggerError("Lifecycle memory has no usable timestamp")
    if live_tip is None and not point_in_time:
        raise DecisionLoggerError("Live feed has no usable timestamp")

    if decision_candle is None:
        candle = lifecycle_tip
    else:
        candle = _to_utc_ts(decision_candle)
        if candle is None:
            raise DecisionLoggerError(f"Invalid decision_candle: {decision_candle!r}")

    life_row = row_at_timestamp(lifecycle, candle)
    if life_row is None:
        raise DecisionLoggerError(f"No lifecycle row for decision candle {candle}")

    auction_row = row_at_timestamp(auction, candle)
    cognitive_row = row_at_timestamp(cognitive, candle)
    final_row = row_at_timestamp(final, candle)

    if point_in_time:
        # Historical semantics: all freshness axes equal the closed lifecycle bar.
        lifecycle_ts = candle
        live_ts = candle
        auction_ts = _asof_source_timestamp(auction, candle) or candle
        cognitive_ts = _asof_source_timestamp(cognitive, candle) or candle
        final_ts = _asof_source_timestamp(final, candle) or candle
    else:
        lifecycle_ts = lifecycle_tip
        live_ts = live_tip
        auction_ts = latest_timestamp(auction)
        cognitive_ts = latest_timestamp(cognitive)
        final_ts = latest_timestamp(final)
        # Live tip append always decides on the latest completed lifecycle bar.
        candle = lifecycle_ts

    written = written_at or pd.Timestamp.now(tz="UTC")
    if written.tzinfo is None:
        written = written.tz_localize("UTC")
    else:
        written = written.tz_convert("UTC")
    freshness = classify_decision_freshness(
        decision_market_ts=candle,
        lifecycle_ts=lifecycle_ts,
        live_ts=live_ts,
        now_utc=written.to_pydatetime(),
    )
    stale = bool(freshness["decision_stale"])
    lag_present = bool(freshness["technical_refresh_lag_present"])
    pipeline_pending = bool(freshness["pipeline_pending"])

    # Prefer explicit close time = timestamp + 15m for closed candle semantics.
    candle_close_time = pd.Timestamp(candle) + pd.Timedelta(minutes=15)

    prev_active = None
    if previous_decision:
        prev_active = previous_decision.get("active_market_context") or previous_decision.get(
            "candidate_context"
        )
    else:
        prev_active = life_row.get("previous_active_market_context")

    ep_meta = _lookup_lifecycle_episode(pd.Timestamp(candle), life_row)
    life_view = life_row.copy()
    if ep_meta.get("lifecycle_episode_start_time"):
        life_view["lifecycle_episode_start_time"] = ep_meta["lifecycle_episode_start_time"]
    start_fields = _derive_decision_start_fields(
        life_row=life_view,
        decision_candle=pd.Timestamp(candle),
        previous_active=str(prev_active) if prev_active is not None else None,
    )

    origin = str(record_origin or RECORD_ORIGIN_LIVE).upper()
    backfilled_at = _iso(written) if origin == RECORD_ORIGIN_BACKFILL else None

    row: dict[str, Any] = {
        "decision_id": str(uuid.uuid4()),
        "decision_written_at_utc": _iso(written),
        "candle_timestamp": _iso(candle),
        "candle_close_time_utc": _iso(candle_close_time),
        "source_timeframe": SOURCE_TIMEFRAME,
        "runtime_pid": runtime_pid if runtime_pid is not None else os.getpid(),
        "pipeline_cycle": runtime.get("pipeline_cycle"),
        "runtime_segments": runtime.get("runtime_segments"),
        "total_runtime_log_cycles": runtime.get("total_runtime_log_cycles"),
        "live_feed_latest_timestamp": _iso(live_ts),
        "auction_latest_timestamp": _iso(auction_ts),
        "cognitive_latest_timestamp": _iso(cognitive_ts),
        "final_context_latest_timestamp": _iso(final_ts),
        "lifecycle_latest_timestamp": _iso(lifecycle_ts),
        "live_to_auction_lag_seconds": _lag_seconds(live_ts, auction_ts),
        "live_to_cognitive_lag_seconds": _lag_seconds(live_ts, cognitive_ts),
        "live_to_final_context_lag_seconds": _lag_seconds(live_ts, final_ts),
        "live_to_lifecycle_lag_seconds": _lag_seconds(live_ts, lifecycle_ts),
        "decision_lag_vs_live_seconds": _lag_seconds(live_ts, candle),
        "decision_lag_vs_lifecycle_seconds": _lag_seconds(candle, lifecycle_ts),
        "auction_episode": _clean(
            (auction_row.get("auction_episode") if auction_row is not None else None)
            or life_row.get("raw_auction_episode")
        ),
        "auction_episode_status": _clean(
            (auction_row.get("episode_status") if auction_row is not None else None)
            or (auction_row.get("auction_episode_status") if auction_row is not None else None),
            default="UNKNOWN",
        ),
        "cognitive_market_state": _clean(
            (cognitive_row.get("cognitive_market_state") if cognitive_row is not None else None)
            or life_row.get("raw_cognitive_market_state")
        ),
        "cognitive_state_status": _clean(
            (cognitive_row.get("state_status") if cognitive_row is not None else None)
            or (cognitive_row.get("cognitive_state_status") if cognitive_row is not None else None),
            default="UNKNOWN",
        ),
        "cognitive_state_direction": _clean(
            (cognitive_row.get("state_direction") if cognitive_row is not None else None)
            or life_row.get("raw_state_direction"),
            default="UNKNOWN",
        ),
        "raw_market_context": _clean(
            life_row.get("raw_market_context")
            or (final_row.get("market_context") if final_row is not None else None),
            default="OBSERVE",
        ),
        "raw_context_status": _clean(
            life_row.get("raw_context_status")
            or (final_row.get("context_status") if final_row is not None else None),
            default="UNKNOWN",
        ),
        "active_market_context": start_fields["active_market_context"],
        "lifecycle_state": _clean(life_row.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT"),
        "active_context_age_bars": _safe_int(life_row.get("active_context_age_bars"), default=0),
        "active_context_started_at": start_fields["active_context_started_at"],
        "lifecycle_episode_id": ep_meta.get("lifecycle_episode_id"),
        "lifecycle_episode_start_time": ep_meta.get("lifecycle_episode_start_time"),
        "lifecycle_episode_end_time": ep_meta.get("lifecycle_episode_end_time"),
        "candidate_context": start_fields["candidate_context"],
        "candidate_started_at": start_fields["candidate_started_at"],
        "previous_active_market_context": start_fields["previous_active_market_context"],
        "transition_reason": start_fields["transition_reason"],
        "lifecycle_state_reason": _clean(
            life_row.get("lifecycle_state_reason") or life_row.get("transition_reason"),
            default="NONE",
        ),
        "state_entered_at": _iso(_to_utc_ts(life_row.get("state_entered_at"))),
        "state_age_minutes": _nullable_float(life_row.get("state_age_minutes")),
        "transition_block_reason": _clean(
            life_row.get("transition_block_reason"),
            default="NONE",
        ),
        "cognition_state_age_minutes": _nullable_float(
            life_row.get("cognition_state_age_minutes")
        ),
        "upstream_cognition_freshness_minutes": _nullable_float(
            life_row.get("upstream_cognition_freshness_minutes")
        ),
        "market_feed_age_minutes": _nullable_float(life_row.get("market_feed_age_minutes")),
        "market_activity_score": _nullable_float(life_row.get("market_activity_score")),
        "observe_escape_candidate": bool(life_row.get("observe_escape_candidate"))
        if life_row.get("observe_escape_candidate") is not None
        else False,
        "observe_block_reason": _clean(life_row.get("observe_block_reason"), default="NONE"),
        # Phase-1 origin diagnostics from point-in-time lifecycle row (never a fill price).
        "context_origin_price": _nullable_float(life_row.get("context_origin_price")),
        # Canonical nullable UTC timestamp, not an ISO string: the persisted
        # parquet column is timestamp[us, tz=UTC] and a string here makes the
        # concat fall back to object dtype, which Arrow cannot write.
        "context_entered_at": _to_utc_ts(life_row.get("context_entered_at")),
        "context_episode_id": _safe_int(
            life_row.get("context_episode_id")
            if life_row.get("context_episode_id") is not None
            else ep_meta.get("lifecycle_episode_id")
        ),
        "context_direction": (
            _clean(life_row.get("context_direction"), default="")
            if life_row.get("context_direction") not in (None, "")
            else (
                _clean(life_row.get("active_market_context"), default="")
                if _clean(life_row.get("active_market_context"), default="")
                in {"LONG_CONTEXT", "SHORT_CONTEXT"}
                else None
            )
        ),
        "context_distance_bps": _nullable_float(life_row.get("context_distance_bps")),
        "context_favorable_distance_bps": _nullable_float(
            life_row.get("context_favorable_distance_bps")
        ),
        "context_adverse_distance_bps": _nullable_float(
            life_row.get("context_adverse_distance_bps")
        ),
        "context_start_event": start_fields["context_start_event"],
        "context_start_event_source": start_fields["context_start_event_source"],
        "directional_flip_detected": start_fields["directional_flip_detected"],
        "context_end_event": start_fields["context_end_event"],
        "invalidation_type": _clean(life_row.get("invalidation_type"), default="NONE"),
        "technical_refresh_lag_present": lag_present,
        "pipeline_pending": pipeline_pending,
        "decision_stale": stale,
        "decision_freshness_status": freshness["decision_freshness_status"],
        "decision_stale_reason": freshness["decision_stale_reason"],
        "source_files_hash": source_hash,
        "schema_version": SCHEMA_VERSION,
        "logger_version": LOGGER_VERSION,
        "record_origin": origin,
        "backfilled_at_utc": backfilled_at,
    }
    # Normalize empty context_direction to None for OBSERVE/non-directional rows.
    if not row.get("context_direction"):
        row["context_direction"] = None
    row = enforce_safety_fields(row)
    row["decision_payload_hash"] = decision_payload_hash(row)
    # Additive signal fields; never invent confidence/expected_edge.
    row = apply_signal_fields(row, now_utc=written.to_pydatetime())
    return row


def build_context_decision_row(**kwargs: Any) -> dict[str, Any]:
    """Canonical single-row builder shared by live append, dry-run, and backfill."""
    return build_decision_row(**kwargs)


def load_decision_log(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=DECISION_COLUMNS)
    frame = pd.read_parquet(path)
    # Normalize timestamp-like string columns for comparisons.
    return frame


def write_atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        frame.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


"""Columns persisted as Arrow ``timestamp[us, tz=UTC]`` rather than as strings.

Every other temporal field in this log is stored as an ISO string; these are the
exceptions, so a value reaching the writer as a string silently degrades the
column to object dtype and breaks the Arrow conversion.
"""
CANONICAL_TIMESTAMP_COLUMNS: tuple[str, ...] = ("context_entered_at",)

CANONICAL_TIMESTAMP_DTYPE = "datetime64[us, UTC]"


def coerce_utc_timestamp_series(values: Any, column: str) -> pd.Series:
    """Coerce a column to nullable UTC timestamps, failing closed on garbage.

    Each value is parsed on its own so that mixed precision (with and without
    microseconds) cannot make pandas infer one format from the first element and
    coerce every other value to NaT.
    """
    parsed: list[Any] = []
    for value in values:
        if value is None:
            parsed.append(pd.NaT)
            continue
        if isinstance(value, str):
            if not value.strip():
                parsed.append(pd.NaT)
                continue
            timestamp = pd.to_datetime(value, utc=True, errors="coerce", format="ISO8601")
        else:
            try:
                if pd.isna(value):
                    parsed.append(pd.NaT)
                    continue
            except (TypeError, ValueError):
                pass
            timestamp = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(timestamp):
            raise DecisionLoggerError(
                f"INVALID_TIMESTAMP: column={column} value={value!r} "
                "is not a parseable ISO-8601 UTC timestamp"
            )
        parsed.append(timestamp)
    index = values.index if isinstance(values, pd.Series) else None
    return pd.Series(parsed, dtype=CANONICAL_TIMESTAMP_DTYPE, index=index)


def normalize_canonical_timestamp_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the canonical timestamp dtype to a frame about to be persisted."""
    for column in CANONICAL_TIMESTAMP_COLUMNS:
        if column in frame.columns:
            frame[column] = coerce_utc_timestamp_series(frame[column], column)
    return frame


def normalize_utc_ns_series(values: Any) -> pd.Series:
    """Normalize timestamps to datetime64[ns, UTC]; NaT dropped by callers."""
    series = pd.to_datetime(values, utc=True, errors="coerce")
    if not isinstance(series, pd.Series):
        series = pd.Series(series)
    # Force ns UTC for gap detection across ns/us parquet sources.
    out = series.dt.tz_convert("UTC") if series.dt.tz is not None else series.dt.tz_localize("UTC")
    try:
        return out.astype("datetime64[ns, UTC]")
    except (TypeError, ValueError):
        return pd.to_datetime(out, utc=True).astype("datetime64[ns, UTC]")


def unique_lifecycle_timestamps(lifecycle: pd.DataFrame) -> list[pd.Timestamp]:
    if lifecycle is None or len(lifecycle) == 0 or "timestamp" not in lifecycle.columns:
        return []
    series = normalize_utc_ns_series(lifecycle["timestamp"]).dropna()
    if len(series) == 0:
        return []
    # Deterministic: keep last occurrence order by sorting unique values.
    uniq = sorted(series.unique())
    return [pd.Timestamp(ts) for ts in uniq]


def decision_candle_timestamps(decision_log: pd.DataFrame) -> set[pd.Timestamp]:
    if decision_log is None or len(decision_log) == 0 or "candle_timestamp" not in decision_log.columns:
        return set()
    series = normalize_utc_ns_series(decision_log["candle_timestamp"]).dropna()
    return {pd.Timestamp(ts) for ts in series.unique()}


def find_missing_lifecycle_timestamps(
    lifecycle: pd.DataFrame,
    decision_log: pd.DataFrame,
    *,
    from_timestamp: Any | None = None,
    to_timestamp: Any | None = None,
) -> list[pd.Timestamp]:
    """Return lifecycle timestamps with no decision row (NaT excluded)."""
    life_ts = unique_lifecycle_timestamps(lifecycle)
    have = decision_candle_timestamps(decision_log)
    lo = _to_utc_ts(from_timestamp)
    hi = _to_utc_ts(to_timestamp)
    missing: list[pd.Timestamp] = []
    for ts in life_ts:
        if ts in have:
            continue
        if lo is not None and ts < lo:
            continue
        if hi is not None and ts > hi:
            continue
        missing.append(ts)
    return missing


def gap_intervals(timestamps: list[pd.Timestamp]) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    if not timestamps:
        return []
    ordered = sorted(timestamps)
    out: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    start = prev = ordered[0]
    for ts in ordered[1:]:
        if ts - prev == pd.Timedelta(minutes=15):
            prev = ts
            continue
        n = int((prev - start) / pd.Timedelta(minutes=15)) + 1
        out.append((start, prev, n))
        start = prev = ts
    n = int((prev - start) / pd.Timedelta(minutes=15)) + 1
    out.append((start, prev, n))
    return out


def _align_frame_to_schema(frame: pd.DataFrame) -> pd.DataFrame:
    aligned = frame.copy()
    for col in DECISION_COLUMNS:
        if col not in aligned.columns:
            aligned[col] = None
    # Preserve any unexpected legacy columns after schema columns.
    extra = [c for c in aligned.columns if c not in DECISION_COLUMNS]
    return aligned[DECISION_COLUMNS + extra]


def merge_decision_frames_preserving_existing(
    existing: pd.DataFrame,
    new_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    """Existing rows win on candle_timestamp; output sorted by candle_timestamp."""
    if not new_rows:
        if len(existing) == 0:
            return pd.DataFrame(columns=DECISION_COLUMNS)
        out = _align_frame_to_schema(existing)
    else:
        new_frame = pd.DataFrame(new_rows)
        for col in DECISION_COLUMNS:
            if col not in new_frame.columns:
                new_frame[col] = None
        if len(existing) == 0:
            out = new_frame
        else:
            existing_aligned = _align_frame_to_schema(existing)
            # Existing first so drop_duplicates keeps original rows.
            out = pd.concat([existing_aligned, new_frame], ignore_index=True, sort=False)
    out = _align_frame_to_schema(out)
    out["_sort_ts"] = normalize_utc_ns_series(out["candle_timestamp"])
    # Keep first occurrence (= existing) for duplicate timestamps.
    out = out.sort_values(["_sort_ts", "decision_written_at_utc"], kind="mergesort")
    out = out.drop_duplicates(subset=["_sort_ts"], keep="first")
    out = out.sort_values("_sort_ts", kind="mergesort").drop(columns=["_sort_ts"])
    return out.reset_index(drop=True)


def backfill_missing_decisions(
    *,
    log_path: Path = DECISION_LOG_PATH,
    output_path: Path | None = None,
    dry_run: bool = False,
    from_timestamp: Any | None = None,
    to_timestamp: Any | None = None,
    max_rows: int | None = None,
    live_path: Path = LIVE_FEED,
    auction_path: Path = AUCTION_PATH,
    cognitive_path: Path = COGNITIVE_PATH,
    final_path: Path = FINAL_PATH,
    lifecycle_path: Path = LIFECYCLE_PATH,
    runtime_log_path: Path = RUNTIME_LOG,
    default_from_existing_min: bool = True,
) -> dict[str, Any]:
    """Idempotent missing-row backfill using the same builder as live append.

    Does not rewrite existing decision rows. Point-in-time freshness prevents
    historical live-ahead from marking restored rows PIPELINE_PENDING.
    """
    missing_sources = [
        p for p in (live_path, auction_path, cognitive_path, final_path, lifecycle_path) if not p.exists()
    ]
    if missing_sources:
        raise DecisionLoggerError(
            "Missing required source files: " + ", ".join(str(p) for p in missing_sources)
        )

    live = load_parquet(live_path)
    auction = load_parquet(auction_path)
    cognitive = load_parquet(cognitive_path)
    final = load_parquet(final_path)
    lifecycle = load_parquet(lifecycle_path)
    runtime = parse_runtime_cycles(runtime_log_path)
    src_hash = source_files_hash(
        [live_path, auction_path, cognitive_path, final_path, lifecycle_path]
    )
    existing = load_decision_log(log_path)

    # Duplicate lifecycle timestamps: fail-safe (do not write production).
    if "timestamp" in lifecycle.columns:
        life_norm = normalize_utc_ns_series(lifecycle["timestamp"])
        dup_count = int(life_norm.dropna().duplicated().sum())
        if dup_count > 0:
            raise DecisionLoggerError(
                f"LIFECYCLE_DUPLICATE_TIMESTAMPS: count={dup_count}; refusing backfill write"
            )

    effective_from = from_timestamp
    if effective_from is None and default_from_existing_min and len(existing):
        existing_ts = normalize_utc_ns_series(existing["candle_timestamp"]).dropna()
        if len(existing_ts):
            effective_from = existing_ts.min()

    missing = find_missing_lifecycle_timestamps(
        lifecycle,
        existing,
        from_timestamp=effective_from,
        to_timestamp=to_timestamp,
    )
    if max_rows is not None:
        missing = missing[: max(0, int(max_rows))]

    written_at = pd.Timestamp.now(tz="UTC")
    new_rows: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    if len(existing):
        tmp = existing.copy()
        tmp["_ts"] = normalize_utc_ns_series(tmp["candle_timestamp"])
        tmp = tmp.sort_values("_ts")
        if len(tmp):
            previous = tmp.iloc[-1].to_dict()

    for ts in missing:
        row = build_context_decision_row(
            live=live,
            auction=auction,
            cognitive=cognitive,
            final=final,
            lifecycle=lifecycle,
            runtime=runtime,
            source_hash=src_hash,
            written_at=written_at,
            previous_decision=previous,
            decision_candle=ts,
            point_in_time=True,
            record_origin=RECORD_ORIGIN_BACKFILL,
        )
        new_rows.append(row)
        previous = row

    combined = merge_decision_frames_preserving_existing(existing, new_rows)
    target = output_path or log_path
    intervals = gap_intervals(missing)

    result: dict[str, Any] = {
        "status": "DRY_RUN" if dry_run else ("BACKFILLED" if new_rows else "NOOP"),
        "dry_run": bool(dry_run),
        "log_path": str(log_path),
        "output_path": str(target),
        "rows_before": int(len(existing)),
        "rows_after": int(len(combined)),
        "missing_before": int(
            len(
                find_missing_lifecycle_timestamps(
                    lifecycle,
                    existing,
                    from_timestamp=effective_from,
                    to_timestamp=to_timestamp,
                )
            )
        ),
        "missing_selected": int(len(missing)),
        "rows_added": int(len(new_rows)),
        "from_timestamp": _iso(_to_utc_ts(effective_from)),
        "to_timestamp": _iso(_to_utc_ts(to_timestamp)),
        "gap_intervals": [
            {"start": _iso(a), "end": _iso(b), "bars": n} for a, b, n in intervals
        ],
        "candidate_candle_timestamps": [_iso(ts) for ts in missing],
        "action_allowed": False,
        "shadow_only": True,
        "execution_enabled": False,
        "visual_json_used": False,
    }

    if dry_run:
        result["candidate_preview_rows"] = len(new_rows)
        return result

    write_atomic_parquet(combined, target)
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from runtime_dataset_metadata import emit_metadata_for_path

        # Patch 1 metadata only — never alters decision payload semantics.
        emit_metadata_for_path(
            "data/live/context_decision_log.parquet",
            root=ROOT,
            metadata_origin="LIVE_WRITER",
        )
    except Exception as _meta_exc:  # noqa: BLE001
        print(f"METADATA_WARN decision_log sidecar: {_meta_exc}")
    # Post-write missing count in selected window against written target.
    written = load_decision_log(target)
    result["missing_after"] = int(
        len(
            find_missing_lifecycle_timestamps(
                lifecycle,
                written,
                from_timestamp=effective_from,
                to_timestamp=to_timestamp,
            )
        )
    )
    result["unique_candle_timestamps"] = int(
        normalize_utc_ns_series(written["candle_timestamp"]).dropna().nunique()
    )
    return result


def append_decision(
    row: dict[str, Any],
    *,
    log_path: Path,
) -> dict[str, Any]:
    """Append-only write. Never mutates existing decision rows."""
    existing = load_decision_log(log_path)
    candle = row["candle_timestamp"]
    new_hash = row["decision_payload_hash"]
    if row.get("record_origin") is None:
        row = dict(row)
        row["record_origin"] = RECORD_ORIGIN_LIVE

    if len(existing) and "candle_timestamp" in existing.columns:
        # Preserve existing rows exactly; compare by candle_timestamp string.
        same = existing.loc[existing["candle_timestamp"].astype(str) == str(candle)]
        if len(same):
            old_hash = str(same.iloc[-1].get("decision_payload_hash") or "")
            if old_hash == new_hash:
                return {
                    "status": "SKIPPED_DUPLICATE",
                    "candle_timestamp": candle,
                    "rows_before": len(existing),
                    "rows_after": len(existing),
                    "decision_id": None,
                }
            raise DecisionLoggerError(
                f"MUTATION_CONFLICT: candle_timestamp={candle} already logged "
                f"with different decision_payload_hash "
                f"(existing={old_hash[:12]}… new={new_hash[:12]}…)"
            )

        # Only append if newer than latest logged candle.
        latest_logged = existing["candle_timestamp"].dropna().astype(str)
        if len(latest_logged):
            latest_ts = max(_to_utc_ts(v) for v in latest_logged if _to_utc_ts(v) is not None)
            new_ts = _to_utc_ts(candle)
            if latest_ts is not None and new_ts is not None and new_ts <= latest_ts:
                return {
                    "status": "SKIPPED_NOT_NEWER",
                    "candle_timestamp": candle,
                    "latest_logged": _iso(latest_ts),
                    "rows_before": len(existing),
                    "rows_after": len(existing),
                    "decision_id": None,
                }

    new_frame = pd.DataFrame([row], columns=DECISION_COLUMNS)
    if len(existing):
        # Reindex to schema; keep all previous values untouched.
        for col in DECISION_COLUMNS:
            if col not in existing.columns:
                existing[col] = None
        combined = pd.concat([existing[DECISION_COLUMNS], new_frame], ignore_index=True)
    else:
        combined = new_frame

    combined = normalize_canonical_timestamp_columns(combined)
    write_atomic_parquet(combined, log_path)
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from runtime_dataset_metadata import emit_metadata_for_path

        emit_metadata_for_path(
            "data/live/context_decision_log.parquet",
            root=ROOT,
            metadata_origin="LIVE_WRITER",
        )
    except Exception as _meta_exc:  # noqa: BLE001
        print(f"METADATA_WARN decision_log sidecar: {_meta_exc}")
    return {
        "status": "APPENDED",
        "candle_timestamp": candle,
        "rows_before": len(existing),
        "rows_after": len(combined),
        "decision_id": row["decision_id"],
        "decision_stale": bool(row.get("decision_stale")),
        "technical_refresh_lag_present": bool(row.get("technical_refresh_lag_present")),
        "decision_payload_hash": new_hash,
    }


def run_once(
    *,
    log_path: Path = DECISION_LOG_PATH,
    live_path: Path = LIVE_FEED,
    auction_path: Path = AUCTION_PATH,
    cognitive_path: Path = COGNITIVE_PATH,
    final_path: Path = FINAL_PATH,
    lifecycle_path: Path = LIFECYCLE_PATH,
    runtime_log_path: Path = RUNTIME_LOG,
) -> dict[str, Any]:
    missing = [p for p in (live_path, auction_path, cognitive_path, final_path, lifecycle_path) if not p.exists()]
    if missing:
        raise DecisionLoggerError(
            "Missing required source files: " + ", ".join(str(p) for p in missing)
        )

    live = load_parquet(live_path)
    auction = load_parquet(auction_path)
    cognitive = load_parquet(cognitive_path)
    final = load_parquet(final_path)
    lifecycle = load_parquet(lifecycle_path)
    runtime = parse_runtime_cycles(runtime_log_path)
    src_hash = source_files_hash(
        [live_path, auction_path, cognitive_path, final_path, lifecycle_path]
    )

    # Optional shadow status is diagnostic only — never a decision source.
    shadow_present = SHADOW_STATUS.exists()

    row = build_context_decision_row(
        live=live,
        auction=auction,
        cognitive=cognitive,
        final=final,
        lifecycle=lifecycle,
        runtime=runtime,
        source_hash=src_hash,
        record_origin=RECORD_ORIGIN_LIVE,
    )
    result = append_decision(row, log_path=log_path)
    result.update(
        {
            "shadow_status_present": shadow_present,
            "visual_json_used": False,
            "log_path": str(log_path),
            "action_allowed": False,
            "shadow_only": True,
            "execution_enabled": False,
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append-only shadow context decision logger")
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DECISION_LOG_PATH,
        help="Append-only decision log parquet path",
    )
    parser.add_argument(
        "--backfill-missing",
        action="store_true",
        help="Fill missing lifecycle timestamps (idempotent; does not rewrite existing rows)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute backfill candidates without writing",
    )
    parser.add_argument(
        "--from-timestamp",
        type=str,
        default=None,
        help="Inclusive UTC lower bound for backfill window",
    )
    parser.add_argument(
        "--to-timestamp",
        type=str,
        default=None,
        help="Inclusive UTC upper bound for backfill window",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Maximum number of missing timestamps to backfill",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="Write candidate/combined log to this path (default: --log-path)",
    )
    args = parser.parse_args(argv)
    try:
        if args.backfill_missing:
            result = backfill_missing_decisions(
                log_path=args.log_path,
                output_path=args.output_path,
                dry_run=bool(args.dry_run),
                from_timestamp=args.from_timestamp,
                to_timestamp=args.to_timestamp,
                max_rows=args.max_rows,
            )
        else:
            if args.dry_run or args.from_timestamp or args.to_timestamp or args.max_rows is not None:
                print(
                    "ERROR: --dry-run/--from-timestamp/--to-timestamp/--max-rows "
                    "require --backfill-missing",
                    file=sys.stderr,
                )
                return 1
            result = run_once(log_path=args.log_path)
            if args.output_path is not None and args.output_path != args.log_path:
                print(
                    "ERROR: --output-path without --backfill-missing is unsupported",
                    file=sys.stderr,
                )
                return 1
    except DecisionLoggerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if "MUTATION_CONFLICT" in str(exc):
            return 2
        return 1

    title = (
        "CONTEXT DECISION LOGGER BACKFILL (shadow-only)"
        if args.backfill_missing
        else "CONTEXT DECISION LOGGER (shadow-only)"
    )
    print(f"======== {title} ========")
    keys = (
        "status",
        "candle_timestamp",
        "decision_id",
        "rows_before",
        "rows_after",
        "rows_added",
        "missing_before",
        "missing_selected",
        "missing_after",
        "from_timestamp",
        "to_timestamp",
        "decision_stale",
        "technical_refresh_lag_present",
        "visual_json_used",
        "execution_enabled",
        "dry_run",
        "log_path",
        "output_path",
    )
    for key in keys:
        if key in result:
            print(f"{key}: {result.get(key)}")
    if result.get("gap_intervals"):
        print(f"gap_intervals: {json.dumps(result['gap_intervals'])}")
    print(
        "NOTE: This logger records shadow-only market context decisions. "
        "It does not enable execution and must not be used to place orders."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
