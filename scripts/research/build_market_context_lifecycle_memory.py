#!/usr/bin/env python3
"""Standalone shadow builder: market context lifecycle memory + episodes.

Converts choppy per-bar market_context into a stable active_market_context
lifecycle without TTL / N-bar rules / trade-policy rewriting.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BUILDER_VERSION = "market_context_lifecycle_memory_v1"
INPUT_PATH = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
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


def _opposite(context: str) -> str | None:
    if context == "LONG_CONTEXT":
        return "SHORT_CONTEXT"
    if context == "SHORT_CONTEXT":
        return "LONG_CONTEXT"
    return None


def _mode_or_unknown(series: pd.Series) -> str:
    cleaned = series.map(lambda v: _clean_text(v, default="UNKNOWN"))
    if len(cleaned) == 0:
        return "UNKNOWN"
    counts = cleaned.value_counts(dropna=False)
    if len(counts) == 0:
        return "UNKNOWN"
    return str(counts.index[0])


def step_lifecycle(
    *,
    raw_market_context: str,
    raw_context_status: str,
    raw_context_reason: str,
    timestamp: pd.Timestamp,
    prev: dict[str, Any] | None,
) -> dict[str, Any]:
    """Advance one bar of lifecycle state from previous active state."""
    raw = _clean_text(raw_market_context, default="OBSERVE")
    if raw not in CONTEXTS:
        raw = "OBSERVE"
    status = _clean_text(raw_context_status, default="UNKNOWN").upper()
    reason = _clean_text(raw_context_reason, default="UNKNOWN")

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
    else:
        active = _clean_text(prev.get("active_market_context"), default="OBSERVE")
        lifecycle = _clean_text(prev.get("lifecycle_state"), default="NO_ACTIVE_CONTEXT")
        active_started = prev.get("active_context_started_at")
        active_age = int(prev.get("active_context_age_bars") or 0)
        candidate = prev.get("candidate_context")
        candidate_started = prev.get("candidate_started_at")
        candidate_reason = prev.get("candidate_reason")
        challenge = prev.get("challenge_context")
        challenge_started = prev.get("challenge_started_at")
        challenge_reason = prev.get("challenge_reason")
        transition = ""
        prev_lifecycle = lifecycle

    # Default: clear transient fields unless rules set them.
    new_candidate = None
    new_candidate_started = None
    new_candidate_reason = None
    new_challenge = None
    new_challenge_started = None
    new_challenge_reason = None
    new_transition = transition

    # 5. INVALIDATED resets.
    if status == "INVALIDATED":
        active = "OBSERVE"
        lifecycle = "INVALIDATED"
        active_started = timestamp
        active_age = 0
        new_transition = "source context invalidated"
    # 2. OBSERVE
    elif raw == "OBSERVE":
        if active == "OBSERVE":
            lifecycle = "NO_ACTIVE_CONTEXT"
            active_started = active_started or timestamp
            active_age = 0 if active_started == timestamp else active_age + 1
            new_transition = "observe with no active context"
        else:
            # Challenge only — do not kill active directional context.
            lifecycle = "CHALLENGED"
            new_challenge = "OBSERVE"
            new_challenge_started = timestamp
            new_challenge_reason = reason
            active_age = active_age + 1
            new_transition = "observe challenged active context"
    # 3/4 directional
    elif raw in DIRECTIONAL:
        if status == "DEVELOPING":
            if active == "OBSERVE":
                lifecycle = "CANDIDATE"
                new_candidate = raw
                new_candidate_started = timestamp
                new_candidate_reason = reason
                active_age = 0 if active_started is None else active_age + 1
                if active_started is None:
                    active_started = timestamp
                new_transition = "developing directional context is candidate only"
            elif raw == active:
                # Same direction developing: keep active; restore ACTIVE unless already challenged path.
                if prev_lifecycle == "CHALLENGED":
                    lifecycle = "CHALLENGED"
                    # keep previous challenge if any; otherwise no new challenge
                    new_challenge = challenge
                    new_challenge_started = challenge_started
                    new_challenge_reason = challenge_reason
                else:
                    lifecycle = "ACTIVE"
                active_age = active_age + 1
                new_transition = "developing same-direction context keeps active"
            else:
                # Opposite developing: challenge only.
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
            elif raw == active:
                lifecycle = "ACTIVE"
                active_age = active_age + 1
                new_transition = "confirmed same-direction context remains active"
            else:
                active = raw
                lifecycle = "ACTIVE"
                active_started = timestamp
                active_age = 0
                new_transition = "confirmed opposite context replaced active context"
        else:
            # UNKNOWN / other statuses: treat cautiously like developing for flips.
            if active == "OBSERVE":
                lifecycle = "CANDIDATE"
                new_candidate = raw
                new_candidate_started = timestamp
                new_candidate_reason = reason
                if active_started is None:
                    active_started = timestamp
                active_age = 0 if active_started == timestamp else active_age + 1
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
        active_age = active_age + 1 if active != "OBSERVE" else 0
        new_transition = "unhandled raw context"

    if active_started is None:
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
    }


def build_lifecycle_memory(context_frame: pd.DataFrame) -> pd.DataFrame:
    if context_frame is None or len(context_frame) == 0:
        return pd.DataFrame(columns=REQUIRED_MEMORY_COLUMNS)

    work = context_frame.copy()
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
        ts = src["timestamp"]
        step = step_lifecycle(
            raw_market_context=raw,
            raw_context_status=status,
            raw_context_reason=reason,
            timestamp=ts,
            prev=prev,
        )
        row = {
            "timestamp": ts,
            "close": _safe_float(src.get("close")),
            "raw_market_context": raw,
            "raw_context_status": status,
            "raw_cognitive_market_state": _clean_text(src.get("cognitive_market_state"), default="UNKNOWN"),
            "raw_state_direction": _clean_text(src.get("state_direction"), default="UNKNOWN"),
            "raw_context_reason": reason,
            **step,
            "action_allowed": _safe_bool(src.get("action_allowed"), default=False),
            "action_reason": _clean_text(src.get("action_reason"), default="UNKNOWN"),
            "shadow_only": True,
            "builder_version": BUILDER_VERSION,
        }
        # action_allowed must never rewrite active context (already true by construction).
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
            next_ctx = _clean_text(groups[idx][1].iloc[0]["active_market_context"])
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
                "dominant_lifecycle_state": _mode_or_unknown(group["lifecycle_state"]) if "lifecycle_state" in group.columns else "UNKNOWN",
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

    memory = build_lifecycle_memory(context_frame)
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
    else:
        latest = memory.iloc[-1]
        print(f"latest timestamp: {latest['timestamp']}")
        print(f"latest raw_market_context: {latest['raw_market_context']}")
        print(f"latest active_market_context: {latest['active_market_context']}")
        print(f"latest lifecycle_state: {latest['lifecycle_state']}")
        print(f"latest active_context_age_bars: {latest['active_context_age_bars']}")
    print(f"output path memory: {mem_path}")
    print(f"output path episodes: {ep_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
