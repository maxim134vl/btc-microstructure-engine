#!/usr/bin/env python3
"""Standalone shadow builder: market context lifecycle memory + episodes.

Converts choppy per-bar market_context into a stable active_market_context
lifecycle without TTL / N-bar rules / trade-policy rewriting.

Auction-based invalidation can close a directional context when OBSERVE
confluence with BALANCE / NEUTRAL auction+cognitive thesis rejection appears.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BUILDER_VERSION = "market_context_lifecycle_memory_v2_origin_continuation_diag"
INPUT_PATH = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
AUCTION_PATH = ROOT / "data" / "cognition" / "auction_episode_memory.parquet"
COGNITION_PATH = ROOT / "data" / "cognition" / "runtime_cognition_memory.parquet"
# Per-bar cognition-chain heartbeat (evaluation cadence). Runtime cognition itself is a sparse event log.
COGNITION_EVALUATION_PATH = ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet"
MEMORY_OUTPUT_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
EPISODES_OUTPUT_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"
# Canonical threshold shared with auction episode cognition asof max_age (45 minutes).
UPSTREAM_COGNITION_STALE_MINUTES = 45.0
COGNITION_EVALUATION_TIMESTAMP_COLUMNS = (
    "evaluated_at",
    "processed_market_timestamp",
    "source_timestamp",
    "cognition_observed_at",
)

REQUIRED_MEMORY_COLUMNS = [
    "timestamp",
    "close",
    "raw_market_context",
    "raw_context_status",
    "raw_cognitive_market_state",
    "raw_state_direction",
    "raw_context_reason",
    "raw_auction_episode",
    "active_market_context",
    "lifecycle_state",
    "active_context_started_at",
    "active_context_age_bars",
    "candidate_context",
    "candidate_started_at",
    "candidate_reason",
    "challenge_context",
    "challenge_started_at",
    "challenge_reason",
    "previous_active_market_context",
    "invalidation_reason",
    "invalidated_at",
    "invalidated_by_auction_episode",
    "invalidated_by_cognitive_state",
    "invalidated_by_market_context",
    "invalidation_type",
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
    "observe_secondary_reason",
    # Phase-1 context origin price diagnostics (immutable per directional episode).
    "context_origin_price",
    "context_entered_at",
    "context_episode_id",
    "context_direction",
    "context_distance_bps",
    "context_favorable_distance_bps",
    "context_adverse_distance_bps",
    "action_allowed",
    "action_reason",
    "shadow_only",
    "builder_version",
]

REQUIRED_EPISODE_COLUMNS = [
    "episode_id",
    "active_market_context",
    "start_time",
    "end_time",
    "start_close",
    "end_close",
    "bars_count",
    "duration_minutes",
    "start_lifecycle_state",
    "end_lifecycle_state",
    "dominant_lifecycle_state",
    "challenged_bars_count",
    "candidate_bars_count",
    "action_allowed_any",
    "action_allowed_all",
    "start_reason",
    "end_reason",
    "shadow_only",
    "builder_version",
]

DIRECTIONAL = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})
CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"})
INVALIDATION_NONE = "NONE"
INVALIDATION_AUCTION = "AUCTION_NEUTRALIZATION"
INVALIDATION_OPPOSITE = "OPPOSITE_CONTEXT_REPLACEMENT"
INVALIDATION_THESIS = "THESIS_REJECTION"

# Termination persistence protection (shadow-only; no execution, no TTL expiry).
# A confirmed active context must not be killed by a single neutral BALANCE/OBSERVE bar.
#   NEUTRALIZATION_CONFIRM_BARS  — consecutive full-confluence bars required to invalidate.
#   MIN_ACTIVE_CONTEXT_HOLD_BARS — a fresh context cannot be neutralized/rejected before this age.
# Opposite CONFIRMED replacement is intentionally exempt and still replaces immediately.
NEUTRALIZATION_CONFIRM_BARS = 2
MIN_ACTIVE_CONTEXT_HOLD_BARS = 3


def _clean_text(value: Any, default: str = "UNKNOWN") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", ""}:
        return default
    return text


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes"}:
        return True
    if text in {"0", "false", "f", "no"}:
        return False
    return bool(value)


def _to_utc_ts(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    try:
        return ts.as_unit("ns")
    except (TypeError, AttributeError, ValueError):
        return ts


def normalize_utc_ns_series(values: Any) -> pd.Series:
    """Normalize timestamps to timezone-aware datetime64[ns, UTC] for merge_asof."""
    if isinstance(values, pd.Series):
        series = values
        index = values.index
    else:
        series = pd.Series(values)
        index = series.index
    if len(series) == 0:
        return pd.Series(pd.array([], dtype="datetime64[ns, UTC]"), index=index)

    parsed = pd.to_datetime(series, utc=True, errors="coerce")
    if not isinstance(parsed, pd.Series):
        parsed = pd.Series(parsed, index=index)
    else:
        parsed = parsed.reindex(index)

    if getattr(parsed.dt, "tz", None) is None:
        parsed = parsed.dt.tz_localize("UTC")
    else:
        parsed = parsed.dt.tz_convert("UTC")

    if hasattr(parsed.dt, "as_unit"):
        try:
            parsed = parsed.dt.as_unit("ns")
        except (TypeError, ValueError, AttributeError):
            parsed = pd.to_datetime(parsed.astype("int64"), unit="ns", utc=True)
    else:
        # Fallback path for older pandas: reconstruct via ns epoch ints.
        nanos = parsed.view("int64")
        parsed = pd.to_datetime(nanos, unit="ns", utc=True)

    if str(parsed.dtype) != "datetime64[ns, UTC]":
        parsed = pd.to_datetime(parsed, utc=True, errors="coerce")
        if hasattr(parsed.dt, "as_unit"):
            parsed = parsed.dt.as_unit("ns")
    return parsed


def _age_minutes(newer: Any, older: Any) -> float | None:
    newer_ts = _to_utc_ts(newer)
    older_ts = _to_utc_ts(older)
    if newer_ts is None or older_ts is None:
        return None
    return round(float((newer_ts - older_ts).total_seconds() / 60.0), 6)


def _market_activity_score(close: float | None, previous_close: float | None) -> float | None:
    if close is None or previous_close is None or previous_close == 0:
        return None
    return round(abs((float(close) - float(previous_close)) / float(previous_close)) * 100.0, 6)


def _is_stale_upstream_cognition(age_minutes: float | None) -> bool:
    return age_minutes is not None and age_minutes > UPSTREAM_COGNITION_STALE_MINUTES


def _is_stale_market_feed(age_minutes: float | None) -> bool:
    return age_minutes is not None and age_minutes > UPSTREAM_COGNITION_STALE_MINUTES


def _fmt_age(age_minutes: float | None) -> str:
    if age_minutes is None:
        return "unknown"
    return f"{age_minutes:.3f}".rstrip("0").rstrip(".")


def _resolve_cognition_evaluation_timestamps(
    cognition_frame: pd.DataFrame | None,
    evaluation_frame: pd.DataFrame | None = None,
) -> pd.Series:
    """Return evaluation/processing timestamps for cognition freshness.

    runtime_cognition_memory is a sparse event log (state changes only). Evaluation
    freshness must not be inferred solely from the last synthesis_state event time.
    Preference order:
      1) explicit evaluation columns on cognition rows
      2) denser evaluation_frame timestamps (canonical: cognitive_market_state_memory)
      3) fallback to cognition event timestamps (conservative / degraded)
    """
    if cognition_frame is not None and len(cognition_frame) > 0:
        for column in COGNITION_EVALUATION_TIMESTAMP_COLUMNS:
            if column in cognition_frame.columns:
                series = normalize_utc_ns_series(cognition_frame[column])
                if series.notna().any():
                    return series

    if evaluation_frame is not None and len(evaluation_frame) > 0:
        for column in ("timestamp",) + COGNITION_EVALUATION_TIMESTAMP_COLUMNS:
            if column in evaluation_frame.columns:
                series = normalize_utc_ns_series(evaluation_frame[column])
                if series.notna().any():
                    return series

    if cognition_frame is not None and len(cognition_frame) > 0 and "timestamp" in cognition_frame.columns:
        return normalize_utc_ns_series(cognition_frame["timestamp"])
    return pd.Series(pd.array([], dtype="datetime64[ns, UTC]"))


def _mode_or_unknown(series: pd.Series) -> str:
    cleaned = series.map(lambda v: _clean_text(v, default="UNKNOWN"))
    if len(cleaned) == 0:
        return "UNKNOWN"
    counts = cleaned.value_counts(dropna=False)
    if len(counts) == 0:
        return "UNKNOWN"
    return str(counts.index[0])


def is_auction_neutralization(
    *,
    raw_market_context: str,
    raw_context_status: str,
    raw_cognitive_market_state: str,
    raw_state_direction: str,
    auction_episode: str,
) -> bool:
    """True only on full OBSERVE + BALANCE/NEUTRAL confluence. No TTL / age / ratio."""
    return (
        _clean_text(raw_market_context, default="OBSERVE") == "OBSERVE"
        and _clean_text(raw_context_status, default="UNKNOWN").upper() == "OBSERVE"
        and _clean_text(raw_cognitive_market_state, default="UNKNOWN").upper() == "BALANCE"
        and _clean_text(raw_state_direction, default="UNKNOWN").upper() == "NEUTRAL"
        and _clean_text(auction_episode, default="UNKNOWN").upper() == "BALANCE"
    )


def _empty_invalidation() -> dict[str, Any]:
    return {
        "previous_active_market_context": None,
        "invalidation_reason": None,
        "invalidated_at": None,
        "invalidated_by_auction_episode": None,
        "invalidated_by_cognitive_state": None,
        "invalidated_by_market_context": None,
        "invalidation_type": INVALIDATION_NONE,
    }


def step_lifecycle(
    *,
    raw_market_context: str,
    raw_context_status: str,
    raw_context_reason: str,
    raw_cognitive_market_state: str,
    raw_state_direction: str,
    auction_episode: str,
    timestamp: pd.Timestamp,
    prev: dict[str, Any] | None,
) -> dict[str, Any]:
    """Advance one bar of lifecycle state from previous active state."""
    raw = _clean_text(raw_market_context, default="OBSERVE")
    if raw not in CONTEXTS:
        raw = "OBSERVE"
    status = _clean_text(raw_context_status, default="UNKNOWN").upper()
    reason = _clean_text(raw_context_reason, default="UNKNOWN")
    cognitive = _clean_text(raw_cognitive_market_state, default="UNKNOWN").upper()
    direction = _clean_text(raw_state_direction, default="UNKNOWN").upper()
    auction = _clean_text(auction_episode, default="UNKNOWN").upper()

    if prev is None:
        active = "OBSERVE"
        lifecycle = "NO_ACTIVE_CONTEXT"
        active_started = None
        active_age = 0
        candidate = None
        candidate_started = None
        candidate_reason = None
        challenge = None
        challenge_started = None
        challenge_reason = None
        transition = "initial state"
        prev_lifecycle = "NO_ACTIVE_CONTEXT"
        carried_inv = _empty_invalidation()
        prev_neutralization_streak = 0
    else:
        active = _clean_text(prev.get("active_market_context"), default="OBSERVE")
        lifecycle = _clean_text(prev.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT")
        active_started = prev.get("active_context_started_at")
        if active_started is not None and (isinstance(active_started, float) and pd.isna(active_started)):
            active_started = None
        active_age = int(prev.get("active_context_age_bars") or 0)
        candidate = prev.get("candidate_context")
        candidate_started = prev.get("candidate_started_at")
        candidate_reason = prev.get("candidate_reason")
        challenge = prev.get("challenge_context")
        challenge_started = prev.get("challenge_started_at")
        challenge_reason = prev.get("challenge_reason")
        transition = ""
        prev_lifecycle = lifecycle
        prev_neutralization_streak = int(prev.get("_neutralization_streak") or 0)
        # Invalidation diagnostics describe the actual event row only.
        # Do NOT carry AUCTION_NEUTRALIZATION forward onto later OBSERVE/CANDIDATE rows.
        carried_inv = _empty_invalidation()

    new_candidate = None
    new_candidate_started = None
    new_candidate_reason = None
    new_challenge = None
    new_challenge_started = None
    new_challenge_reason = None
    new_transition = transition
    inv = dict(carried_inv)
    neutralization_streak = 0

    # Source-row INVALIDATED → thesis rejection, with minimum-hold protection.
    if status == "INVALIDATED":
        if active in DIRECTIONAL and active_age < MIN_ACTIVE_CONTEXT_HOLD_BARS:
            # Too fresh: hold as CHALLENGED instead of closing on the first rejection bar.
            lifecycle = "CHALLENGED"
            new_challenge = active
            new_challenge_started = timestamp
            new_challenge_reason = "source invalidated within minimum active hold"
            active_age = active_age + 1
            new_transition = "source invalidation held (minimum active hold protection)"
        else:
            previous = active if active in DIRECTIONAL else None
            active = "OBSERVE"
            lifecycle = "INVALIDATED"
            active_started = None
            active_age = 0
            new_transition = "source context invalidated"
            inv = {
                "previous_active_market_context": previous,
                "invalidation_reason": "source context invalidated",
                "invalidated_at": timestamp,
                "invalidated_by_auction_episode": auction,
                "invalidated_by_cognitive_state": cognitive,
                "invalidated_by_market_context": raw,
                "invalidation_type": INVALIDATION_THESIS,
            }
    # OBSERVE path: neutralization or challenge.
    elif raw == "OBSERVE":
        if active == "OBSERVE":
            lifecycle = "NO_ACTIVE_CONTEXT"
            active_started = None
            active_age = 0
            new_transition = "observe with no active context"
        elif active in DIRECTIONAL and is_auction_neutralization(
            raw_market_context=raw,
            raw_context_status=status,
            raw_cognitive_market_state=cognitive,
            raw_state_direction=direction,
            auction_episode=auction,
        ):
            # Persistence protection: a single neutral bar must not kill a confirmed context.
            streak = prev_neutralization_streak + 1
            too_young = active_age < MIN_ACTIVE_CONTEXT_HOLD_BARS
            not_persistent = streak < NEUTRALIZATION_CONFIRM_BARS
            if too_young or not_persistent:
                lifecycle = "CHALLENGED"
                new_challenge = "OBSERVE"
                new_challenge_started = timestamp
                new_challenge_reason = reason
                active_age = active_age + 1
                neutralization_streak = streak
                new_transition = (
                    "neutralization confluence challenged active context "
                    f"(hold protection: age={active_age - 1}, streak={streak})"
                )
            else:
                previous = active
                inv_reason = (
                    f"{previous} invalidated after {streak} consecutive neutralization bars; "
                    "auction and cognitive state held BALANCE / NEUTRAL / OBSERVE."
                )
                active = "OBSERVE"
                lifecycle = "INVALIDATED"
                active_started = None
                active_age = 0
                neutralization_streak = 0
                new_transition = "auction neutralization invalidated active context"
                inv = {
                    "previous_active_market_context": previous,
                    "invalidation_reason": inv_reason,
                    "invalidated_at": timestamp,
                    "invalidated_by_auction_episode": auction,
                    "invalidated_by_cognitive_state": cognitive,
                    "invalidated_by_market_context": raw,
                    "invalidation_type": INVALIDATION_AUCTION,
                }
        else:
            # Challenge only — incomplete confluence must not kill active context.
            # Confluence chain is broken, so reset the neutralization streak.
            lifecycle = "CHALLENGED"
            new_challenge = "OBSERVE"
            new_challenge_started = timestamp
            new_challenge_reason = reason
            active_age = active_age + 1
            new_transition = "observe challenged active context"
    # Directional raw contexts.
    elif raw in DIRECTIONAL:
        if status == "DEVELOPING":
            if active == "OBSERVE":
                lifecycle = "CANDIDATE"
                new_candidate = raw
                # Keep candidate identity/clock across tips of the same direction.
                if candidate == raw and candidate_started is not None:
                    new_candidate_started = candidate_started
                    new_candidate_reason = candidate_reason or reason
                else:
                    new_candidate_started = timestamp
                    new_candidate_reason = reason
                active_started = None
                active_age = 0
                new_transition = "developing directional context is candidate only"
            elif raw == active:
                if prev_lifecycle == "CHALLENGED":
                    lifecycle = "CHALLENGED"
                    new_challenge = challenge
                    new_challenge_started = challenge_started
                    new_challenge_reason = challenge_reason
                else:
                    lifecycle = "ACTIVE"
                active_age = active_age + 1
                new_transition = "developing same-direction context keeps active"
            else:
                lifecycle = "CHALLENGED"
                new_challenge = raw
                new_challenge_started = timestamp
                new_challenge_reason = reason
                active_age = active_age + 1
                new_transition = "developing opposite context challenges active"
        elif status == "ACTIVE":
            if active == "OBSERVE":
                active = raw
                lifecycle = "ACTIVE"
                active_started = timestamp
                active_age = 0
                new_transition = "confirmed directional context became active"
                inv = _empty_invalidation()
            elif raw == active:
                lifecycle = "ACTIVE"
                active_age = active_age + 1
                new_transition = "confirmed same-direction context remains active"
            else:
                previous = active
                active = raw
                lifecycle = "ACTIVE"
                active_started = timestamp
                active_age = 0
                new_transition = "confirmed opposite context replaced active context"
                inv = {
                    "previous_active_market_context": previous,
                    "invalidation_reason": (
                        f"{previous} replaced by confirmed opposite {raw}"
                    ),
                    "invalidated_at": timestamp,
                    "invalidated_by_auction_episode": auction,
                    "invalidated_by_cognitive_state": cognitive,
                    "invalidated_by_market_context": raw,
                    "invalidation_type": INVALIDATION_OPPOSITE,
                }
        else:
            if active == "OBSERVE":
                lifecycle = "CANDIDATE"
                new_candidate = raw
                if candidate == raw and candidate_started is not None:
                    new_candidate_started = candidate_started
                    new_candidate_reason = candidate_reason or reason
                else:
                    new_candidate_started = timestamp
                    new_candidate_reason = reason
                active_started = None
                active_age = 0
                new_transition = "non-active directional status stays candidate"
            elif raw == active:
                lifecycle = "ACTIVE" if prev_lifecycle != "CHALLENGED" else "CHALLENGED"
                if lifecycle == "CHALLENGED":
                    new_challenge = challenge
                    new_challenge_started = challenge_started
                    new_challenge_reason = challenge_reason
                active_age = active_age + 1
                new_transition = "same-direction non-active status keeps active"
            else:
                lifecycle = "CHALLENGED"
                new_challenge = raw
                new_challenge_started = timestamp
                new_challenge_reason = reason
                active_age = active_age + 1
                new_transition = "opposite non-active status challenges active"
    else:
        lifecycle = "NO_ACTIVE_CONTEXT" if active == "OBSERVE" else "CHALLENGED"
        if active == "OBSERVE":
            active_started = None
            active_age = 0
        else:
            active_age = active_age + 1
        new_transition = "unhandled raw context"

    # Age semantics: only directional active contexts have age / started_at.
    if active == "OBSERVE" or lifecycle in {"NO_ACTIVE_CONTEXT", "INVALIDATED"}:
        active_started = None
        active_age = 0
    elif active in DIRECTIONAL and active_started is None:
        active_started = timestamp
        active_age = 0

    return {
        "active_market_context": active,
        "lifecycle_state": lifecycle,
        "active_context_started_at": active_started,
        "active_context_age_bars": int(active_age),
        "candidate_context": new_candidate,
        "candidate_started_at": new_candidate_started,
        "candidate_reason": new_candidate_reason,
        "challenge_context": new_challenge,
        "challenge_started_at": new_challenge_started,
        "challenge_reason": new_challenge_reason,
        "transition_reason": new_transition,
        # Internal state threaded via prev; dropped from output (not in REQUIRED_MEMORY_COLUMNS).
        "_neutralization_streak": int(neutralization_streak),
        **inv,
    }


def attach_auction_episode(context_frame: pd.DataFrame, auction_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Attach auction_episode (+ FT/status diagnostics) onto final-context rows."""
    work = context_frame.copy()
    need_episode = "auction_episode" not in work.columns
    need_ft = "follow_through" not in work.columns
    need_status = "episode_status" not in work.columns
    if not need_episode and not need_ft and not need_status:
        return work

    if auction_frame is None:
        if AUCTION_PATH.exists():
            auction_frame = pd.read_parquet(AUCTION_PATH)
        else:
            if need_episode:
                work["auction_episode"] = "UNKNOWN"
            if need_ft:
                work["follow_through"] = "UNKNOWN"
            if need_status:
                work["episode_status"] = "UNKNOWN"
            return work

    auction = auction_frame.copy()
    if "timestamp" not in auction.columns or "auction_episode" not in auction.columns:
        if need_episode:
            work["auction_episode"] = "UNKNOWN"
        if need_ft:
            work["follow_through"] = "UNKNOWN"
        if need_status:
            work["episode_status"] = "UNKNOWN"
        return work

    original_index = work.index
    left = work.copy()
    left["_row_id"] = range(len(left))
    left["timestamp"] = normalize_utc_ns_series(left["timestamp"])
    auction = auction.copy()
    auction["timestamp"] = normalize_utc_ns_series(auction["timestamp"])
    left_valid = left.dropna(subset=["timestamp"]).sort_values(["timestamp", "_row_id"])
    cols = ["timestamp", "auction_episode"]
    for col in ("follow_through", "episode_status"):
        if col in auction.columns:
            cols.append(col)
    right = (
        auction[cols]
        .dropna(subset=["timestamp"])
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
    )
    if len(left_valid) == 0 or len(right) == 0:
        if need_episode:
            work["auction_episode"] = "UNKNOWN"
        if need_ft:
            work["follow_through"] = "UNKNOWN"
        if need_status:
            work["episode_status"] = "UNKNOWN"
        return work.drop(columns=["_row_id"], errors="ignore")

    merged = pd.merge_asof(
        left_valid,
        right,
        on="timestamp",
        direction="backward",
        tolerance=pd.Timedelta("2h"),
        suffixes=("", "_auc"),
    )
    out = work.drop(columns=["_row_id"], errors="ignore").copy()
    if need_episode:
        episode_by_row = {
            int(row_id): _clean_text(value, default="UNKNOWN")
            for row_id, value in zip(merged["_row_id"].tolist(), merged["auction_episode"].tolist())
        }
        out["auction_episode"] = [episode_by_row.get(i, "UNKNOWN") for i in range(len(out))]
    if need_ft:
        ft_col = "follow_through" if "follow_through" in merged.columns else None
        if ft_col:
            ft_by_row = {
                int(row_id): _clean_text(value, default="UNKNOWN")
                for row_id, value in zip(merged["_row_id"].tolist(), merged[ft_col].tolist())
            }
            out["follow_through"] = [ft_by_row.get(i, "UNKNOWN") for i in range(len(out))]
        else:
            out["follow_through"] = "UNKNOWN"
    if need_status:
        st_col = "episode_status" if "episode_status" in merged.columns else None
        if st_col:
            st_by_row = {
                int(row_id): _clean_text(value, default="UNKNOWN")
                for row_id, value in zip(merged["_row_id"].tolist(), merged[st_col].tolist())
            }
            out["episode_status"] = [st_by_row.get(i, "UNKNOWN") for i in range(len(out))]
        else:
            out["episode_status"] = "UNKNOWN"
    out.index = original_index
    return out


