#!/usr/bin/env python3
"""Standalone shadow builder: final market context memory.

Maps cognitive_market_state → LONG_CONTEXT / SHORT_CONTEXT / OBSERVE.
Does NOT enable execution. action_allowed is always False.
Does NOT touch pipeline / arbitration / visualizer.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BUILDER_VERSION = "final_market_context_memory_v1"
INPUT_PATH = ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet"
OUTPUT_PATH = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
STALE_HOURS = 6.0

REQUIRED_OUTPUT_COLUMNS = [
    "timestamp",
    "close",
    "cognitive_market_state",
    "state_direction",
    "state_status",
    "state_reason",
    "market_context",
    "context_status",
    "context_reason",
    "action_allowed",
    "action_reason",
    "source_state_freshness",
    "builder_version",
    "shadow_only",
]

MARKET_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"})
ACTION_REASON = "shadow market context only; execution disabled"

LONG_STATES = frozenset({"LOWER_ABSORPTION", "ACCEPTANCE_HIGHER", "BUYER_CONTROL"})
SHORT_STATES = frozenset({"UPPER_DISTRIBUTION", "ACCEPTANCE_LOWER", "SELLER_CONTROL"})
OBSERVE_STATES = frozenset({"BALANCE", "UNCERTAIN"})
LONG_DIRECTIONS = frozenset({"BUYER_SUPPORT", "BUYER_CONTROL"})
SHORT_DIRECTIONS = frozenset({"SELLER_PRESSURE", "SELLER_CONTROL"})
OBSERVE_DIRECTIONS = frozenset({"NEUTRAL", "UNKNOWN"})


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


def classify_market_context(
    *,
    cognitive_market_state: str,
    state_direction: str,
    state_status: str,
) -> tuple[str, str]:
    """Return (market_context, context_reason).

    Trading bans must NEVER rewrite SHORT_CONTEXT → OBSERVE.
    """
    state = _clean_text(cognitive_market_state).upper()
    direction = _clean_text(state_direction).upper()
    status = _clean_text(state_status).upper()

    if status == "INVALIDATED":
        return "OBSERVE", "INVALIDATED cognitive state implies OBSERVE"

    if state in LONG_STATES or direction in LONG_DIRECTIONS:
        if state == "LOWER_ABSORPTION":
            return "LONG_CONTEXT", "LOWER_ABSORPTION implies LONG_CONTEXT"
        if state == "ACCEPTANCE_HIGHER":
            return "LONG_CONTEXT", "ACCEPTANCE_HIGHER implies LONG_CONTEXT"
        if state == "BUYER_CONTROL":
            return "LONG_CONTEXT", "BUYER_CONTROL implies LONG_CONTEXT"
        if direction == "BUYER_SUPPORT":
            return "LONG_CONTEXT", "BUYER_SUPPORT direction implies LONG_CONTEXT"
        return "LONG_CONTEXT", "BUYER_CONTROL direction implies LONG_CONTEXT"

    if state in SHORT_STATES or direction in SHORT_DIRECTIONS:
        if state == "UPPER_DISTRIBUTION":
            return "SHORT_CONTEXT", "UPPER_DISTRIBUTION implies SHORT_CONTEXT"
        if state == "ACCEPTANCE_LOWER":
            return "SHORT_CONTEXT", "ACCEPTANCE_LOWER implies SHORT_CONTEXT"
        if state == "SELLER_CONTROL":
            return "SHORT_CONTEXT", "SELLER_CONTROL implies SHORT_CONTEXT"
        if direction == "SELLER_PRESSURE":
            return "SHORT_CONTEXT", "SELLER_PRESSURE direction implies SHORT_CONTEXT"
        return "SHORT_CONTEXT", "SELLER_CONTROL direction implies SHORT_CONTEXT"

    if state == "BALANCE" or direction == "NEUTRAL":
        return "OBSERVE", "BALANCE implies OBSERVE"
    if state == "UNCERTAIN" or direction == "UNKNOWN":
        return "OBSERVE", "UNCERTAIN implies OBSERVE"
    if state in OBSERVE_STATES or direction in OBSERVE_DIRECTIONS:
        return "OBSERVE", "UNCERTAIN implies OBSERVE"

    return "OBSERVE", "insufficient cognitive state evidence implies OBSERVE"


def classify_context_status(
    *,
    market_context: str,
    state_status: str,
) -> str:
    context = _clean_text(market_context).upper()
    status = _clean_text(state_status).upper()

    if status == "INVALIDATED":
        return "INVALIDATED"
    if context == "OBSERVE":
        return "OBSERVE"
    if status == "CONFIRMED":
        return "ACTIVE"
    if status in {"DEVELOPING", "STARTED"}:
        return "DEVELOPING"
    if status == "UNKNOWN":
        return "UNKNOWN"
    return "UNKNOWN"


def assess_source_state_freshness(frame: pd.DataFrame) -> str:
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


def build_final_market_context_rows(state_frame: pd.DataFrame) -> pd.DataFrame:
    if state_frame is None or len(state_frame) == 0:
        return pd.DataFrame(columns=REQUIRED_OUTPUT_COLUMNS)

    work = state_frame.copy()
    if "timestamp" not in work.columns:
        raise ValueError("cognitive_market_state_memory missing required column: timestamp")
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if len(work) == 0:
        return pd.DataFrame(columns=REQUIRED_OUTPUT_COLUMNS)

    freshness = assess_source_state_freshness(work)
    rows: list[dict[str, Any]] = []

    for _, src in work.iterrows():
        state = _clean_text(src.get("cognitive_market_state"), default="UNCERTAIN")
        direction = _clean_text(src.get("state_direction"), default="UNKNOWN")
        status = _clean_text(src.get("state_status"), default="UNKNOWN")
        state_reason = _clean_text(src.get("state_reason"), default="UNKNOWN")

        market_context, context_reason = classify_market_context(
            cognitive_market_state=state,
            state_direction=direction,
            state_status=status,
        )
        if market_context not in MARKET_CONTEXTS:
            raise RuntimeError(f"illegal market_context produced: {market_context}")

        context_status = classify_context_status(
            market_context=market_context,
            state_status=status,
        )

        rows.append(
            {
                "timestamp": src["timestamp"],
                "close": _safe_float(src.get("close")),
                "cognitive_market_state": state,
                "state_direction": direction,
                "state_status": status,
                "state_reason": state_reason,
                "market_context": market_context,
                "context_status": context_status,
                "context_reason": context_reason,
                "action_allowed": False,
                "action_reason": ACTION_REASON,
                "source_state_freshness": freshness,
                "builder_version": BUILDER_VERSION,
                "shadow_only": True,
            }
        )

    out = pd.DataFrame(rows)
    # Invariant: action never enabled at this stage.
    if out["action_allowed"].astype(bool).any():
        raise RuntimeError("action_allowed must remain False")
    if not out["shadow_only"].astype(bool).all():
        raise RuntimeError("shadow_only must remain True")
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
            "Run scripts/research/build_cognitive_market_state_memory.py first.",
            file=sys.stderr,
        )
        return 1

    try:
        state_frame = pd.read_parquet(INPUT_PATH)
    except Exception as exc:
        print(f"ERROR: failed to read {INPUT_PATH}: {exc}", file=sys.stderr)
        return 1

    frame = build_final_market_context_rows(state_frame)
    path = write_atomic_parquet(frame, OUTPUT_PATH)

    if len(frame) == 0:
        print("rows written: 0")
        print("latest timestamp: —")
        print("latest market_context: —")
        print("latest context_status: —")
        print("latest action_allowed: —")
        print(f"output path: {path}")
        return 0

    latest = frame.iloc[-1]
    print(f"rows written: {len(frame)}")
    print(f"latest timestamp: {latest['timestamp']}")
    print(f"latest market_context: {latest['market_context']}")
    print(f"latest context_status: {latest['context_status']}")
    print(f"latest action_allowed: {latest['action_allowed']}")
    print(f"output path: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
