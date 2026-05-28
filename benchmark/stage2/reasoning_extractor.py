"""Extract Stage 2 reasoning events with Stage 1 input context."""

from __future__ import annotations

from typing import Any

import pandas as pd

from benchmark.stage1.event_extractor import _attach_candle_context, _load, _merge_asof, _select_columns


def _stage1_inputs(row: pd.Series) -> list[str]:
    inputs: list[str] = []

    trigger = row.get("trigger_event")
    if pd.notna(trigger) and str(trigger) not in ("NORMAL", "nan"):
        inputs.append(str(trigger).replace("_", " ").lower())

    volume_class = row.get("volume_class")
    if pd.notna(volume_class) and volume_class in ("climax", "stopping"):
        inputs.append(str(volume_class))

    volume_event = row.get("volume_event")
    if pd.notna(volume_event) and str(volume_event) not in ("NEUTRAL_VOLUME", "nan"):
        inputs.append(str(volume_event).replace("_", " ").lower())

    climax = row.get("climax_state")
    if pd.notna(climax) and str(climax) not in ("NO_CLIMAX", "nan"):
        inputs.append(str(climax).replace("_", " ").lower())

    effort = row.get("effort_result_state")
    if pd.notna(effort) and str(effort) not in ("BALANCED_RESPONSE", "nan"):
        inputs.append(str(effort).replace("_", " ").lower())

    if pd.notna(row.get("delta")):
        initiative = "buyer initiative" if float(row["delta"]) > 0 else "seller initiative"
        inputs.append(initiative)

    return inputs


def _pretty(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).replace("_", " ").lower()


def _stage2_narrative(row: pd.Series) -> str:
    synthesis = _pretty(row.get("synthesis_state"))
    regime = _pretty(row.get("auction_regime") or row.get("regime_state"))
    conviction = row.get("conviction_probability")
    distribution = row.get("distribution_probability")
    location = _pretty(row.get("location_bias"))
    persistence = _pretty(row.get("persistence"))

    parts: list[str] = []
    if synthesis:
        parts.append(f"{synthesis} synthesis")
    if regime:
        parts.append(f"regime {regime}")
    if persistence:
        parts.append(f"persistence {persistence}")
    if location:
        parts.append(f"location {location}")
    if pd.notna(distribution) and float(distribution) >= 0.5:
        parts.append("elevated downside continuation probability")
    elif pd.notna(conviction) and float(conviction) >= 0.7:
        parts.append("high conviction auction state")
    elif pd.notna(conviction) and float(conviction) >= 0.4:
        parts.append("moderate conviction state")

    if not parts:
        return "Stage 2 produced no explicit reasoning narrative."
    return ", ".join(parts).capitalize() + "."


def extract_reasoning_events(lookback_days: int = 7) -> pd.DataFrame:
    """Build Stage 2 reasoning timeline enriched with Stage 1 inputs."""

    candles = _load("candle_structure_memory.parquet")
    cognition = _load("runtime_cognition_memory.parquet")
    if len(candles) == 0 or len(cognition) == 0:
        return pd.DataFrame()

    cutoff = candles["timestamp"].max() - pd.Timedelta(days=lookback_days)
    events = cognition[cognition["timestamp"] >= cutoff].copy()
    events = events.dropna(subset=["synthesis_state"], how="all")
    if len(events) == 0:
        return pd.DataFrame()

    volume_class = _load("volume_classification_memory.parquet")
    response = _load("volume_response_state.parquet")
    probabilistic = _load("probabilistic_auction_memory.parquet")
    reinforcement = _load("auction_reinforcement_memory.parquet")
    transitions = _load("state_transition_memory.parquet")

    events = _attach_candle_context(events, candles)
    events = _merge_asof(events, _select_columns(volume_class, ["timestamp", "volume_class", "delta"]), "_s1vc")
    events = _merge_asof(
        events,
        _select_columns(
            response,
            [
                "timestamp",
                "volume_event",
                "climax_state",
                "effort_result_state",
                "localized_behavior",
                "participation_state",
            ],
        ),
        "_s1vr",
    )
    events = _merge_asof(
        events,
        _select_columns(
            probabilistic,
            [
                "timestamp",
                "auction_regime",
                "regime_state",
                "conviction_probability",
                "disciplined_conviction",
                "regime_confidence",
                "distribution_probability",
                "absorption_probability",
                "contradiction_flags",
                "contradiction_clusters",
                "regime_transition_probability",
            ],
        ),
        "_pa",
    )
    events = _merge_asof(
        events,
        _select_columns(reinforcement, ["timestamp", "belief_state", "belief_strength", "auction_state"]),
        "_ar",
    )

    if len(transitions) > 0:
        st = transitions[transitions["timestamp"] >= cutoff].copy()
        st = st[st["transition_state"].notna() & (st["transition_state"] != "STABLE_STATE")]
        if "previous_state" in st.columns and "current_state" in st.columns:
            st = st[st["previous_state"] != st["current_state"]]
        if len(st) > 0:
            events = _merge_asof(
                events,
                _select_columns(st, ["timestamp", "transition_state", "previous_state", "current_state"]),
                "_st",
            )

    events = events.sort_values("timestamp").reset_index(drop=True)
    events["event_index"] = range(1, len(events) + 1)
    events["stage1_inputs"] = events.apply(_stage1_inputs, axis=1)
    events["stage2_interpretation"] = events.apply(_stage2_narrative, axis=1)
    return events


def reasoning_context(row: pd.Series) -> dict[str, Any]:
    return {
        "timestamp": str(row["timestamp"]),
        "stage1_inputs": row.get("stage1_inputs", []),
        "stage2_interpretation": row.get("stage2_interpretation"),
        "synthesis_state": row.get("synthesis_state"),
        "trigger_event": row.get("trigger_event"),
        "persistence": row.get("persistence"),
        "persistence_score": float(row["persistence_score"]) if pd.notna(row.get("persistence_score")) else None,
        "structural_rank": row.get("structural_rank"),
        "alignment_score": float(row["alignment_score"]) if pd.notna(row.get("alignment_score")) else None,
        "location_bias": row.get("location_bias"),
        "auction_regime": row.get("auction_regime") or row.get("regime_state"),
        "conviction_probability": float(row["conviction_probability"])
        if pd.notna(row.get("conviction_probability"))
        else None,
        "regime_confidence": float(row["regime_confidence"]) if pd.notna(row.get("regime_confidence")) else None,
        "distribution_probability": float(row["distribution_probability"])
        if pd.notna(row.get("distribution_probability"))
        else None,
        "belief_state": row.get("belief_state"),
        "contradiction_flags": row.get("contradiction_flags"),
    }
