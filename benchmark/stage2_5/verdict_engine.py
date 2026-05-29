"""Dispatch Stage 2.5 validators and fuse multi-horizon verdicts."""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchmark.stage2_5.context_validator import VALIDATION_HORIZONS, build_multi_horizon_context, find_event_index, load_candles
from benchmark.stage2_5.continuation_validator import validate_horizon as validate_continuation
from benchmark.stage2_5.event_extractor import event_context, event_narration
from benchmark.stage2_5.initiative_validator import validate_horizon as validate_initiative
from benchmark.stage2_5.rotational_validator import validate_horizon as validate_rotational

STATE_VALIDATORS = {
    "IC_CONTINUATION_WEAKENING": validate_continuation,
    "IC_INITIATIVE_DETERIORATION": validate_initiative,
    "IC_ROTATIONAL_PRESSURE": validate_rotational,
}

VERDICT_RANK = {
    "CONFIRMED": 4,
    "EARLY_WARNING": 3,
    "PARTIAL": 2,
    "FAILED": 1,
    "FALSE_POSITIVE": 0,
}


def _pick_validator(state: str):
    return STATE_VALIDATORS.get(state)


def _fuse_verdicts(state: str, horizon_results: dict[int, dict[str, Any]]) -> dict[str, Any]:
    if not horizon_results:
        return {
            "verdict": "PARTIAL",
            "false_positive": False,
            "early_warning": False,
            "confirmation_horizon": None,
            "note": "No horizon results.",
        }

    by_horizon = {h: horizon_results[h]["verdict"] for h in sorted(horizon_results)}
    ranks = {h: VERDICT_RANK.get(v, 0) for h, v in by_horizon.items()}

    confirmation_horizon = next((h for h, v in by_horizon.items() if v == "CONFIRMED"), None)
    false_positive = any(r["false_positive"] for r in horizon_results.values())

    if false_positive and all(by_horizon[h] in ("FALSE_POSITIVE", "FAILED") for h in by_horizon):
        best_h = max(ranks, key=ranks.get)
        return {
            "verdict": "FALSE_POSITIVE",
            "false_positive": True,
            "early_warning": False,
            "confirmation_horizon": None,
            "note": horizon_results[best_h]["note"],
        }

    if confirmation_horizon is not None:
        if state == "IC_CONTINUATION_WEAKENING":
            later = [h for h in by_horizon if h > confirmation_horizon]
            if later and all(by_horizon[h] in ("PARTIAL", "FAILED") for h in later):
                return {
                    "verdict": "EARLY_WARNING",
                    "false_positive": False,
                    "early_warning": True,
                    "confirmation_horizon": confirmation_horizon,
                    "note": (
                        f"Weakening confirmed by +{confirmation_horizon} bars before longer-horizon ambiguity. "
                        f"{horizon_results[confirmation_horizon]['note']}"
                    ),
                }
        return {
            "verdict": "CONFIRMED",
            "false_positive": False,
            "early_warning": False,
            "confirmation_horizon": confirmation_horizon,
            "note": horizon_results[confirmation_horizon]["note"],
        }

    if state == "IC_CONTINUATION_WEAKENING":
        early_h = next((h for h, v in by_horizon.items() if v == "PARTIAL"), None)
        later_confirmed = any(ranks[h] >= VERDICT_RANK["PARTIAL"] for h in by_horizon if early_h and h > early_h)
        if early_h == 4 and later_confirmed and max(ranks.values()) == VERDICT_RANK["PARTIAL"]:
            return {
                "verdict": "EARLY_WARNING",
                "false_positive": False,
                "early_warning": True,
                "confirmation_horizon": 4,
                "note": horizon_results[early_h]["note"],
            }

    best_h = max(ranks, key=ranks.get)
    best_verdict = by_horizon[best_h]
    if best_verdict == "PARTIAL" and len(set(by_horizon.values())) == 1:
        best_verdict = "PARTIAL"
    elif best_verdict in ("FAILED", "PARTIAL") and ranks[best_h] == max(ranks.values()):
        best_verdict = by_horizon[best_h]

    return {
        "verdict": best_verdict,
        "false_positive": false_positive,
        "early_warning": False,
        "confirmation_horizon": best_h if best_verdict == "PARTIAL" else None,
        "note": horizon_results[best_h]["note"],
    }


def validate_intermediate_events(events: pd.DataFrame) -> list[dict[str, Any]]:
    candles = load_candles()
    results: list[dict[str, Any]] = []

    for _, row in events.iterrows():
        ts = pd.Timestamp(row["timestamp"])
        state = str(row["intermediate_state"])
        validator = _pick_validator(state)
        event_idx = find_event_index(candles, ts)

        if validator is None:
            results.append(
                {
                    "event_index": int(row.get("event_index", 0)),
                    "timestamp": str(ts),
                    "intermediate_state": state,
                    "interpretation": event_narration(row),
                    "verdict": "PARTIAL",
                    "false_positive": False,
                    "early_warning": False,
                    "validation_note": "Unsupported intermediate state.",
                    "context": event_context(row),
                    "horizons": {},
                }
            )
            continue

        if event_idx is None:
            results.append(
                {
                    "event_index": int(row.get("event_index", 0)),
                    "timestamp": str(ts),
                    "intermediate_state": state,
                    "interpretation": event_narration(row),
                    "verdict": "PARTIAL",
                    "false_positive": False,
                    "early_warning": False,
                    "validation_note": "Event timestamp not found in candle memory.",
                    "context": event_context(row),
                    "horizons": {},
                }
            )
            continue

        contexts = build_multi_horizon_context(candles, event_idx)
        horizon_results: dict[int, dict[str, Any]] = {}
        for horizon, context in contexts.items():
            scored = validator(context)
            horizon_results[horizon] = {**scored, "metrics": context}

        fused = _fuse_verdicts(state, horizon_results)
        observed = _observed_outcome(contexts, fused.get("confirmation_horizon"))

        results.append(
            {
                "event_index": int(row.get("event_index", 0)),
                "timestamp": str(ts),
                "intermediate_state": state,
                "interpretation": event_narration(row),
                "observed_outcome": observed,
                "verdict": fused["verdict"],
                "false_positive": fused["false_positive"],
                "early_warning": fused.get("early_warning", False),
                "confirmation_horizon": fused.get("confirmation_horizon"),
                "validation_note": fused["note"],
                "context": event_context(row),
                "horizons": {
                    str(h): {
                        "verdict": horizon_results[h]["verdict"],
                        "note": horizon_results[h]["note"],
                        "delta": horizon_results[h]["metrics"]["delta"],
                        "forward": horizon_results[h]["metrics"]["forward"],
                    }
                    for h in VALIDATION_HORIZONS
                },
            }
        )

    return results


def _observed_outcome(contexts: dict[int, dict[str, Any]], confirmation_horizon: int | None) -> str:
    horizon = confirmation_horizon or 8
    context = contexts.get(horizon) or contexts.get(8) or next(iter(contexts.values()))
    forward = context["forward"]
    delta = context["delta"]
    return (
        f"Over +{int(context['horizon'])} bars: continuation_quality {forward['continuation_quality']:.2f} "
        f"(Δ{delta['continuation_quality']:+.2f}), initiative_dominance {forward['initiative_dominance']:.2f} "
        f"(Δ{delta['initiative_dominance']:+.2f}), sign_flips {forward['sign_flips']:.2f}."
    )
