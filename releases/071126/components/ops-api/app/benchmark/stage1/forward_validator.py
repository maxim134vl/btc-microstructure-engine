"""Compare Stage 1 beliefs against forward market behavior."""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchmark.stage1.event_extractor import event_to_interpretation
from parquet_utils import safe_read_parquet

FORWARD_HORIZON = 7

# Cognitive expectations — direction of market confirmation, not PnL targets.
EXPECTATIONS: dict[str, dict[str, Any]] = {
    "BUYING_CLIMAX": {"bias": "bearish", "label": "buyer climax exhaustion"},
    "SELLING_CLIMAX": {"bias": "bullish", "label": "seller climax exhaustion"},
    "STOPPING_VOLUME": {"bias": "bullish", "label": "stopping support"},
    "EXHAUSTION_VOLUME": {"bias": "bearish", "label": "volume exhaustion"},
    "ABSORPTION_VOLUME": {"bias": "neutral", "label": "absorption / balance"},
    "CONTINUATION_VOLUME": {"bias": "trend", "label": "efficient continuation"},
    "CLIMAX_EXHAUSTION": {"bias": "bearish", "label": "climax exhaustion"},
    "CLIMAX_ABSORPTION": {"bias": "neutral", "label": "climax absorption"},
    "EXHAUSTION_RESPONSE": {"bias": "bearish", "label": "exhaustion response"},
    "ABSORPTION_RESPONSE": {"bias": "neutral", "label": "absorption response"},
    "EFFICIENT_CONTINUATION": {"bias": "trend", "label": "efficient continuation"},
    "LOCAL_EXHAUSTION": {"bias": "bearish", "label": "local exhaustion"},
    "INTERMEDIATE_REVERSAL": {"bias": "reversal", "label": "intermediate reversal"},
    "STRUCTURAL_REVERSAL": {"bias": "reversal", "label": "structural reversal"},
    "climax": {"bias": "reversal", "label": "volume climax"},
    "stopping": {"bias": "bullish", "label": "stopping activity"},
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
        idx = [candles["timestamp"].searchsorted(ts)]
    start = int(idx[0])
    return candles.iloc[start + 1 : start + 1 + horizon]


def _detect_bias(row: pd.Series) -> dict[str, Any] | None:
    for key in (
        "trigger_event",
        "volume_event",
        "climax_state",
        "effort_result_state",
        "synthesis_state",
        "volume_class",
    ):
        val = row.get(key)
        if pd.isna(val):
            continue
        spec = EXPECTATIONS.get(str(val))
        if spec:
            return {**spec, "source_field": key, "source_value": str(val)}
    if pd.notna(row.get("delta")):
        bias = "bullish" if float(row["delta"]) > 0 else "bearish"
        return {"bias": bias, "label": f"{bias} delta initiative", "source_field": "delta"}
    return None


def _measure_forward(forward: pd.DataFrame, entry_price: float) -> dict[str, Any]:
    if len(forward) == 0:
        return {
            "move_pct": 0.0,
            "follow_through": "NONE",
            "max_up_pct": 0.0,
            "max_down_pct": 0.0,
            "forward_candles": 0,
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

    return {
        "move_pct": round(move_pct * 100, 3),
        "max_up_pct": round(max_up * 100, 3),
        "max_down_pct": round(max_down * 100, 3),
        "follow_through": strength,
        "forward_candles": len(forward),
    }


def _score_verdict(bias: str, outcome: dict[str, Any], delta: float | None) -> tuple[str, bool, str]:
    move = outcome["move_pct"] / 100.0
    threshold = 0.003

    if bias == "neutral":
        if abs(move) <= 0.01:
            return "CONFIRMED", False, "Market remained balanced after absorption interpretation."
        if abs(move) <= 0.02:
            return "PARTIAL", False, "Moderate drift — partial absorption confirmation."
        return "FAILED", True, "Large move despite absorption expectation."

    if bias == "trend":
        if delta is not None:
            expected_up = float(delta) > 0
            if expected_up and move > threshold:
                return "CONFIRMED", False, "Continuation aligned with initiative direction."
            if not expected_up and move < -threshold:
                return "CONFIRMED", False, "Continuation aligned with initiative direction."
        if abs(move) < threshold:
            return "FAILED", True, "Expected continuation but market stalled."
        return "PARTIAL", False, "Continuation partially present."

    if bias == "reversal":
        if abs(move) >= threshold:
            return "CONFIRMED", False, "Reversal or structural shift observed after event."
        return "PARTIAL", False, "Limited follow-through after reversal signal."

    if bias == "bullish":
        if move >= threshold:
            return "CONFIRMED", False, "Market moved upward confirming bullish interpretation."
        if move <= -threshold:
            return "FALSE POSITIVE", True, "Market moved opposite to bullish interpretation."
        return "PARTIAL", False, "Weak upward confirmation."

    if bias == "bearish":
        if move <= -threshold:
            return "CONFIRMED", False, "Market moved downward confirming bearish interpretation."
        if move >= threshold:
            return "FALSE POSITIVE", True, "Market moved opposite to bearish interpretation."
        return "PARTIAL", False, "Weak downward confirmation."

    return "PARTIAL", False, "Insufficient bias classification."


def validate_events(events: pd.DataFrame, horizon: int = FORWARD_HORIZON) -> list[dict[str, Any]]:
    candles = _load_candles()
    results: list[dict[str, Any]] = []

    for _, row in events.iterrows():
        ts = row["timestamp"]
        entry = float(row["close"])
        forward = _forward_window(candles, ts, horizon)
        outcome = _measure_forward(forward, entry)
        bias_spec = _detect_bias(row)
        interpretation = event_to_interpretation(row)

        if bias_spec is None:
            verdict, false_positive, note = "PARTIAL", False, "No explicit cognitive bias to validate."
        else:
            delta = float(row["delta"]) if pd.notna(row.get("delta")) else None
            verdict, false_positive, note = _score_verdict(bias_spec["bias"], outcome, delta)

        direction_word = "upward" if outcome["move_pct"] >= 0 else "downward"
        observed = (
            f"Market moved {direction_word} {abs(outcome['move_pct']):.2f}% "
            f"over next {outcome['forward_candles']} candles."
        )

        results.append(
            {
                "event_index": int(row.get("event_index", 0)),
                "timestamp": str(ts),
                "interpretation": interpretation,
                "bias_label": bias_spec["label"] if bias_spec else "unclassified",
                "bias_source": bias_spec["source_field"] if bias_spec else None,
                "entry_price": entry,
                "outcome": outcome,
                "observed_outcome": observed,
                "verdict": verdict,
                "false_positive": false_positive,
                "validation_note": note,
                "context": {
                    "volume_event": row.get("volume_event"),
                    "climax_state": row.get("climax_state"),
                    "effort_result_state": row.get("effort_result_state"),
                    "synthesis_state": row.get("synthesis_state"),
                    "trigger_event": row.get("trigger_event"),
                },
            }
        )

    return results
