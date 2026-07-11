#!/usr/bin/env python3
"""Standalone shadow builder: cognitive market state memory.

Interprets auction_episode_memory into cognitive market process states.
Does NOT emit LONG_CONTEXT / SHORT_CONTEXT and does NOT touch arbitration/pipeline.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BUILDER_VERSION = "cognitive_market_state_memory_v1"
INPUT_PATH = ROOT / "data" / "cognition" / "auction_episode_memory.parquet"
OUTPUT_PATH = ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet"
STALE_HOURS = 6.0

REQUIRED_OUTPUT_COLUMNS = [
    "timestamp",
    "close",
    "primary_auction_episode",
    "primary_episode_status",
    "primary_episode_reason",
    "cognitive_market_state",
    "state_direction",
    "state_status",
    "state_reason",
    "auction_location",
    "effort_side",
    "effort_result",
    "price_result",
    "follow_through",
    "source_episode_freshness",
    "source_episode_row_count",
    "builder_version",
    "shadow_only",
]

COGNITIVE_STATES = frozenset(
    {
        "UPPER_DISTRIBUTION",
        "LOWER_ABSORPTION",
        "ACCEPTANCE_HIGHER",
        "ACCEPTANCE_LOWER",
        "BUYER_CONTROL",
        "SELLER_CONTROL",
        "BALANCE",
        "UNCERTAIN",
    }
)


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


def map_state_status(episode_status: str) -> str:
    status = _clean_text(episode_status).upper()
    if status in {"DEVELOPING", "STARTED"}:
        return "DEVELOPING"
    if status == "CONFIRMED":
        return "CONFIRMED"
    if status == "INVALIDATED":
        return "INVALIDATED"
    return "UNKNOWN"


def classify_cognitive_market_state(
    *,
    auction_episode: str,
    episode_status: str,
    effort_side: str = "UNKNOWN",
    effort_result: str = "UNKNOWN",
) -> tuple[str, str, str]:
    """Return (cognitive_market_state, state_direction, state_reason)."""
    episode = _clean_text(auction_episode).upper()
    status = _clean_text(episode_status).upper()
    side = _clean_text(effort_side).upper()
    result = _clean_text(effort_result).upper()
    invalidated = status == "INVALIDATED"

    if not invalidated and episode in {"UPPER_DISTRIBUTION", "FAILED_BREAKOUT"}:
        return (
            "UPPER_DISTRIBUTION",
            "SELLER_PRESSURE",
            "auction episode UPPER_DISTRIBUTION implies seller pressure"
            if episode == "UPPER_DISTRIBUTION"
            else "auction episode FAILED_BREAKOUT implies seller pressure",
        )

    if not invalidated and episode in {"LOWER_ABSORPTION", "FAILED_BREAKDOWN"}:
        return (
            "LOWER_ABSORPTION",
            "BUYER_SUPPORT",
            "auction episode LOWER_ABSORPTION implies buyer support"
            if episode == "LOWER_ABSORPTION"
            else "auction episode FAILED_BREAKDOWN implies buyer support",
        )

    if episode == "ACCEPTANCE_HIGHER":
        return (
            "ACCEPTANCE_HIGHER",
            "BUYER_CONTROL",
            "auction episode ACCEPTANCE_HIGHER implies buyer control",
        )

    if episode == "ACCEPTANCE_LOWER":
        return (
            "ACCEPTANCE_LOWER",
            "SELLER_CONTROL",
            "auction episode ACCEPTANCE_LOWER implies seller control",
        )

    if episode == "CONTINUATION" and side == "BUYER" and result in {"ACCEPTED", "CONTINUED"}:
        return (
            "BUYER_CONTROL",
            "BUYER_CONTROL",
            "auction episode CONTINUATION with buyer accepted/continued effort",
        )

    if episode == "CONTINUATION" and side == "SELLER" and result in {"ACCEPTED", "CONTINUED"}:
        return (
            "SELLER_CONTROL",
            "SELLER_CONTROL",
            "auction episode CONTINUATION with seller accepted/continued effort",
        )

    if episode == "BALANCE":
        return (
            "BALANCE",
            "NEUTRAL",
            "auction episode BALANCE has no directional dominance",
        )

    if episode == "UNKNOWN" or episode == "":
        return (
            "UNCERTAIN",
            "UNKNOWN",
            "insufficient auction evidence",
        )

    # CONTINUATION without clear side/result, INVALIDATED mapped episodes, etc.
    if invalidated:
        return (
            "UNCERTAIN",
            "UNKNOWN",
            "primary auction episode invalidated; insufficient confirmed auction evidence",
        )

    return (
        "UNCERTAIN",
        "UNKNOWN",
        "insufficient auction evidence",
    )


def assess_source_episode_freshness(frame: pd.DataFrame) -> str:
    if frame is None or len(frame) == 0 or "timestamp" not in frame.columns:
        return "missing"
    ts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce").dropna()
    if len(ts) == 0:
        return "missing"
    latest = ts.iloc[-1]
    now = pd.Timestamp.now(tz="UTC")
    age_hours = (now - latest).total_seconds() / 3600.0
    if age_hours > STALE_HOURS:
        return "stale"
    return "fresh"


def build_cognitive_market_state_rows(episode_frame: pd.DataFrame) -> pd.DataFrame:
    if episode_frame is None or len(episode_frame) == 0:
        return pd.DataFrame(columns=REQUIRED_OUTPUT_COLUMNS)

    work = episode_frame.copy()
    if "timestamp" not in work.columns:
        raise ValueError("auction_episode_memory missing required column: timestamp")
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if len(work) == 0:
        return pd.DataFrame(columns=REQUIRED_OUTPUT_COLUMNS)

    freshness = assess_source_episode_freshness(work)
    row_count = int(len(work))
    rows: list[dict[str, Any]] = []

    for _, src in work.iterrows():
        episode = _clean_text(src.get("auction_episode"), default="UNKNOWN")
        episode_status = _clean_text(src.get("episode_status"), default="UNKNOWN")
        episode_reason = _clean_text(src.get("episode_reason"), default="UNKNOWN")
        effort_side = _clean_text(src.get("effort_side"), default="UNKNOWN")
        effort_result = _clean_text(src.get("effort_result"), default="UNKNOWN")
        state, direction, reason = classify_cognitive_market_state(
            auction_episode=episode,
            episode_status=episode_status,
            effort_side=effort_side,
            effort_result=effort_result,
        )
        if state not in COGNITIVE_STATES:
            raise RuntimeError(f"illegal cognitive_market_state produced: {state}")

        rows.append(
            {
                "timestamp": src["timestamp"],
                "close": _safe_float(src.get("close")),
                "primary_auction_episode": episode,
                "primary_episode_status": episode_status,
                "primary_episode_reason": episode_reason,
                "cognitive_market_state": state,
                "state_direction": direction,
                "state_status": map_state_status(episode_status),
                "state_reason": reason,
                "auction_location": _clean_text(src.get("auction_location"), default="UNKNOWN"),
                "effort_side": effort_side,
                "effort_result": effort_result,
                "price_result": _clean_text(src.get("price_result"), default="UNKNOWN"),
                "follow_through": _clean_text(src.get("follow_through"), default="UNKNOWN"),
                "source_episode_freshness": freshness,
                "source_episode_row_count": row_count,
                "builder_version": BUILDER_VERSION,
                "shadow_only": True,
            }
        )

    out = pd.DataFrame(rows)
    forbidden = {"LONG_CONTEXT", "SHORT_CONTEXT"}
    for col in ("cognitive_market_state", "state_direction", "primary_auction_episode"):
        if col in out.columns and out[col].astype(str).isin(forbidden).any():
            raise RuntimeError(f"forbidden context token leaked into {col}")
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
            "Run scripts/research/build_auction_episode_memory.py first.",
            file=sys.stderr,
        )
        return 1

    try:
        episode_frame = pd.read_parquet(INPUT_PATH)
    except Exception as exc:
        print(f"ERROR: failed to read {INPUT_PATH}: {exc}", file=sys.stderr)
        return 1

    frame = build_cognitive_market_state_rows(episode_frame)
    path = write_atomic_parquet(frame, OUTPUT_PATH)

    if len(frame) == 0:
        print("rows written: 0")
        print("latest timestamp: —")
        print("latest cognitive_market_state: —")
        print("latest state_status: —")
        print("latest state_direction: —")
        print(f"output path: {path}")
        return 0

    latest = frame.iloc[-1]
    print(f"rows written: {len(frame)}")
    print(f"latest timestamp: {latest['timestamp']}")
    print(f"latest cognitive_market_state: {latest['cognitive_market_state']}")
    print(f"latest state_status: {latest['state_status']}")
    print(f"latest state_direction: {latest['state_direction']}")
    print(f"output path: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
