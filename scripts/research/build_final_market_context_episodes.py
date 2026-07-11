#!/usr/bin/env python3
"""Standalone shadow builder: final market context episodes.

Groups consecutive identical market_context rows into episodes for visualization.
Does NOT invent lifetimes, rewrite contexts, or touch pipeline/arbitration.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BUILDER_VERSION = "final_market_context_episodes_v1"
INPUT_PATH = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
OUTPUT_PATH = ROOT / "data" / "cognition" / "final_market_context_episodes.parquet"

REQUIRED_OUTPUT_COLUMNS = [
    "episode_id",
    "market_context",
    "start_time",
    "end_time",
    "start_close",
    "end_close",
    "bars_count",
    "duration_minutes",
    "start_cognitive_market_state",
    "end_cognitive_market_state",
    "start_context_status",
    "end_context_status",
    "dominant_context_status",
    "dominant_state_direction",
    "action_allowed_any",
    "action_allowed_all",
    "shadow_only",
    "start_reason",
    "end_reason",
    "builder_version",
]

ALLOWED_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"})


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


def build_final_market_context_episodes(context_frame: pd.DataFrame) -> pd.DataFrame:
    if context_frame is None or len(context_frame) == 0:
        return pd.DataFrame(columns=REQUIRED_OUTPUT_COLUMNS)

    work = context_frame.copy()
    if "timestamp" not in work.columns:
        raise ValueError("final_market_context_memory missing required column: timestamp")
    if "market_context" not in work.columns:
        raise ValueError("final_market_context_memory missing required column: market_context")

    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if len(work) == 0:
        return pd.DataFrame(columns=REQUIRED_OUTPUT_COLUMNS)

    work["market_context"] = work["market_context"].map(lambda v: _clean_text(v, default="OBSERVE"))
    illegal = sorted(set(work["market_context"]) - ALLOWED_CONTEXTS)
    if illegal:
        raise RuntimeError(f"unexpected market_context values in source: {illegal}")

    # Episode boundaries: first row or market_context change vs previous.
    changed = work["market_context"] != work["market_context"].shift(1)
    changed.iloc[0] = True
    work["_episode_group"] = changed.cumsum()

    episodes: list[dict[str, Any]] = []
    groups = list(work.groupby("_episode_group", sort=True))
    for idx, (_, group) in enumerate(groups, start=1):
        group = group.sort_values("timestamp")
        start = group.iloc[0]
        end = group.iloc[-1]
        market_context = _clean_text(start["market_context"])
        start_time = start["timestamp"]
        end_time = end["timestamp"]
        duration_minutes = float((end_time - start_time).total_seconds() / 60.0)

        if idx < len(groups):
            next_ctx = _clean_text(groups[idx][1].iloc[0]["market_context"])
            end_reason = f"market_context changed from {market_context} to {next_ctx}"
        else:
            end_reason = "latest open episode"

        action_flags = group["action_allowed"].map(_safe_bool) if "action_allowed" in group.columns else pd.Series([False] * len(group))

        episodes.append(
            {
                "episode_id": idx,
                "market_context": market_context,
                "start_time": start_time,
                "end_time": end_time,
                "start_close": _safe_float(start.get("close")),
                "end_close": _safe_float(end.get("close")),
                "bars_count": int(len(group)),
                "duration_minutes": duration_minutes,
                "start_cognitive_market_state": _clean_text(start.get("cognitive_market_state"), default="UNKNOWN"),
                "end_cognitive_market_state": _clean_text(end.get("cognitive_market_state"), default="UNKNOWN"),
                "start_context_status": _clean_text(start.get("context_status"), default="UNKNOWN"),
                "end_context_status": _clean_text(end.get("context_status"), default="UNKNOWN"),
                "dominant_context_status": _mode_or_unknown(group["context_status"]) if "context_status" in group.columns else "UNKNOWN",
                "dominant_state_direction": _mode_or_unknown(group["state_direction"]) if "state_direction" in group.columns else "UNKNOWN",
                "action_allowed_any": bool(action_flags.any()),
                "action_allowed_all": bool(len(action_flags) > 0 and action_flags.all()),
                "shadow_only": True,
                "start_reason": _clean_text(start.get("context_reason"), default="UNKNOWN"),
                "end_reason": end_reason,
                "builder_version": BUILDER_VERSION,
            }
        )

    out = pd.DataFrame(episodes)
    if len(out) and not out["shadow_only"].astype(bool).all():
        raise RuntimeError("shadow_only must remain True")
    # Must not invent new context labels.
    if len(out) and sorted(set(out["market_context"]) - ALLOWED_CONTEXTS):
        raise RuntimeError("episode builder altered market_context vocabulary")
    return out[REQUIRED_OUTPUT_COLUMNS]


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

    frame = build_final_market_context_episodes(context_frame)
    path = write_atomic_parquet(frame, OUTPUT_PATH)

    if len(frame) == 0:
        print("rows written: 0")
        print("latest episode_id: —")
        print("latest market_context: —")
        print("latest start_time: —")
        print("latest end_time: —")
        print("latest bars_count: —")
        print(f"output path: {path}")
        return 0

    latest = frame.iloc[-1]
    print(f"rows written: {len(frame)}")
    print(f"latest episode_id: {latest['episode_id']}")
    print(f"latest market_context: {latest['market_context']}")
    print(f"latest start_time: {latest['start_time']}")
    print(f"latest end_time: {latest['end_time']}")
    print(f"latest bars_count: {latest['bars_count']}")
    print(f"output path: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
