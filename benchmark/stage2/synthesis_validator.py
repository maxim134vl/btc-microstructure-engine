"""Validate Stage 2 synthesis conclusions against forward market behavior."""

from __future__ import annotations

from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet

FORWARD_HORIZON = 11

SYNTHESIS_BIAS: dict[str, dict[str, Any]] = {
    "LOCAL_EXHAUSTION": {
        "bias": "bearish",
        "narrative": "local exhaustion with downside risk",
        "coherence_base": 0.7,
    },
    "INTERMEDIATE_REVERSAL": {
        "bias": "reversal",
        "narrative": "intermediate reversal structure",
        "coherence_base": 0.75,
    },
    "STRUCTURAL_REVERSAL": {
        "bias": "reversal",
        "narrative": "structural reversal with multi-timeframe confirmation",
        "coherence_base": 0.85,
    },
}

REGIME_BIAS: dict[str, str] = {
    "DISTRIBUTION_REGIME": "bearish",
    "ABSORPTION_REGIME": "neutral",
    "HIGH_CONVICTION_AUCTION": "trend",
    "STRUCTURAL_REGIME": "trend",
    "ABSORPTION_RECOVERY": "bullish",
    "UNCERTAIN": "neutral",
}


def _load_candles() -> pd.DataFrame:
    frame = safe_read_parquet("candle_structure_memory.parquet")
    if len(frame) == 0:
        return frame
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame.sort_values("timestamp").reset_index(drop=True)


def _forward_window(candles: pd.DataFrame, ts: pd.Timestamp, horizon: int) -> pd.DataFrame:
    idx = candles.index[candles["timestamp"] == ts]
    if len(idx) == 0:
        pos = int(candles["timestamp"].searchsorted(ts))
        if pos >= len(candles):
            return candles.iloc[0:0]
        start = pos
    else:
        start = int(idx[0])
    return candles.iloc[start + 1 : start + 1 + horizon]


def _measure_forward(forward: pd.DataFrame, entry_price: float) -> dict[str, Any]:
    if len(forward) == 0 or entry_price <= 0:
        return {
            "move_pct": 0.0,
            "follow_through": "NONE",
            "max_up_pct": 0.0,
            "max_down_pct": 0.0,
            "forward_candles": 0,
            "direction": "flat",
        }

    closes = forward["close"].astype(float)
    final = float(closes.iloc[-1])
    move_pct = (final - entry_price) / entry_price
    max_up = float((forward["high"].max() - entry_price) / entry_price)
    max_down = float((entry_price - forward["low"].min()) / entry_price)

    if abs(move_pct) >= 0.02:
        strength = "STRONG"
    elif abs(move_pct) >= 0.008:
        strength = "MODERATE"
    elif abs(move_pct) >= 0.002:
        strength = "WEAK"
    else:
        strength = "NONE"

    direction = "up" if move_pct > 0.001 else "down" if move_pct < -0.001 else "flat"
    return {
        "move_pct": round(move_pct * 100, 3),
        "max_up_pct": round(max_up * 100, 3),
        "max_down_pct": round(max_down * 100, 3),
        "follow_through": strength,
        "forward_candles": len(forward),
        "direction": direction,
    }


def _resolve_bias(row: pd.Series) -> dict[str, Any]:
    synthesis = str(row.get("synthesis_state", ""))
    spec = SYNTHESIS_BIAS.get(synthesis)
    if spec:
        return {**spec, "source": "synthesis_state", "value": synthesis}

    regime = str(row.get("auction_regime") or row.get("regime_state") or "")
    bias = REGIME_BIAS.get(regime)
    if bias:
        return {
            "bias": bias,
            "narrative": f"{regime} regime inference",
            "coherence_base": 0.6,
            "source": "auction_regime",
            "value": regime,
        }

    trigger = str(row.get("trigger_event", ""))
    if "CLIMAX" in trigger:
        return {
            "bias": "reversal",
            "narrative": "climax-driven reversal expectation",
            "coherence_base": 0.55,
            "source": "trigger_event",
            "value": trigger,
        }

    return {
        "bias": "neutral",
        "narrative": "unclassified reasoning",
        "coherence_base": 0.4,
        "source": None,
        "value": None,
    }


def _score_synthesis(bias: str, outcome: dict[str, Any]) -> tuple[str, str]:
    move = outcome["move_pct"] / 100.0
    threshold = 0.003

    if bias == "neutral":
        if abs(move) <= 0.01:
            return "CONFIRMED", "Market remained balanced as Stage 2 expected."
        if abs(move) <= 0.02:
            return "PARTIAL", "Moderate drift — partial narrative confirmation."
        return "FAILED", "Large move despite neutral Stage 2 reasoning."

    if bias == "reversal":
        if abs(move) >= threshold:
            return "CONFIRMED", "Market transitioned after reversal narrative."
        return "PARTIAL", "Limited transition after reversal reasoning."

    if bias == "bullish":
        if move >= threshold:
            return "CONFIRMED", "Upside continuation confirmed Stage 2 narrative."
        if move <= -threshold:
            return "FALSE_NARRATIVE", "Market moved opposite to bullish reasoning."
        return "PARTIAL", "Weak upside confirmation."

    if bias == "bearish":
        if move <= -threshold:
            return "CONFIRMED", "Downside auction confirmed distribution narrative."
        if move >= threshold:
            return "FALSE_NARRATIVE", "Market reversed upward against distribution narrative."
        return "PARTIAL", "Weak downside confirmation."

    if bias == "trend":
        if abs(move) >= threshold:
            return "CONFIRMED", "Trend continuation aligned with conviction narrative."
        return "PARTIAL", "Trend narrative lacked follow-through."

    return "PARTIAL", "Insufficient synthesis bias classification."


def validate_synthesis(row: pd.Series, *, horizon: int = FORWARD_HORIZON) -> dict[str, Any]:
    candles = _load_candles()
    ts = pd.to_datetime(row["timestamp"])
    entry = float(row["close"]) if pd.notna(row.get("close")) and float(row["close"]) > 0 else 0.0
    forward = _forward_window(candles, ts, horizon)
    outcome = _measure_forward(forward, entry)
    bias_spec = _resolve_bias(row)
    verdict, note = _score_synthesis(bias_spec["bias"], outcome)

    direction_word = outcome["direction"]
    observed = (
        f"Market moved {direction_word} {abs(outcome['move_pct']):.2f}% "
        f"over next {outcome['forward_candles']} candles."
    )
    if verdict == "CONFIRMED" and bias_spec["bias"] == "bearish" and outcome["direction"] == "down":
        observed = (
            f"Market transitioned into downside auction over next {outcome['forward_candles']} candles "
            f"({abs(outcome['move_pct']):.2f}%)."
        )

    return {
        "bias_spec": bias_spec,
        "outcome": outcome,
        "observed_outcome": observed,
        "synthesis_verdict": verdict,
        "synthesis_note": note,
        "narrative_coherence": bias_spec["coherence_base"],
    }
