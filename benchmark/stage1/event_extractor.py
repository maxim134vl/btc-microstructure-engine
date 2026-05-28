"""Extract Stage 1 cognition events for benchmark validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from parquet_utils import safe_read_parquet


def _load(name: str) -> pd.DataFrame:
    frame = safe_read_parquet(name)
    if len(frame) == 0:
        return frame
    if "timestamp" in frame.columns:
        frame = frame.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.dropna(subset=["timestamp"])
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def _select_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    present = [column for column in columns if column in frame.columns]
    if "timestamp" not in present:
        return pd.DataFrame()
    return frame[present].copy()


def _merge_asof(base: pd.DataFrame, other: pd.DataFrame, suffix: str) -> pd.DataFrame:
    if len(base) == 0 or len(other) == 0 or "timestamp" not in other.columns:
        return base
    left = base.sort_values("timestamp").dropna(subset=["timestamp"])
    right = other.sort_values("timestamp").dropna(subset=["timestamp"])
    if len(right) == 0:
        return left
    overlap = set(left.columns) & set(right.columns) - {"timestamp"}
    if overlap:
        right = right.rename(columns={column: f"{column}{suffix}" for column in overlap})
    return pd.merge_asof(left, right, on="timestamp", direction="backward")


def _attach_candle_context(events: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    if len(events) == 0:
        return events
    base = events.sort_values("timestamp").dropna(subset=["timestamp"])
    ctx = candles.sort_values("timestamp").dropna(subset=["timestamp"])
    merged = pd.merge_asof(base, ctx, on="timestamp", direction="backward", suffixes=("", "_candle"))
    for column in ("open", "high", "low", "close", "volume", "delta"):
        candle_col = f"{column}_candle"
        if candle_col in merged.columns:
            merged[column] = merged[column].fillna(merged[candle_col])
            merged = merged.drop(columns=[candle_col])
    return merged


def _collect_native_events(
    *,
    candles: pd.DataFrame,
    volume_class: pd.DataFrame,
    response: pd.DataFrame,
    cognition: pd.DataFrame,
    probabilistic: pd.DataFrame,
    transitions: pd.DataFrame,
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    """Collect events only at timestamps where Stage 1 emitted a signal."""

    frames: list[pd.DataFrame] = []

    if len(volume_class) > 0 and "volume_class" in volume_class.columns:
        vc = volume_class[volume_class["timestamp"] >= cutoff].copy()
        vc = vc[vc["volume_class"].isin(["climax", "stopping"])]
        if len(vc) > 0:
            frames.append(_select_columns(vc, ["timestamp", "volume_class"]))

    if len(response) > 0:
        vr = response[response["timestamp"] >= cutoff].copy()
        climax = vr.get("climax_state", pd.Series(dtype=object))
        effort = vr.get("effort_result_state", pd.Series(dtype=object))
        vr_mask = (
            vr.get("volume_event", pd.Series(dtype=object)).isin(
                ["STOPPING_VOLUME", "ABSORPTION_VOLUME", "EXHAUSTION_VOLUME", "CONTINUATION_VOLUME"]
            )
            | (climax.notna() & (climax != "NO_CLIMAX"))
            | (effort.notna() & (effort != "BALANCED_RESPONSE"))
        )
        vr = vr[vr_mask.fillna(False)]
        if len(vr) > 0:
            frames.append(
                _select_columns(
                    vr,
                    [
                        "timestamp",
                        "volume_event",
                        "climax_state",
                        "participation_state",
                        "effort_result_state",
                        "localized_behavior",
                        "unfinished_auction",
                    ],
                )
            )

    if len(cognition) > 0:
        rc = cognition[cognition["timestamp"] >= cutoff].copy()
        rc = rc.dropna(subset=["synthesis_state"], how="all")
        if len(rc) > 0:
            frames.append(
                _select_columns(
                    rc,
                    [
                        "timestamp",
                        "synthesis_state",
                        "trigger_event",
                        "persistence_score",
                        "structural_rank",
                        "alignment_score",
                    ],
                )
            )

    if len(transitions) > 0 and "transition_state" in transitions.columns:
        st = transitions[transitions["timestamp"] >= cutoff].copy()
        st = st[st["transition_state"].notna()]
        st = st[st["transition_state"] != "STABLE_STATE"]
        if "previous_state" in st.columns and "current_state" in st.columns:
            st = st[st["previous_state"] != st["current_state"]]
        if len(st) > 0:
            frames.append(
                _select_columns(st, ["timestamp", "transition_state", "previous_state", "current_state"])
            )

    if not frames:
        return pd.DataFrame()

    events = frames[0]
    for frame in frames[1:]:
        events = pd.merge(events, frame, on="timestamp", how="outer", suffixes=("", "_dup"))
        for column in frame.columns:
            if column == "timestamp":
                continue
            dup = f"{column}_dup"
            if dup in events.columns:
                events[column] = events[column].fillna(events[dup])
                events = events.drop(columns=[dup])

    events = events.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    events = _attach_candle_context(events, candles)

    if len(probabilistic) > 0:
        pa = probabilistic[probabilistic["timestamp"] >= cutoff].copy()
        events = _merge_asof(
            events,
            _select_columns(pa, ["timestamp", "auction_regime", "conviction_probability"]),
            "_pa",
        )

    return events


def extract_cognition_events(lookback_days: int = 7) -> pd.DataFrame:
    """Build unified event timeline from Stage 1 memory layers."""

    candles = _load("candle_structure_memory.parquet")
    if len(candles) == 0:
        return pd.DataFrame()

    cutoff = candles["timestamp"].max() - pd.Timedelta(days=lookback_days)
    candles = candles[candles["timestamp"] >= cutoff].copy()

    volume_class = _load("volume_classification_memory.parquet")
    response = _load("volume_response_state.parquet")
    cognition = _load("runtime_cognition_memory.parquet")
    probabilistic = _load("probabilistic_auction_memory.parquet")
    transitions = _load("state_transition_memory.parquet")

    events = _collect_native_events(
        candles=candles,
        volume_class=volume_class,
        response=response,
        cognition=cognition,
        probabilistic=probabilistic,
        transitions=transitions,
        cutoff=cutoff,
    )
    if len(events) == 0:
        return pd.DataFrame()

    events = events.sort_values("timestamp").reset_index(drop=True)
    events["event_index"] = range(1, len(events) + 1)
    return events


def event_to_interpretation(row: pd.Series) -> str:
    """Human-readable Stage 1 belief string."""

    parts: list[str] = []

    ve = row.get("volume_event")
    vc = row.get("volume_class")
    cs = row.get("climax_state")
    er = row.get("effort_result_state")
    lb = row.get("localized_behavior")
    ss = row.get("synthesis_state")
    te = row.get("trigger_event")
    ar = row.get("auction_regime")
    delta = row.get("delta")

    if pd.notna(te) and str(te) not in ("NORMAL", "nan"):
        parts.append(f"Trigger event: {te}.")
    elif pd.notna(vc) and vc in ("climax", "stopping"):
        parts.append(f"Volume class: {vc}.")
    if pd.notna(ve) and str(ve) not in ("NEUTRAL_VOLUME", "nan"):
        parts.append(f"Volume event: {ve}.")
    if pd.notna(cs) and str(cs) not in ("NO_CLIMAX", "nan"):
        parts.append(f"Climax state: {cs}.")
    if pd.notna(er) and str(er) not in ("BALANCED_RESPONSE", "nan"):
        parts.append(f"Effort/result: {er}.")
    if pd.notna(lb) and str(lb) not in ("nan", ""):
        parts.append(f"Localized behavior: {lb}.")
    if pd.notna(ss):
        parts.append(f"Synthesis: {ss}.")
    if pd.notna(ar):
        parts.append(f"Regime: {ar}.")
    if pd.notna(delta):
        initiative = "buyer" if float(delta) > 0 else "seller"
        parts.append(f"{initiative.title()} initiative on delta.")

    if not parts:
        return "Stage 1 observed neutral market participation."
    return " ".join(parts)


def row_context(row: pd.Series) -> dict[str, Any]:
    return {
        "timestamp": str(row["timestamp"]),
        "price": float(row["close"]),
        "delta": float(row["delta"]) if pd.notna(row.get("delta")) else None,
        "volume_class": row.get("volume_class"),
        "volume_event": row.get("volume_event"),
        "climax_state": row.get("climax_state"),
        "effort_result_state": row.get("effort_result_state"),
        "synthesis_state": row.get("synthesis_state"),
        "trigger_event": row.get("trigger_event"),
        "auction_regime": row.get("auction_regime"),
        "transition_state": row.get("transition_state"),
    }
