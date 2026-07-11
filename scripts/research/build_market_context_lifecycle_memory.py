#!/usr/bin/env python3
"""Standalone shadow builder: market context lifecycle memory + episodes.

Converts choppy per-bar market_context into a stable active_market_context
lifecycle without TTL / N-bar rules / trade-policy rewriting.

Auction-based invalidation can close a directional context when OBSERVE
confluence with BALANCE / NEUTRAL auction+cognitive thesis rejection appears.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BUILDER_VERSION = "market_context_lifecycle_memory_v2"
INPUT_PATH = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
AUCTION_PATH = ROOT / "data" / "cognition" / "auction_episode_memory.parquet"
MEMORY_OUTPUT_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
EPISODES_OUTPUT_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"

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
        # Carry last invalidation diagnostics while still in OBSERVE after a close.
        prev_inv_type = _clean_text(prev.get("invalidation_type"), default=INVALIDATION_NONE)
        if prev_inv_type != INVALIDATION_NONE and active == "OBSERVE":
            carried_inv = {
                "previous_active_market_context": prev.get("previous_active_market_context"),
                "invalidation_reason": prev.get("invalidation_reason"),
                "invalidated_at": prev.get("invalidated_at"),
                "invalidated_by_auction_episode": prev.get("invalidated_by_auction_episode"),
                "invalidated_by_cognitive_state": prev.get("invalidated_by_cognitive_state"),
                "invalidated_by_market_context": prev.get("invalidated_by_market_context"),
                "invalidation_type": prev_inv_type,
            }
        else:
            carried_inv = _empty_invalidation()

    new_candidate = None
    new_candidate_started = None
    new_candidate_reason = None
    new_challenge = None
    new_challenge_started = None
    new_challenge_reason = None
    new_transition = transition
    inv = dict(carried_inv)

    # Source-row INVALIDATED → thesis rejection to OBSERVE.
    if status == "INVALIDATED":
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
            previous = active
            inv_reason = (
                f"{previous} invalidated because auction and cognitive state moved to "
                "BALANCE / NEUTRAL / OBSERVE; no confirmed opposite context required."
            )
            active = "OBSERVE"
            lifecycle = "INVALIDATED"
            active_started = None
            active_age = 0
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
        **inv,
    }


def attach_auction_episode(context_frame: pd.DataFrame, auction_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Attach auction_episode onto final-context rows (merge_asof or passthrough)."""
    work = context_frame.copy()
    if "auction_episode" in work.columns:
        return work

    if auction_frame is None:
        if AUCTION_PATH.exists():
            auction_frame = pd.read_parquet(AUCTION_PATH)
        else:
            work["auction_episode"] = "UNKNOWN"
            return work

    auction = auction_frame.copy()
    if "timestamp" not in auction.columns or "auction_episode" not in auction.columns:
        work["auction_episode"] = "UNKNOWN"
        return work

    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce").astype("datetime64[ns, UTC]")
    auction["timestamp"] = pd.to_datetime(auction["timestamp"], utc=True, errors="coerce").astype("datetime64[ns, UTC]")
    auction = auction.dropna(subset=["timestamp"]).sort_values("timestamp")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp")
    merged = pd.merge_asof(
        work,
        auction[["timestamp", "auction_episode"]],
        on="timestamp",
        direction="backward",
        tolerance=pd.Timedelta("2h"),
    )
    merged["auction_episode"] = merged["auction_episode"].map(
        lambda v: _clean_text(v, default="UNKNOWN")
    )
    return merged


def build_lifecycle_memory(
    context_frame: pd.DataFrame,
    auction_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if context_frame is None or len(context_frame) == 0:
        return pd.DataFrame(columns=REQUIRED_MEMORY_COLUMNS)

    work = attach_auction_episode(context_frame, auction_frame=auction_frame)
    if "timestamp" not in work.columns or "market_context" not in work.columns:
        raise ValueError("final_market_context_memory missing timestamp/market_context")
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    for _, src in work.iterrows():
        raw = _clean_text(src.get("market_context"), default="OBSERVE")
        status = _clean_text(src.get("context_status"), default="UNKNOWN")
        reason = _clean_text(src.get("context_reason"), default="UNKNOWN")
        cognitive = _clean_text(src.get("cognitive_market_state"), default="UNKNOWN")
        direction = _clean_text(src.get("state_direction"), default="UNKNOWN")
        auction = _clean_text(src.get("auction_episode"), default="UNKNOWN")
        ts = src["timestamp"]
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
            "close": _safe_float(src.get("close")),
            "raw_market_context": raw,
            "raw_context_status": status,
            "raw_cognitive_market_state": cognitive,
            "raw_state_direction": direction,
            "raw_context_reason": reason,
            "raw_auction_episode": auction,
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
        rows.append(row)
        prev = row

    out = pd.DataFrame(rows)
    if len(out) and not out["shadow_only"].astype(bool).all():
        raise RuntimeError("shadow_only must remain True")
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


def main() -> int:
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

    memory = build_lifecycle_memory(context_frame, auction_frame=auction_frame)
    episodes = build_lifecycle_episodes(memory)
    mem_path = write_atomic_parquet(memory, MEMORY_OUTPUT_PATH)
    ep_path = write_atomic_parquet(episodes, EPISODES_OUTPUT_PATH)

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
