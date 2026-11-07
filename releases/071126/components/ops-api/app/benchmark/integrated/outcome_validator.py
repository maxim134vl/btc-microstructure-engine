"""Validate market outcome for integrated cognition chains."""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchmark.stage1.forward_validator import (
    _detect_bias,
    _forward_window,
    _load_candles,
    _measure_forward,
    _score_verdict,
)

FORWARD_HORIZON = 11


def validate_outcome(row: pd.Series, *, horizon: int = FORWARD_HORIZON) -> dict[str, Any]:
    candles = _load_candles()
    ts = pd.to_datetime(row["timestamp"])
    entry = float(row["close"]) if pd.notna(row.get("close")) and float(row["close"]) > 0 else 0.0
    forward = _forward_window(candles, ts, horizon)
    outcome = _measure_forward(forward, entry)

    bias_spec = _detect_bias(row)
    if bias_spec is None:
        market_verdict, false_positive, note = "PARTIAL", False, "No explicit market bias to validate."
    else:
        delta = float(row["delta"]) if pd.notna(row.get("delta")) else None
        market_verdict, false_positive, note = _score_verdict(bias_spec["bias"], outcome, delta)

    direction = outcome.get("direction", "flat")
    observed = (
        f"Market moved {direction} {abs(outcome['move_pct']):.2f}% "
        f"over next {outcome['forward_candles']} candles."
    )
    if market_verdict == "CONFIRMED" and direction == "down":
        observed = (
            f"Market transitioned lower over next {outcome['forward_candles']} candles "
            f"({abs(outcome['move_pct']):.2f}%)."
        )
    elif market_verdict == "CONFIRMED" and direction == "up":
        observed = (
            f"Market transitioned higher over next {outcome['forward_candles']} candles "
            f"({abs(outcome['move_pct']):.2f}%)."
        )

    return {
        "outcome": outcome,
        "observed_outcome": observed,
        "market_verdict": market_verdict,
        "market_note": note,
        "false_positive": false_positive,
        "combined_narrative_confirmed": market_verdict == "CONFIRMED",
    }
