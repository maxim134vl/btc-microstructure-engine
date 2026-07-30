"""SHADOW_ZONE_REACTION_V1 — causal price-path reaction proof for volume zones."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from . import DEFAULT_TICK_SIZE
from .timeutil import iso, parse_ts

REACTION_MODEL = "SHADOW_ZONE_REACTION_V1"

REACTION_THRESHOLDS = {
    "REACTION_050_ZONE_WIDTH": 0.50,
    "REACTION_100_ZONE_WIDTH": 1.00,
    "REACTION_150_ZONE_WIDTH": 1.50,
}

REACTION_STATUSES_V1 = (
    "PROVEN",
    "NOT_TOUCHED",
    "TOUCHED_NO_REACTION",
    "INVALIDATED_BEFORE_REACTION",
    "REACTION_TOO_SMALL",
    "WRONG_TIMEFRAME",
    "INSUFFICIENT_EVENT_HISTORY",
    "FUTURE_EVIDENCE_REJECTED",
    "AMBIGUOUS",
)

ZONE_AGE_POLICIES = {
    "ZONE_AGE_2_BARS": 2,
    "ZONE_AGE_4_BARS": 4,
    "ZONE_AGE_8_BARS": 8,
    "ZONE_UNTIL_INVALIDATED": None,
}


def reaction_threshold_distance(*, zone: dict[str, Any], threshold_id: str, tick_size: float = DEFAULT_TICK_SIZE) -> float:
    width = abs(float(zone["upper_boundary"]) - float(zone["lower_boundary"]))
    mult = float(REACTION_THRESHOLDS[threshold_id])
    return max(width * mult, float(tick_size))


def prove_zone_reaction(
    *,
    zone: dict[str, Any],
    direction: str,  # BULLISH | BEARISH
    events: pd.DataFrame,
    zone_created_at: datetime,
    decision_ts: datetime,
    threshold_id: str,
    tick_size: float = DEFAULT_TICK_SIZE,
    zone_timeframe: str | None = None,
    expected_timeframe: str | None = None,
) -> dict[str, Any]:
    """Prove reaction after zone creation and before decision using executable path prices."""
    out: dict[str, Any] = {
        "reaction_model": REACTION_MODEL,
        "reaction_threshold_id": threshold_id,
        "status": "INSUFFICIENT_EVENT_HISTORY",
        "direction": direction,
        "touch_timestamp": None,
        "reaction_timestamp": None,
        "threshold_distance": None,
        "displacement": None,
        "zone_created_at": iso(zone_created_at),
        "decision_timestamp": iso(decision_ts),
    }
    if expected_timeframe and zone_timeframe and str(zone_timeframe).upper() != str(expected_timeframe).upper():
        out["status"] = "WRONG_TIMEFRAME"
        return out
    if zone_created_at >= decision_ts:
        out["status"] = "FUTURE_EVIDENCE_REJECTED"
        return out

    lower = float(zone["lower_boundary"])
    upper = float(zone["upper_boundary"])
    thr = reaction_threshold_distance(zone=zone, threshold_id=threshold_id, tick_size=tick_size)
    out["threshold_distance"] = thr

    if events is None or events.empty or "_ts" not in events.columns:
        out["status"] = "INSUFFICIENT_EVENT_HISTORY"
        return out

    df = events.copy()
    df["_ts"] = pd.to_datetime(df["_ts"], utc=True)
    # Reject any future evidence beyond decision
    if (df["_ts"] > pd.Timestamp(decision_ts)).any() and False:
        # We filter rather than fail the whole series; future rows are dropped.
        pass
    future = df[df["_ts"] > pd.Timestamp(decision_ts)]
    if not future.empty and (df["_ts"] <= pd.Timestamp(zone_created_at)).all():
        out["status"] = "FUTURE_EVIDENCE_REJECTED"
        return out

    window = df[(df["_ts"] > pd.Timestamp(zone_created_at)) & (df["_ts"] <= pd.Timestamp(decision_ts))]
    if window.empty:
        out["status"] = "INSUFFICIENT_EVENT_HISTORY"
        return out

    # Prefer executable mid from BBO; else trade price.
    if "best_bid_price" in window.columns and "best_ask_price" in window.columns:
        px = (window["best_bid_price"].astype(float) + window["best_ask_price"].astype(float)) / 2.0
        # For displacement use directional executable: bullish exit above uses ask; we use mid for touch,
        # ask for bullish displacement, bid for bearish displacement when available.
        ask = window["best_ask_price"].astype(float)
        bid = window["best_bid_price"].astype(float)
    else:
        px = window["price"].astype(float)
        ask = px
        bid = px

    touched = False
    touch_ts = None
    invalidated_before = False
    proven = False
    reaction_ts = None
    displacement = None
    too_small = False

    for i, (_, row) in enumerate(window.iterrows()):
        p = float(px.iloc[i])
        a = float(ask.iloc[i])
        b = float(bid.iloc[i])
        ts = row["_ts"].to_pydatetime()

        if direction == "BULLISH":
            # Invalidation: fully through distal (below lower)
            if touched and (not proven) and b < lower - 1e-12:
                invalidated_before = True
                break
            if (not touched) and (p <= upper + 1e-12) and (p >= lower - 1e-12 or b <= upper):
                touched = True
                touch_ts = ts
                continue
            if touched and not proven:
                disp = a - upper
                if disp + 1e-12 >= thr:
                    proven = True
                    reaction_ts = ts
                    displacement = disp
                    break
                if a > upper + 1e-12:
                    too_small = True
                    displacement = disp
        else:  # BEARISH
            if touched and (not proven) and a > upper + 1e-12:
                invalidated_before = True
                break
            if (not touched) and (p >= lower - 1e-12) and (p <= upper + 1e-12 or a >= lower):
                touched = True
                touch_ts = ts
                continue
            if touched and not proven:
                disp = lower - b
                if disp + 1e-12 >= thr:
                    proven = True
                    reaction_ts = ts
                    displacement = disp
                    break
                if b < lower - 1e-12:
                    too_small = True
                    displacement = disp

    out["touch_timestamp"] = iso(touch_ts)
    out["reaction_timestamp"] = iso(reaction_ts)
    out["displacement"] = displacement

    if reaction_ts and pd.Timestamp(reaction_ts) > pd.Timestamp(decision_ts):
        out["status"] = "FUTURE_EVIDENCE_REJECTED"
        return out
    if invalidated_before:
        out["status"] = "INVALIDATED_BEFORE_REACTION"
        return out
    if proven:
        out["status"] = "PROVEN"
        return out
    if not touched:
        out["status"] = "NOT_TOUCHED"
        return out
    if too_small:
        out["status"] = "REACTION_TOO_SMALL"
        return out
    out["status"] = "TOUCHED_NO_REACTION"
    return out


def zone_age_ok(
    *,
    source_candle_open: datetime,
    decision_ts: datetime,
    timeframe: str,
    age_policy: str,
    tf_seconds: int,
) -> bool:
    max_bars = ZONE_AGE_POLICIES.get(age_policy)
    if max_bars is None:
        return True  # until invalidated handled separately
    # Age in source TF bars from source open to prior closed relative to decision
    from .timeutil import candle_open

    decision_open = candle_open(decision_ts, tf_seconds)
    # bars elapsed = (decision_open - source_open) / tf_seconds
    delta = (decision_open - source_candle_open).total_seconds() / float(tf_seconds)
    # source must be a completed bar before decision: delta >= 1
    return 1 <= delta <= float(max_bars)


def zone_invalidated_by_path(
    *,
    zone: dict[str, Any],
    direction: str,
    events: pd.DataFrame,
    zone_created_at: datetime,
    decision_ts: datetime,
) -> bool:
    """True if price fully traversed distal boundary before decision."""
    if events is None or events.empty:
        return False
    lower = float(zone["lower_boundary"])
    upper = float(zone["upper_boundary"])
    df = events.copy()
    df["_ts"] = pd.to_datetime(df["_ts"], utc=True)
    window = df[(df["_ts"] > pd.Timestamp(zone_created_at)) & (df["_ts"] <= pd.Timestamp(decision_ts))]
    if window.empty:
        return False
    if "best_bid_price" in window.columns:
        bid = window["best_bid_price"].astype(float)
        ask = window["best_ask_price"].astype(float)
    else:
        bid = ask = window["price"].astype(float)
    if direction == "BULLISH":
        return bool((bid < lower - 1e-12).any())
    return bool((ask > upper + 1e-12).any())
