"""Track behavioral propagation across MTF hierarchy."""

from __future__ import annotations

from typing import Any

import pandas as pd

from visual_cognition.behavioral_overlay_engine import classify_initiative, continuation_health, detect_behaviors


def _state_at_timeframe(
    cognition: pd.DataFrame,
    candles_by_tf: dict[str, pd.DataFrame],
    timestamp: pd.Timestamp,
    timeframe: str,
) -> dict[str, Any]:
    bars = candles_by_tf.get(timeframe, pd.DataFrame())
    if len(bars) == 0:
        return {"timeframe": timeframe, "status": "NO_DATA"}

    bars = bars.sort_values("timestamp")
    prior_bars = bars[bars["timestamp"] <= timestamp]
    if len(prior_bars) == 0:
        bar = bars.iloc[0]
    else:
        bar = prior_bars.iloc[-1]

    cog = cognition[cognition["timestamp"] <= timestamp] if len(cognition) else pd.DataFrame()
    cog_row = cog.iloc[-1] if len(cog) else pd.Series({**bar.to_dict()})

    merged = pd.Series({**cog_row.to_dict(), **bar.to_dict()})
    initiative = classify_initiative(merged)
    behaviors = detect_behaviors(merged)
    health = continuation_health(merged)

    return {
        "timeframe": timeframe,
        "timestamp": bar["timestamp"].isoformat() if hasattr(bar["timestamp"], "isoformat") else str(bar["timestamp"]),
        "initiative": initiative,
        "behaviors": behaviors,
        "continuation_health": health,
        "synthesis_state": merged.get("synthesis_state"),
        "trigger_event": merged.get("trigger_event"),
        "climax_state": merged.get("climax_state"),
    }


def _describe_tf_state(state: dict[str, Any]) -> str:
    tf = state["timeframe"]
    if state.get("status") == "NO_DATA":
        return f"{tf}: no cognition data"

    parts: list[str] = []
    initiative = state.get("initiative", "dormant")
    health = state.get("continuation_health", 0.5)
    behaviors = state.get("behaviors") or []

    if "BUYING_CLIMAX" in behaviors or "SELLING_CLIMAX" in behaviors:
        climax = "buying climax" if "BUYING_CLIMAX" in behaviors else "selling climax"
        parts.append(climax)
    elif health < 0.35:
        parts.append(f"{initiative} continuation collapsing")
    elif health < 0.55:
        parts.append(f"{initiative} continuation weakening")
    elif "ROTATIONAL_PRESSURE" in behaviors:
        parts.append("rotational pressure increasing")
    elif "STOPPING_ACTIVITY" in behaviors or "ABSORPTION" in behaviors:
        parts.append("stopping / absorption activity")
    elif initiative == "buyer":
        parts.append("buyer initiative dominant")
    elif initiative == "seller":
        parts.append("seller initiative dominant")
    else:
        parts.append("neutral rotation")

    return f"{tf}: {' · '.join(parts)}"


def track_propagation(
    cognition: pd.DataFrame,
    candles_by_tf: dict[str, pd.DataFrame],
    timestamp: pd.Timestamp,
) -> dict[str, Any]:
    """Build MTF propagation chain D1 → H4 → H1 → M15."""

    order = ("D1", "H4", "H1", "M15")
    states = [_state_at_timeframe(cognition, candles_by_tf, timestamp, tf) for tf in order]
    chain = [_describe_tf_state(state) for state in states]

    inheritance: list[dict[str, Any]] = []
    for index in range(1, len(states)):
        parent = states[index - 1]
        child = states[index]
        if parent.get("status") == "NO_DATA" or child.get("status") == "NO_DATA":
            continue
        parent_health = parent.get("continuation_health", 0.5)
        child_health = child.get("continuation_health", 0.5)
        signal = "stable"
        if parent_health < 0.5 and child_health < parent_health - 0.1:
            signal = "intensified"
        elif parent_health < 0.5 and child_health <= parent_health + 0.05:
            signal = "reflected"
        elif child_health < 0.35:
            signal = "collapsed"
        inheritance.append(
            {
                "from": parent["timeframe"],
                "to": child["timeframe"],
                "signal": signal,
                "parent_health": parent_health,
                "child_health": child_health,
            }
        )

    narrative_parts: list[str] = []
    for line in chain:
        narrative_parts.append(line.split(": ", 1)[-1])
    summary = " → ".join(narrative_parts)

    return {
        "chain": chain,
        "states": states,
        "inheritance": inheritance,
        "summary": summary,
    }
