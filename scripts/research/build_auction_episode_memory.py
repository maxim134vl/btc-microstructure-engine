#!/usr/bin/env python3
"""Standalone shadow builder: auction episode memory.

Sits between bar/volume observations and cognitive / final context.
Does NOT write LONG_CONTEXT / SHORT_CONTEXT and does NOT touch arbitration.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BUILDER_VERSION = "auction_episode_memory_v1"
OUTPUT_PATH = ROOT / "data" / "cognition" / "auction_episode_memory.parquet"
STALE_HOURS = 6.0

REQUIRED_OUTPUT_COLUMNS = [
    "timestamp",
    "close",
    "bar_event",
    "volume_event",
    "climax_state",
    "volume_effort",
    "effort_side",
    "auction_location",
    "price_result",
    "effort_result",
    "follow_through",
    "convergence_state",
    "localized_behavior",
    "auction_regime",
    "distribution_probability",
    "absorption_probability",
    "auction_episode",
    "episode_status",
    "episode_reason",
    "source_freshness",
    "builder_version",
    "shadow_only",
]

INPUT_SPECS: dict[str, tuple[Path, ...]] = {
    "live": (ROOT / "data" / "live" / "live_market_feed.parquet",),
    "candles": (ROOT / "data" / "cognition" / "candle_structure_memory.parquet",),
    "volume_response": (ROOT / "data" / "cognition" / "volume_response_state.parquet",),
    "convergence": (ROOT / "data" / "reinforcement" / "auction_convergence_memory.parquet",),
    "probabilistic": (ROOT / "data" / "probabilistic" / "probabilistic_auction_memory.parquet",),
    "cognition": (ROOT / "data" / "cognition" / "runtime_cognition_memory.parquet",),
    "cognition_composite": (ROOT / "data" / "cognition" / "runtime_cognition_composite.parquet",),
}


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


def _read_parquet_optional(paths: tuple[Path, ...]) -> pd.DataFrame:
    for path in paths:
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if frame is None or len(frame) == 0:
            continue
        return frame.copy()
    return pd.DataFrame()


def _normalize_timestamp_column(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or len(frame) == 0:
        return pd.DataFrame()
    work = frame.copy()
    ts_col = None
    for candidate in ("timestamp", "evaluation_timestamp", "bar_timestamp"):
        if candidate in work.columns:
            ts_col = candidate
            break
    if ts_col is None:
        return pd.DataFrame()
    work["timestamp"] = pd.to_datetime(work[ts_col], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp")
    if ts_col != "timestamp" and ts_col in work.columns and ts_col != "timestamp":
        # keep original evaluation_timestamp if present; ensure timestamp exists
        pass
    return work.reset_index(drop=True)


def _asof_row(frame: pd.DataFrame, ts: pd.Timestamp) -> pd.Series | None:
    if frame is None or len(frame) == 0 or "timestamp" not in frame.columns:
        return None
    prior = frame[frame["timestamp"] <= ts]
    if len(prior) == 0:
        return None
    return prior.iloc[-1]


def _asof_lookup(frame: pd.DataFrame, ts: pd.Timestamp, column: str, default: Any = None) -> Any:
    row = _asof_row(frame, ts)
    if row is None or column not in row.index:
        return default
    value = row.get(column, default)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return value


def _asof_lookup_near(
    frame: pd.DataFrame,
    ts: pd.Timestamp,
    column: str,
    *,
    max_age: pd.Timedelta,
    default: Any = None,
) -> Any:
    """Asof value only if source row is within max_age of the bar (avoids sticky cognition)."""
    row = _asof_row(frame, ts)
    if row is None or column not in row.index:
        return default
    src_ts = row.get("timestamp")
    if src_ts is None or pd.isna(src_ts):
        return default
    if (ts - src_ts) > max_age:
        return default
    value = row.get(column, default)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return value


def _source_freshness_label(frame: pd.DataFrame, reference_ts: pd.Timestamp | None) -> str:
    if frame is None or len(frame) == 0 or "timestamp" not in getattr(frame, "columns", []):
        return "missing"
    if reference_ts is None or pd.isna(reference_ts):
        return "fresh" if len(frame) else "missing"
    latest = frame["timestamp"].iloc[-1]
    if pd.isna(latest):
        return "missing"
    age_hours = (reference_ts - latest).total_seconds() / 3600.0
    if age_hours > STALE_HOURS:
        return "stale"
    return "fresh"


def classify_bar_event(
    *,
    trigger_event: str = "UNKNOWN",
    tier1_trigger_event: str = "UNKNOWN",
    volume_event: str = "UNKNOWN",
    climax_state: str = "UNKNOWN",
    effort_result_state: str = "UNKNOWN",
) -> str:
    """Single-bar observation event — not a cognitive market state."""
    for candidate in (tier1_trigger_event, trigger_event):
        token = _clean_text(candidate).upper()
        if token in {"BUYING_CLIMAX", "SELLING_CLIMAX", "STOPPING_VOLUME"}:
            return token
    vol = _clean_text(volume_event).upper()
    if vol == "STOPPING_VOLUME":
        return "STOPPING_VOLUME"
    if vol in {"ABSORPTION_VOLUME", "ABSORPTION_RESPONSE"}:
        return "ABSORPTION_RESPONSE"
    climax = _clean_text(climax_state).upper()
    if climax == "CLIMAX_EXHAUSTION":
        return "CLIMAX_EXHAUSTION"
    if climax in {"CLIMAX_ABSORPTION"}:
        return "ABSORPTION_RESPONSE"
    effort = _clean_text(effort_result_state).upper()
    if effort == "ABSORPTION_RESPONSE":
        return "ABSORPTION_RESPONSE"
    return "UNKNOWN"


def classify_volume_effort(
    *,
    volume_class: str = "UNKNOWN",
    relative_volume: float | None = None,
    climax_state: str = "UNKNOWN",
    volume_event: str = "UNKNOWN",
) -> str:
    """Map existing volume fields only — no invented formulas beyond simple bins."""
    climax = _clean_text(climax_state).upper()
    vclass = _clean_text(volume_class).lower()
    vevent = _clean_text(volume_event).upper()
    if climax.startswith("CLIMAX") or vclass == "climax" or vevent in {"STOPPING_VOLUME", "EXHAUSTION_VOLUME"}:
        if climax != "NO_CLIMAX" and climax != "UNKNOWN":
            return "EXTREME" if climax.startswith("CLIMAX") or vclass == "climax" else "HIGH"
        if vclass == "climax":
            return "EXTREME"
        if vevent in {"STOPPING_VOLUME", "EXHAUSTION_VOLUME"}:
            return "HIGH"
    if vclass in {"high_average", "high", "elevated"}:
        return "HIGH"
    if vclass in {"low_small", "low", "small"}:
        return "LOW"
    if vclass in {"stopping"}:
        return "HIGH"
    if relative_volume is not None:
        if relative_volume >= 3.0:
            return "EXTREME"
        if relative_volume >= 1.5:
            return "HIGH"
        if relative_volume >= 0.7:
            return "NORMAL"
        if relative_volume > 0:
            return "LOW"
    if vclass not in {"unknown", ""} and vclass != "UNKNOWN".lower():
        return "NORMAL"
    return "UNKNOWN"


def classify_effort_side(
    *,
    bar_event: str,
    auction_location: str,
    candle_type: str = "UNKNOWN",
) -> str:
    event = _clean_text(bar_event).upper()
    location = _clean_text(auction_location).upper()
    if event == "BUYING_CLIMAX":
        return "BUYER"
    if event in {"SELLING_CLIMAX", "STOPPING_VOLUME"}:
        return "SELLER"
    if event == "ABSORPTION_RESPONSE" and location == "UPPER_AREA":
        return "BUYER"
    if event == "ABSORPTION_RESPONSE" and location == "LOWER_AREA":
        return "SELLER"
    if event == "CLIMAX_EXHAUSTION" and location == "UPPER_AREA":
        return "BUYER"
    if event == "CLIMAX_EXHAUSTION" and location == "LOWER_AREA":
        return "SELLER"
    if location in {"UPPER_AREA", "BREAKOUT_AREA"} and event not in {"UNKNOWN"}:
        return "BUYER"
    if location in {"LOWER_AREA", "BREAKDOWN_AREA"} and event not in {"UNKNOWN"}:
        return "SELLER"
    ctype = _clean_text(candle_type).lower()
    if ctype in {"bullish", "bearish"} and event not in {"UNKNOWN"}:
        return "MIXED"
    return "UNKNOWN"


def classify_auction_location(
    *,
    tier1_location_bias: str = "UNKNOWN",
    location_bias: str = "UNKNOWN",
    close_position: float | None = None,
) -> str:
    for candidate in (tier1_location_bias, location_bias):
        token = _clean_text(candidate).upper()
        if token in {"UPPER_DISTRIBUTION", "UPPER_AREA", "UPPER"}:
            return "UPPER_AREA"
        if token in {"LOWER_ABSORPTION", "LOWER_CAPITULATION", "LOWER_AREA", "LOWER"}:
            return "LOWER_AREA"
        if token in {"BREAKOUT", "BREAKOUT_AREA"}:
            return "BREAKOUT_AREA"
        if token in {"BREAKDOWN", "BREAKDOWN_AREA"}:
            return "BREAKDOWN_AREA"
        if token in {"MIDDLE", "MIDDLE_AREA", "BALANCE"}:
            return "MIDDLE_AREA"
    if close_position is not None:
        if close_position >= 0.75:
            return "UPPER_AREA"
        if close_position <= 0.25:
            return "LOWER_AREA"
        if 0.35 <= close_position <= 0.65:
            return "MIDDLE_AREA"
    return "UNKNOWN"


def classify_price_result(
    *,
    close: float | None,
    prev_close: float | None,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    bar_event: str = "UNKNOWN",
) -> str:
    """Simple diagnostic price result vs previous close — not structural truth."""
    if close is None or prev_close is None or prev_close == 0:
        return "UNKNOWN"
    ret = (close - prev_close) / abs(prev_close)
    event = _clean_text(bar_event).upper()
    near_high = high is not None and high > 0 and (high - close) / high <= 0.0015
    near_low = low is not None and low > 0 and (close - low) / low <= 0.0015

    if abs(ret) < 0.0008:
        if event in {"BUYING_CLIMAX", "SELLING_CLIMAX", "STOPPING_VOLUME", "CLIMAX_EXHAUSTION"}:
            return "NO_PROGRESS"
        return "RANGE"

    if ret > 0:
        if event in {"BUYING_CLIMAX", "CLIMAX_EXHAUSTION"} and open_ is not None and close < open_ and not near_high:
            return "REJECTED_HIGHER"
        if near_high or ret >= 0.0015:
            return "ACCEPTED_HIGHER"
        return "ACCEPTED_HIGHER"

    # ret < 0
    if event in {"SELLING_CLIMAX", "STOPPING_VOLUME"} and open_ is not None and close > open_ and not near_low:
        return "REJECTED_LOWER"
    if event == "BUYING_CLIMAX":
        return "REJECTED_HIGHER"
    if near_low or ret <= -0.0015:
        return "ACCEPTED_LOWER"
    return "ACCEPTED_LOWER"


def classify_follow_through(
    *,
    closes: list[float],
    index: int,
    effort_side: str,
    bar_event: str,
    horizon: int = 4,
) -> str:
    """Diagnostic look-ahead over available history only."""
    if index < 0 or index >= len(closes) - 1:
        return "UNKNOWN"
    base = closes[index]
    if base is None or base == 0:
        return "UNKNOWN"
    future = closes[index + 1 : index + 1 + horizon]
    future = [c for c in future if c is not None]
    if not future:
        return "UNKNOWN"
    end = future[-1]
    move = (end - base) / abs(base)
    max_up = (max(future) - base) / abs(base)
    max_down = (min(future) - base) / abs(base)
    side = _clean_text(effort_side).upper()
    event = _clean_text(bar_event).upper()

    want_higher = side == "BUYER" or event in {"BUYING_CLIMAX"}
    want_lower = side == "SELLER" or event in {"SELLING_CLIMAX", "STOPPING_VOLUME"}

    if want_higher:
        if max_up >= 0.002 and move >= 0.001:
            return "YES"
        if max_up >= 0.001 and move >= 0:
            return "WEAK"
        if max_down <= -0.0015 or move < -0.001:
            return "FAILED"
        return "NO"
    if want_lower:
        if max_down <= -0.002 and move <= -0.001:
            return "YES"
        if max_down <= -0.001 and move <= 0:
            return "WEAK"
        if max_up >= 0.0015 or move > 0.001:
            return "FAILED"
        return "NO"
    if abs(move) < 0.0008:
        return "NO"
    return "UNKNOWN"


def classify_effort_result(
    *,
    volume_effort: str,
    price_result: str,
    follow_through: str,
    effort_result_state: str = "UNKNOWN",
) -> str:
    existing = _clean_text(effort_result_state).upper()
    if existing == "ABSORPTION_RESPONSE":
        return "ABSORBED"
    if existing == "EFFICIENT_CONTINUATION":
        return "CONTINUED"
    if existing == "EXHAUSTION_RESPONSE":
        return "NO_RESULT"

    effort = _clean_text(volume_effort).upper()
    price = _clean_text(price_result).upper()
    ft = _clean_text(follow_through).upper()
    high_effort = effort in {"HIGH", "EXTREME"}

    if price in {"REJECTED_HIGHER", "REJECTED_LOWER"}:
        return "REJECTED"
    if price in {"ACCEPTED_HIGHER", "ACCEPTED_LOWER"} and ft in {"YES", "WEAK"}:
        return "ACCEPTED" if ft == "YES" else "CONTINUED"
    if price in {"ACCEPTED_HIGHER", "ACCEPTED_LOWER"} and high_effort:
        return "ACCEPTED"
    if high_effort and price in {"NO_PROGRESS", "RANGE"}:
        return "ABSORBED"
    if high_effort and ft in {"FAILED", "NO"}:
        return "NO_RESULT"
    if existing == "BALANCED_RESPONSE":
        return "NO_RESULT"
    return "UNKNOWN"


def classify_auction_episode(
    *,
    bar_event: str,
    auction_location: str,
    follow_through: str,
    price_result: str,
    volume_effort: str,
    effort_result: str,
) -> str:
    event = _clean_text(bar_event).upper()
    location = _clean_text(auction_location).upper()
    ft = _clean_text(follow_through).upper()
    price = _clean_text(price_result).upper()
    effort = _clean_text(volume_effort).upper()
    eresult = _clean_text(effort_result).upper()

    failed_higher = ft in {"FAILED", "NO"} or price in {"REJECTED_HIGHER", "NO_PROGRESS"}
    failed_lower = ft in {"FAILED", "NO"} or price in {"REJECTED_LOWER", "NO_PROGRESS"}

    if event == "BUYING_CLIMAX" and location == "UPPER_AREA" and failed_higher:
        return "UPPER_DISTRIBUTION"
    if event in {"STOPPING_VOLUME", "SELLING_CLIMAX"} and location == "LOWER_AREA" and failed_lower:
        return "LOWER_ABSORPTION"
    if effort in {"HIGH", "EXTREME"} and (price == "REJECTED_HIGHER" or (eresult == "REJECTED" and location in {"UPPER_AREA", "BREAKOUT_AREA"})):
        return "FAILED_BREAKOUT"
    if effort in {"HIGH", "EXTREME"} and (price == "REJECTED_LOWER" or (eresult == "REJECTED" and location in {"LOWER_AREA", "BREAKDOWN_AREA"})):
        return "FAILED_BREAKDOWN"
    if price == "ACCEPTED_HIGHER" and eresult in {"ACCEPTED", "CONTINUED"}:
        return "ACCEPTANCE_HIGHER"
    if price == "ACCEPTED_LOWER" and eresult in {"ACCEPTED", "CONTINUED"}:
        return "ACCEPTANCE_LOWER"
    if eresult == "CONTINUED" and ft == "YES":
        return "CONTINUATION"
    if price == "RANGE" or eresult in {"ABSORBED", "NO_RESULT"}:
        return "BALANCE"
    if event == "UNKNOWN" and location == "UNKNOWN":
        return "UNKNOWN"
    return "UNKNOWN"


def classify_episode_status(
    *,
    auction_episode: str,
    follow_through: str,
    effort_result: str,
) -> str:
    episode = _clean_text(auction_episode).upper()
    ft = _clean_text(follow_through).upper()
    eresult = _clean_text(effort_result).upper()
    if episode == "UNKNOWN":
        return "UNKNOWN"
    # Without look-ahead confirmation, stay cautious.
    if ft == "UNKNOWN":
        return "DEVELOPING"
    if episode in {"UPPER_DISTRIBUTION", "LOWER_ABSORPTION", "FAILED_BREAKOUT", "FAILED_BREAKDOWN"}:
        if ft in {"FAILED", "NO"} or eresult in {"REJECTED", "ABSORBED", "NO_RESULT"}:
            return "CONFIRMED"
        if ft == "YES":
            return "INVALIDATED"
        return "DEVELOPING"
    if episode in {"ACCEPTANCE_HIGHER", "ACCEPTANCE_LOWER", "CONTINUATION"}:
        if ft == "YES":
            return "CONFIRMED"
        if ft in {"FAILED"}:
            return "INVALIDATED"
        return "DEVELOPING"
    if episode == "BALANCE":
        return "DEVELOPING"
    return "STARTED"


def build_episode_reason(
    *,
    bar_event: str,
    auction_location: str,
    follow_through: str,
    auction_episode: str,
    price_result: str,
) -> str:
    event = _clean_text(bar_event)
    location = _clean_text(auction_location)
    ft = _clean_text(follow_through)
    episode = _clean_text(auction_episode)
    price = _clean_text(price_result)
    if episode == "UPPER_DISTRIBUTION":
        return f"{event} at {location} with failed higher continuation"
    if episode == "LOWER_ABSORPTION":
        return f"{event} at {location} with no lower follow-through"
    if episode == "FAILED_BREAKOUT":
        return f"high effort rejected higher ({event}, {price}, follow_through={ft})"
    if episode == "FAILED_BREAKDOWN":
        return f"high effort rejected lower ({event}, {price}, follow_through={ft})"
    if episode in {"ACCEPTANCE_HIGHER", "ACCEPTANCE_LOWER"}:
        return f"{price} with follow_through={ft}"
    if episode == "BALANCE":
        return f"balance / no decisive auction progress (price_result={price}, follow_through={ft})"
    if event == "UNKNOWN" or location == "UNKNOWN":
        return "insufficient location / follow-through evidence"
    return f"{event} at {location}; price_result={price}; follow_through={ft}"


def build_auction_episode_rows(
    frames: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Build episode rows. `frames` optional for tests; otherwise load from disk."""
    if frames is None:
        frames = {name: _normalize_timestamp_column(_read_parquet_optional(paths)) for name, paths in INPUT_SPECS.items()}
    else:
        frames = {name: _normalize_timestamp_column(frame if frame is not None else pd.DataFrame()) for name, frame in frames.items()}

    candles = frames.get("candles", pd.DataFrame())
    live = frames.get("live", pd.DataFrame())
    if len(candles) == 0 and len(live) > 0:
        candles = live.copy()
    if len(candles) == 0:
        return pd.DataFrame(columns=REQUIRED_OUTPUT_COLUMNS)

    bar_cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume", "close_position", "candle_type", "volume_zscore"] if c in candles.columns]
    bars = candles[bar_cols].drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp").reset_index(drop=True)
    if "close" not in bars.columns:
        return pd.DataFrame(columns=REQUIRED_OUTPUT_COLUMNS)

    closes = [_safe_float(v) for v in bars["close"].tolist()]
    reference_ts = bars["timestamp"].iloc[-1]

    freshness = {
        "live": _source_freshness_label(frames.get("live", pd.DataFrame()), reference_ts),
        "candles": _source_freshness_label(frames.get("candles", pd.DataFrame()), reference_ts),
        "volume_response": _source_freshness_label(frames.get("volume_response", pd.DataFrame()), reference_ts),
        "convergence": _source_freshness_label(frames.get("convergence", pd.DataFrame()), reference_ts),
        "probabilistic": _source_freshness_label(frames.get("probabilistic", pd.DataFrame()), reference_ts),
        "cognition": _source_freshness_label(frames.get("cognition", pd.DataFrame()), reference_ts),
        "cognition_composite": _source_freshness_label(frames.get("cognition_composite", pd.DataFrame()), reference_ts),
    }
    freshness_json = json.dumps(freshness, separators=(",", ":"))

    vol = frames.get("volume_response", pd.DataFrame())
    conv = frames.get("convergence", pd.DataFrame())
    prob = frames.get("probabilistic", pd.DataFrame())
    cog = frames.get("cognition", pd.DataFrame())
    comp = frames.get("cognition_composite", pd.DataFrame())

    cognition_max_age = pd.Timedelta(minutes=45)

    def _asof_cols(source: pd.DataFrame, cols: list[str], max_age: pd.Timedelta | None = None) -> pd.DataFrame:
        base = bars[["timestamp"]].copy()
        for c in cols:
            base[c] = pd.NA
        if source is None or len(source) == 0:
            return base
        have = [c for c in cols if c in source.columns]
        if not have:
            return base
        right = source[["timestamp"] + have].drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
        right = right.rename(columns={"timestamp": "src_timestamp", **{c: f"v_{c}" for c in have}})
        merged = pd.merge_asof(
            base[["timestamp"]],
            right,
            left_on="timestamp",
            right_on="src_timestamp",
            direction="backward",
        )
        if max_age is not None:
            ok = merged["src_timestamp"].notna() & ((merged["timestamp"] - merged["src_timestamp"]) <= max_age)
        else:
            ok = merged["src_timestamp"].notna()
        for c in have:
            col = f"v_{c}"
            base[c] = merged[col].where(ok, pd.NA)
        return base

    vol_j = _asof_cols(vol, ["volume_event", "climax_state", "effort_result_state", "volume_class", "relative_volume", "localized_behavior"])
    conv_j = _asof_cols(conv, ["convergence_state", "localized_behavior"])
    prob_j = _asof_cols(prob, ["auction_regime", "distribution_probability", "absorption_probability"])
    cog_j = _asof_cols(cog, ["trigger_event", "location_bias"], max_age=cognition_max_age)
    comp_j = _asof_cols(comp, ["tier1_trigger_event", "tier1_location_bias"], max_age=cognition_max_age)

    rows: list[dict[str, Any]] = []
    for index in range(len(bars)):
        bar = bars.iloc[index]
        ts = bar["timestamp"]
        close = _safe_float(bar.get("close"))
        prev_close = closes[index - 1] if index > 0 else None
        open_ = _safe_float(bar.get("open")) if "open" in bars.columns else None
        high = _safe_float(bar.get("high")) if "high" in bars.columns else None
        low = _safe_float(bar.get("low")) if "low" in bars.columns else None
        close_position = _safe_float(bar.get("close_position")) if "close_position" in bars.columns else None
        candle_type = _clean_text(bar.get("candle_type"), default="UNKNOWN") if "candle_type" in bars.columns else "UNKNOWN"

        volume_event = _clean_text(vol_j.iloc[index].get("volume_event"), default="UNKNOWN")
        climax_state = _clean_text(vol_j.iloc[index].get("climax_state"), default="UNKNOWN")
        effort_result_state = _clean_text(vol_j.iloc[index].get("effort_result_state"), default="UNKNOWN")
        volume_class = _clean_text(vol_j.iloc[index].get("volume_class"), default="UNKNOWN")
        relative_volume = _safe_float(vol_j.iloc[index].get("relative_volume"), default=None)
        localized_from_vol = _clean_text(vol_j.iloc[index].get("localized_behavior"), default="UNKNOWN")

        convergence_state = _clean_text(conv_j.iloc[index].get("convergence_state"), default="UNKNOWN")
        localized_behavior = _clean_text(conv_j.iloc[index].get("localized_behavior"), default=localized_from_vol)

        auction_regime = _clean_text(prob_j.iloc[index].get("auction_regime"), default="UNKNOWN")
        distribution_probability = _safe_float(prob_j.iloc[index].get("distribution_probability"), default=None)
        absorption_probability = _safe_float(prob_j.iloc[index].get("absorption_probability"), default=None)

        trigger_event = _clean_text(cog_j.iloc[index].get("trigger_event"), default="UNKNOWN")
        location_bias = _clean_text(cog_j.iloc[index].get("location_bias"), default="UNKNOWN")
        tier1_trigger = _clean_text(comp_j.iloc[index].get("tier1_trigger_event"), default="UNKNOWN")
        tier1_location = _clean_text(comp_j.iloc[index].get("tier1_location_bias"), default="UNKNOWN")

        bar_event = classify_bar_event(
            trigger_event=trigger_event,
            tier1_trigger_event=tier1_trigger,
            volume_event=volume_event,
            climax_state=climax_state,
            effort_result_state=effort_result_state,
        )
        volume_effort = classify_volume_effort(
            volume_class=volume_class,
            relative_volume=relative_volume,
            climax_state=climax_state,
            volume_event=volume_event,
        )
        auction_location = classify_auction_location(
            tier1_location_bias=tier1_location,
            location_bias=location_bias,
            close_position=close_position,
        )
        effort_side = classify_effort_side(
            bar_event=bar_event,
            auction_location=auction_location,
            candle_type=candle_type,
        )
        price_result = classify_price_result(
            close=close,
            prev_close=prev_close,
            open_=open_,
            high=high,
            low=low,
            bar_event=bar_event,
        )
        follow_through = classify_follow_through(
            closes=closes,
            index=int(index),
            effort_side=effort_side,
            bar_event=bar_event,
        )
        effort_result = classify_effort_result(
            volume_effort=volume_effort,
            price_result=price_result,
            follow_through=follow_through,
            effort_result_state=effort_result_state,
        )
        auction_episode = classify_auction_episode(
            bar_event=bar_event,
            auction_location=auction_location,
            follow_through=follow_through,
            price_result=price_result,
            volume_effort=volume_effort,
            effort_result=effort_result,
        )
        episode_status = classify_episode_status(
            auction_episode=auction_episode,
            follow_through=follow_through,
            effort_result=effort_result,
        )
        episode_reason = build_episode_reason(
            bar_event=bar_event,
            auction_location=auction_location,
            follow_through=follow_through,
            auction_episode=auction_episode,
            price_result=price_result,
        )

        rows.append(
            {
                "timestamp": ts,
                "close": close,
                "bar_event": bar_event,
                "volume_event": volume_event,
                "climax_state": climax_state,
                "volume_effort": volume_effort,
                "effort_side": effort_side,
                "auction_location": auction_location,
                "price_result": price_result,
                "effort_result": effort_result,
                "follow_through": follow_through,
                "convergence_state": convergence_state,
                "localized_behavior": localized_behavior,
                "auction_regime": auction_regime,
                "distribution_probability": distribution_probability,
                "absorption_probability": absorption_probability,
                "auction_episode": auction_episode,
                "episode_status": episode_status,
                "episode_reason": episode_reason,
                "source_freshness": freshness_json,
                "builder_version": BUILDER_VERSION,
                "shadow_only": True,
            }
        )

    out = pd.DataFrame(rows)
    forbidden = {"LONG_CONTEXT", "SHORT_CONTEXT"}
    for col in ("auction_episode", "bar_event", "episode_status"):
        if col in out.columns and out[col].astype(str).isin(forbidden).any():
            raise RuntimeError(f"forbidden context token leaked into {col}")
    return out[REQUIRED_OUTPUT_COLUMNS]


def write_atomic_parquet(frame: pd.DataFrame, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output_path.stem}_", suffix=".parquet", dir=str(output_path.parent))
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
    frame = build_auction_episode_rows()
    path = write_atomic_parquet(frame, OUTPUT_PATH)
    if len(frame) == 0:
        print("rows written: 0")
        print("latest timestamp: —")
        print("latest auction_episode: —")
        print("latest episode_status: —")
        print(f"output path: {path}")
        return 0
    latest = frame.iloc[-1]
    print(f"rows written: {len(frame)}")
    print(f"latest timestamp: {latest['timestamp']}")
    print(f"latest auction_episode: {latest['auction_episode']}")
    print(f"latest episode_status: {latest['episode_status']}")
    print(f"output path: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
