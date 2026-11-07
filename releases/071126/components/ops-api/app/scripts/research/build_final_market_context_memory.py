#!/usr/bin/env python3
"""Standalone shadow builder: final market context memory.

Living process + trend strength → LONG_CONTEXT / SHORT_CONTEXT / OBSERVE.
Bar events (lower absorption, upper distribution) are not context by themselves.
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
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.cognition.living_market_process import (  # noqa: E402
    ProcessSnapshot,
    classify_market_context as classify_living_market_context,
    step_living_process,
)

BUILDER_VERSION = "final_market_context_memory_v2"
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
    "living_process",
    "process_strength",
    "timeframe",
]

MARKET_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"})
ACTION_REASON = "shadow market context only; execution disabled"

# Accepted process only. LOWER_ABSORPTION / UPPER_DISTRIBUTION are events.
LONG_STATES = frozenset({"ACCEPTANCE_HIGHER", "BUYER_CONTROL"})
SHORT_STATES = frozenset({"ACCEPTANCE_LOWER", "SELLER_CONTROL"})
OBSERVE_STATES = frozenset({"BALANCE", "UNCERTAIN", "LOWER_ABSORPTION", "UPPER_DISTRIBUTION"})
LONG_DIRECTIONS = frozenset({"BUYER_CONTROL"})
SHORT_DIRECTIONS = frozenset({"SELLER_CONTROL"})
OBSERVE_DIRECTIONS = frozenset({"NEUTRAL", "UNKNOWN", "BUYER_SUPPORT", "SELLER_PRESSURE"})


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
    prior_context: str | None = None,
    prior_strength: float = 0.0,
    effort_result: str = "UNKNOWN",
    price_result: str = "UNKNOWN",
    effort_side: str = "UNKNOWN",
    volume_effort: str = "UNKNOWN",
    relative_volume: float | None = None,
    relative_spread: float | None = None,
    timeframe: str = "M15",
    prior: ProcessSnapshot | None = None,
) -> tuple[str, str]:
    """Return (market_context, context_reason) from the living process.

    Trading bans must NEVER rewrite SHORT_CONTEXT → OBSERVE.
    """
    return classify_living_market_context(
        cognitive_market_state=cognitive_market_state,
        state_direction=state_direction,
        state_status=state_status,
        prior_context=prior_context,
        prior_strength=prior_strength,
        effort_result=effort_result,
        price_result=price_result,
        effort_side=effort_side,
        volume_effort=volume_effort,
        relative_volume=relative_volume,
        relative_spread=relative_spread,
        timeframe=timeframe,
        prior=prior,
    )


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
    if "timeframe" not in work.columns:
        work["timeframe"] = "M15"
    else:
        work["timeframe"] = work["timeframe"].map(lambda v: _clean_text(v, default="M15"))
    work = work.sort_values(["timeframe", "timestamp"]).reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    prior_by_tf: dict[str, ProcessSnapshot | None] = {}

    for _, src in work.iterrows():
        state = _clean_text(src.get("cognitive_market_state"), default="UNCERTAIN")
        direction = _clean_text(src.get("state_direction"), default="UNKNOWN")
        status = _clean_text(src.get("state_status"), default="UNKNOWN")
        state_reason = _clean_text(src.get("state_reason"), default="UNKNOWN")
        timeframe = _clean_text(src.get("timeframe"), default="M15")
        snap = step_living_process(
            prior_by_tf.get(timeframe),
            cognitive_market_state=state,
            state_direction=direction,
            state_status=status,
            effort_result=_clean_text(src.get("effort_result"), default="UNKNOWN"),
            price_result=_clean_text(src.get("price_result"), default="UNKNOWN"),
            effort_side=_clean_text(src.get("effort_side"), default="UNKNOWN"),
            volume_effort=_clean_text(src.get("volume_effort"), default="UNKNOWN"),
            relative_volume=_safe_float(src.get("relative_volume")),
            relative_spread=_safe_float(src.get("relative_spread")),
            timeframe=timeframe,
        )
        prior_by_tf[timeframe] = snap
        market_context = snap.market_context
        context_reason = snap.context_reason
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
                "living_process": snap.process,
                "process_strength": float(snap.strength),
                "timeframe": timeframe,
            }
        )

    out = pd.DataFrame(rows)
    out = out.sort_values(["timeframe", "timestamp"]).reset_index(drop=True)
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