def attach_runtime_cognition_freshness(
    context_frame: pd.DataFrame,
    cognition_frame: pd.DataFrame | None = None,
    evaluation_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Attach cognition state-age and evaluation-freshness diagnostics.

    Preserves original lifecycle/context row order and count. NaT timestamps are
    kept in the output with null diagnostics rather than dropped.
    """
    work = context_frame.copy()
    original_index = work.index
    n_rows = len(work)
    if "cognition_state_age_minutes" not in work.columns:
        work["cognition_state_age_minutes"] = pd.array([pd.NA] * n_rows, dtype="Float64")
    if "upstream_cognition_freshness_minutes" not in work.columns:
        work["upstream_cognition_freshness_minutes"] = pd.array([pd.NA] * n_rows, dtype="Float64")

    if "timestamp" not in work.columns:
        work.index = original_index
        return work

    left = pd.DataFrame(
        {
            "_row_id": range(n_rows),
            "timestamp": normalize_utc_ns_series(work["timestamp"]),
        },
        index=original_index,
    )
    left_valid = left.dropna(subset=["timestamp"]).sort_values(["timestamp", "_row_id"])
    if len(left_valid) == 0:
        work.index = original_index
        return work

    state_ages = pd.Series(pd.array([pd.NA] * n_rows, dtype="Float64"))
    eval_ages = pd.Series(pd.array([pd.NA] * n_rows, dtype="Float64"))

    if (
        cognition_frame is not None
        and len(cognition_frame) > 0
        and "timestamp" in cognition_frame.columns
    ):
        right_state = pd.DataFrame(
            {
                "runtime_cognition_timestamp": normalize_utc_ns_series(cognition_frame["timestamp"]),
            }
        )
        # Keep NaT out of merge keys only; do not drop valid lifecycle rows.
        right_state = right_state.dropna(subset=["runtime_cognition_timestamp"])
        right_state = right_state.sort_values("runtime_cognition_timestamp")
        right_state = right_state.drop_duplicates(subset=["runtime_cognition_timestamp"], keep="last")
        if len(right_state) > 0:
            merged_state = pd.merge_asof(
                left_valid,
                right_state,
                left_on="timestamp",
                right_on="runtime_cognition_timestamp",
                direction="backward",
            )
            for row_id, bar_ts, event_ts in zip(
                merged_state["_row_id"].tolist(),
                merged_state["timestamp"].tolist(),
                merged_state["runtime_cognition_timestamp"].tolist(),
            ):
                state_ages.iloc[int(row_id)] = _age_minutes(bar_ts, event_ts)

    eval_timestamps = _resolve_cognition_evaluation_timestamps(
        cognition_frame,
        evaluation_frame=evaluation_frame,
    )
    if len(eval_timestamps) > 0 and eval_timestamps.notna().any():
        right_eval = pd.DataFrame({"cognition_evaluation_timestamp": eval_timestamps})
        right_eval = right_eval.dropna(subset=["cognition_evaluation_timestamp"])
        right_eval = right_eval.sort_values("cognition_evaluation_timestamp")
        right_eval = right_eval.drop_duplicates(
            subset=["cognition_evaluation_timestamp"], keep="last"
        )
        if len(right_eval) > 0:
            merged_eval = pd.merge_asof(
                left_valid,
                right_eval,
                left_on="timestamp",
                right_on="cognition_evaluation_timestamp",
                direction="backward",
            )
            for row_id, bar_ts, eval_ts in zip(
                merged_eval["_row_id"].tolist(),
                merged_eval["timestamp"].tolist(),
                merged_eval["cognition_evaluation_timestamp"].tolist(),
            ):
                eval_ages.iloc[int(row_id)] = _age_minutes(bar_ts, eval_ts)

    work["cognition_state_age_minutes"] = state_ages.to_numpy()
    work["upstream_cognition_freshness_minutes"] = eval_ages.to_numpy()
    work.index = original_index
    return work


def _attach_lifecycle_diagnostics(
    row: dict[str, Any],
    *,
    prev: dict[str, Any] | None,
    timestamp: pd.Timestamp,
    upstream_cognition_age_minutes: float | None,
    cognition_state_age_minutes: float | None,
    market_feed_age_minutes: float | None,
    market_activity_score: float | None,
) -> dict[str, Any]:
    active = _clean_text(row.get("active_market_context"), default="OBSERVE")
    lifecycle = _clean_text(row.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT")
    raw = _clean_text(row.get("raw_market_context"), default="OBSERVE")
    candidate = _clean_text(row.get("candidate_context"), default="UNKNOWN")
    stale_cognition = _is_stale_upstream_cognition(upstream_cognition_age_minutes)
    stale_market = _is_stale_market_feed(market_feed_age_minutes)
    observe_escape_candidate = bool(raw in DIRECTIONAL or candidate in DIRECTIONAL)
    observe_block_reason = None
    observe_secondary_reason = None
    transition_block_reason = None

    if active == "OBSERVE":
        if lifecycle == "INVALIDATED":
            observe_block_reason = _clean_text(row.get("invalidation_type"), default="INVALIDATED")
            transition_block_reason = observe_block_reason
        elif stale_cognition and raw == "OBSERVE":
            # Stale cognition is never a normal OBSERVE / tradeable neutral state.
            observe_escape_candidate = False
            if stale_market:
                observe_block_reason = "STALE_MARKET_AND_COGNITION"
                transition_block_reason = "STALE_MARKET_AND_COGNITION"
                reason = (
                    "stale market feed "
                    f"(gap_minutes={_fmt_age(market_feed_age_minutes)}) "
                    "and stale upstream cognition evaluation "
                    f"(age_minutes={_fmt_age(upstream_cognition_age_minutes)}; "
                    f"state_age_minutes={_fmt_age(cognition_state_age_minutes)})"
                )
            else:
                observe_block_reason = "STALE_COGNITION"
                transition_block_reason = "STALE_COGNITION"
                reason = (
                    "stale upstream cognition evaluation while market bars continue "
                    f"(age_minutes={_fmt_age(upstream_cognition_age_minutes)}; "
                    f"state_age_minutes={_fmt_age(cognition_state_age_minutes)})"
                )
            if lifecycle in {"NO_ACTIVE_CONTEXT", "STALE_COGNITION"}:
                lifecycle = "STALE_COGNITION"
                row["lifecycle_state"] = lifecycle
                row["transition_reason"] = reason
        elif raw == "OBSERVE":
            observe_block_reason = "NO_DIRECTIONAL_CONTEXT"
            transition_block_reason = "NO_DIRECTIONAL_CONTEXT"
        elif candidate in DIRECTIONAL:
            observe_block_reason = "DIRECTIONAL_CONTEXT_CANDIDATE_ONLY"
            auction_ep = _clean_text(
                row.get("raw_auction_episode") or row.get("auction_episode"),
                default="UNKNOWN",
            ).upper()
            ft = _clean_text(row.get("follow_through"), default="UNKNOWN").upper()
            if auction_ep in {"ACCEPTANCE_HIGHER", "ACCEPTANCE_LOWER"} and ft in {"NO", "WEAK"}:
                observe_secondary_reason = "ACCEPTANCE_AWAITING_FT_YES"

    previous_entered = None
    if prev is not None:
        same_state = (
            _clean_text(prev.get("active_market_context"), default="OBSERVE") == active
            and _clean_text(prev.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT") == lifecycle
        )
        if same_state:
            previous_entered = _to_utc_ts(prev.get("state_entered_at"))
    state_entered_at = previous_entered or timestamp
    row["lifecycle_state_reason"] = _clean_text(row.get("transition_reason"), default="NONE")
    row["state_entered_at"] = state_entered_at
    row["state_age_minutes"] = _age_minutes(timestamp, state_entered_at) or 0.0
    row["transition_block_reason"] = transition_block_reason
    row["cognition_state_age_minutes"] = cognition_state_age_minutes
    row["upstream_cognition_freshness_minutes"] = upstream_cognition_age_minutes
    row["market_feed_age_minutes"] = market_feed_age_minutes
    row["market_activity_score"] = market_activity_score
    row["observe_escape_candidate"] = observe_escape_candidate
    row["observe_block_reason"] = observe_block_reason
    row["observe_secondary_reason"] = observe_secondary_reason
    return row


def signed_context_distance_bps(
    direction: str | None,
    origin_price: float | None,
    current_close: float | None,
) -> float | None:
    """Signed distance in bps; positive = move with context, negative = against."""
    direction_clean = _clean_text(direction, default="")
    origin = _safe_float(origin_price)
    close = _safe_float(current_close)
    if origin is None or close is None or origin == 0.0:
        return None
    if direction_clean == "LONG_CONTEXT":
        return round((close - origin) / origin * 10000.0, 6)
    if direction_clean == "SHORT_CONTEXT":
        return round((origin - close) / origin * 10000.0, 6)
    return None


def attach_context_origin_fields(memory_frame: pd.DataFrame) -> pd.DataFrame:
    """Attach immutable per-episode origin price diagnostics to lifecycle bars.

    Semantics (Phase 1):
      - Origin is created only when active_market_context is LONG/SHORT
        (confirmed active directional episode), not on CANDIDATE while OBSERVE.
      - Origin = close of the first bar of that directional episode.
      - Origin is immutable until the episode ends / is invalidated.
      - context_episode_id matches build_lifecycle_episodes numbering.
    """
    if memory_frame is None or len(memory_frame) == 0:
        empty = pd.DataFrame(columns=REQUIRED_MEMORY_COLUMNS)
        return empty

    work = memory_frame.copy()
    work["timestamp"] = normalize_utc_ns_series(work["timestamp"])
    work = work.sort_values("timestamp").reset_index(drop=True)

    for col in (
        "context_origin_price",
        "context_entered_at",
        "context_episode_id",
        "context_direction",
        "context_distance_bps",
        "context_favorable_distance_bps",
        "context_adverse_distance_bps",
    ):
        if col not in work.columns:
            work[col] = None

    changed = work["active_market_context"] != work["active_market_context"].shift(1)
    if len(changed):
        changed.iloc[0] = True
    work["_episode_group"] = changed.cumsum()

    for episode_id, (_, group) in enumerate(
        work.groupby("_episode_group", sort=True), start=1
    ):
        idx = group.index
        active = _clean_text(group.iloc[0].get("active_market_context"), default="OBSERVE")
        work.loc[idx, "context_episode_id"] = int(episode_id)
        if active not in DIRECTIONAL:
            work.loc[idx, "context_origin_price"] = None
            work.loc[idx, "context_entered_at"] = None
            work.loc[idx, "context_direction"] = None
            work.loc[idx, "context_distance_bps"] = None
            work.loc[idx, "context_favorable_distance_bps"] = None
            work.loc[idx, "context_adverse_distance_bps"] = None
            continue

        start_row = group.iloc[0]
        origin = _safe_float(start_row.get("close"))
        entered_at = start_row.get("timestamp")
        work.loc[idx, "context_origin_price"] = origin
        work.loc[idx, "context_entered_at"] = entered_at
        work.loc[idx, "context_direction"] = active
        for i in idx:
            close = _safe_float(work.at[i, "close"])
            dist = signed_context_distance_bps(active, origin, close)
            work.at[i, "context_distance_bps"] = dist
            if dist is None:
                work.at[i, "context_favorable_distance_bps"] = None
                work.at[i, "context_adverse_distance_bps"] = None
            else:
                work.at[i, "context_favorable_distance_bps"] = round(max(float(dist), 0.0), 6)
                work.at[i, "context_adverse_distance_bps"] = round(max(-float(dist), 0.0), 6)

    work = work.drop(columns=["_episode_group"], errors="ignore")
    return work


def build_lifecycle_memory(
    context_frame: pd.DataFrame,
    auction_frame: pd.DataFrame | None = None,
    cognition_frame: pd.DataFrame | None = None,
    evaluation_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if context_frame is None or len(context_frame) == 0:
        return pd.DataFrame(columns=REQUIRED_MEMORY_COLUMNS)

    work = attach_auction_episode(context_frame, auction_frame=auction_frame)
    work = attach_runtime_cognition_freshness(
        work,
        cognition_frame=cognition_frame,
        evaluation_frame=evaluation_frame,
    )
    if "timestamp" not in work.columns or "market_context" not in work.columns:
        raise ValueError("final_market_context_memory missing timestamp/market_context")
    work = work.copy()
    work["timestamp"] = normalize_utc_ns_series(work["timestamp"])
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    previous_close: float | None = None
    previous_ts: pd.Timestamp | None = None
    for _, src in work.iterrows():
        raw = _clean_text(src.get("market_context"), default="OBSERVE")
        status = _clean_text(src.get("context_status"), default="UNKNOWN")
        reason = _clean_text(src.get("context_reason"), default="UNKNOWN")
        cognitive = _clean_text(src.get("cognitive_market_state"), default="UNKNOWN")
        direction = _clean_text(src.get("state_direction"), default="UNKNOWN")
        auction = _clean_text(src.get("auction_episode"), default="UNKNOWN")
        ts = src["timestamp"]
        close = _safe_float(src.get("close"))
        upstream_age = _safe_float(src.get("upstream_cognition_freshness_minutes"), default=None)
        state_age = _safe_float(src.get("cognition_state_age_minutes"), default=None)
        market_feed_age = _age_minutes(ts, previous_ts) if previous_ts is not None else 0.0
        activity_score = _market_activity_score(close, previous_close)
        step = step_lifecycle(
            raw_market_context=raw,
            raw_context_status=status,
            raw_context_reason=reason,
            raw_cognitive_market_state=cognitive,
            raw_state_direction=direction,
            auction_episode=auction,
            timestamp=ts,
            prev=prev,
        )
        row = {
            "timestamp": ts,
            "close": close,
            "raw_market_context": raw,
            "raw_context_status": status,
            "raw_cognitive_market_state": cognitive,
            "raw_state_direction": direction,
            "raw_context_reason": reason,
            "raw_auction_episode": auction,
            "follow_through": _clean_text(src.get("follow_through"), default="UNKNOWN"),
            "episode_status": _clean_text(src.get("episode_status"), default="UNKNOWN"),
            **step,
            # Shadow policy: never enable execution from lifecycle.
            "action_allowed": False,
            "action_reason": _clean_text(
                src.get("action_reason"),
                default="shadow market context only; execution disabled",
            ),
            "shadow_only": True,
            "builder_version": BUILDER_VERSION,
        }
        row = _attach_lifecycle_diagnostics(
            row,
            prev=prev,
            timestamp=ts,
            upstream_cognition_age_minutes=upstream_age,
            cognition_state_age_minutes=state_age,
            market_feed_age_minutes=market_feed_age,
            market_activity_score=activity_score,
        )
        rows.append(row)
        prev = row
        previous_close = close
        previous_ts = _to_utc_ts(ts)

    out = pd.DataFrame(rows)
    if len(out) and not out["shadow_only"].astype(bool).all():
        raise RuntimeError("shadow_only must remain True")
    out = attach_context_origin_fields(out)
    return out[REQUIRED_MEMORY_COLUMNS]


def build_lifecycle_episodes(memory_frame: pd.DataFrame) -> pd.DataFrame:
    if memory_frame is None or len(memory_frame) == 0:
        return pd.DataFrame(columns=REQUIRED_EPISODE_COLUMNS)

    work = memory_frame.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if "active_market_context" not in work.columns:
        raise ValueError("lifecycle memory missing active_market_context")

    changed = work["active_market_context"] != work["active_market_context"].shift(1)
    changed.iloc[0] = True
    work["_episode_group"] = changed.cumsum()

    episodes: list[dict[str, Any]] = []
    groups = list(work.groupby("_episode_group", sort=True))
    for idx, (_, group) in enumerate(groups, start=1):
        group = group.sort_values("timestamp")
        start = group.iloc[0]
        end = group.iloc[-1]
        active = _clean_text(start["active_market_context"])
        start_time = start["timestamp"]
        end_time = end["timestamp"]
        duration_minutes = float((end_time - start_time).total_seconds() / 60.0)

        if idx < len(groups):
            next_group = groups[idx][1]
            next_start = next_group.iloc[0]
            next_ctx = _clean_text(next_start["active_market_context"])
            inv_type = _clean_text(next_start.get("invalidation_type"), default=INVALIDATION_NONE)
            if inv_type == INVALIDATION_AUCTION:
                end_reason = (
                    f"auction neutralization closed {active} at invalidation timestamp; "
                    f"new {next_ctx} episode started"
                )
            elif inv_type == INVALIDATION_OPPOSITE:
                end_reason = f"opposite confirmed context replaced {active} with {next_ctx}"
            elif inv_type == INVALIDATION_THESIS:
                end_reason = f"thesis rejection closed {active}; new {next_ctx} episode started"
            else:
                end_reason = f"active_market_context changed from {active} to {next_ctx}"
        else:
            end_reason = "latest open lifecycle episode"

        action_flags = (
            group["action_allowed"].map(_safe_bool)
            if "action_allowed" in group.columns
            else pd.Series([False] * len(group))
        )
        challenged_bars = int((group["lifecycle_state"] == "CHALLENGED").sum()) if "lifecycle_state" in group.columns else 0
        candidate_bars = int((group["lifecycle_state"] == "CANDIDATE").sum()) if "lifecycle_state" in group.columns else 0

        episodes.append(
            {
                "episode_id": idx,
                "active_market_context": active,
                "start_time": start_time,
                "end_time": end_time,
                "start_close": _safe_float(start.get("close")),
                "end_close": _safe_float(end.get("close")),
                "bars_count": int(len(group)),
                "duration_minutes": duration_minutes,
                "start_lifecycle_state": _clean_text(start.get("lifecycle_state"), default="UNKNOWN"),
                "end_lifecycle_state": _clean_text(end.get("lifecycle_state"), default="UNKNOWN"),
                "dominant_lifecycle_state": _mode_or_unknown(group["lifecycle_state"])
                if "lifecycle_state" in group.columns
                else "UNKNOWN",
                "challenged_bars_count": challenged_bars,
                "candidate_bars_count": candidate_bars,
                "action_allowed_any": bool(action_flags.any()),
                "action_allowed_all": bool(len(action_flags) > 0 and action_flags.all()),
                "start_reason": _clean_text(start.get("transition_reason"), default="UNKNOWN"),
                "end_reason": end_reason,
                "shadow_only": True,
                "builder_version": BUILDER_VERSION,
            }
        )

    out = pd.DataFrame(episodes)
    if len(out) and not out["shadow_only"].astype(bool).all():
        raise RuntimeError("shadow_only must remain True")
    return out[REQUIRED_EPISODE_COLUMNS]


def write_atomic_parquet(frame: pd.DataFrame, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}_",
        suffix=".parquet",
        dir=str(output_path.parent),
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        frame.to_parquet(tmp_path, index=False)
        os.replace(tmp_path, output_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build shadow market context lifecycle memory + episodes"
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=MEMORY_OUTPUT_PATH,
        help="Lifecycle memory parquet output path (default: production path)",
    )
    parser.add_argument(
        "--episodes-output-path",
        type=Path,
        default=EPISODES_OUTPUT_PATH,
        help="Lifecycle episodes parquet output path (default: production path)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    memory_output_path = Path(args.output_path)
    episodes_output_path = Path(args.episodes_output_path)

    if not INPUT_PATH.exists():
        print(
            f"ERROR: required input missing: {INPUT_PATH}\n"
            "Run scripts/research/build_final_market_context_memory.py first.",
            file=sys.stderr,
        )
        return 1

    try:
        context_frame = pd.read_parquet(INPUT_PATH)
    except Exception as exc:
        print(f"ERROR: failed to read {INPUT_PATH}: {exc}", file=sys.stderr)
        return 1

    auction_frame = None
    if AUCTION_PATH.exists():
        try:
            auction_frame = pd.read_parquet(AUCTION_PATH)
        except Exception as exc:
            print(f"WARNING: failed to read auction episodes ({exc}); neutralization may be limited")

    cognition_frame = None
    if COGNITION_PATH.exists():
        try:
            cognition_frame = pd.read_parquet(COGNITION_PATH)
        except Exception as exc:
            print(f"WARNING: failed to read runtime cognition ({exc}); stale-cognition diagnostics may be limited")

    evaluation_frame = None
    if COGNITION_EVALUATION_PATH.exists():
        try:
            evaluation_frame = pd.read_parquet(COGNITION_EVALUATION_PATH)
        except Exception as exc:
            print(
                f"WARNING: failed to read cognition evaluation heartbeat ({exc}); "
                "falling back to cognition event timestamps"
            )

    memory = build_lifecycle_memory(
        context_frame,
        auction_frame=auction_frame,
        cognition_frame=cognition_frame,
        evaluation_frame=evaluation_frame,
    )
    episodes = build_lifecycle_episodes(memory)
    mem_path = write_atomic_parquet(memory, memory_output_path)
    ep_path = write_atomic_parquet(episodes, episodes_output_path)

    print(f"rows written memory: {len(memory)}")
    print(f"rows written episodes: {len(episodes)}")
    if len(memory) == 0:
        print("latest timestamp: —")
        print("latest raw_market_context: —")
        print("latest active_market_context: —")
        print("latest lifecycle_state: —")
        print("latest active_context_age_bars: —")
        print("latest invalidation_type: —")
        print("latest previous_active_market_context: —")
    else:
        latest = memory.iloc[-1]
        print(f"latest timestamp: {latest['timestamp']}")
        print(f"latest raw_market_context: {latest['raw_market_context']}")
        print(f"latest active_market_context: {latest['active_market_context']}")
        print(f"latest lifecycle_state: {latest['lifecycle_state']}")
        print(f"latest active_context_age_bars: {latest['active_context_age_bars']}")
        print(f"latest invalidation_type: {latest['invalidation_type']}")
        print(f"latest previous_active_market_context: {latest['previous_active_market_context']}")
    print(f"output path memory: {mem_path}")
    print(f"output path episodes: {ep_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
