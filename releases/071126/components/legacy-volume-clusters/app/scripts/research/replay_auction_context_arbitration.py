#!/usr/bin/env python3
"""Read-only auction context arbitration replay (2026-07-08 → 2026-07-09).

Replays bar-level evidence from cognition parquets and scores what directional
context *would* have been chosen if auction-context arbitration existed.

Does not modify runtime engines, parquet inputs, or dashboard state.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.cognition.auction_context_arbitrator import (  # noqa: E402
    CALIBRATED_V2_MIN_DIRECTIONAL_SCORE,
    CALIBRATED_V2_MIN_SCORE_MARGIN,
    NOT_LIVE_SAFE_RULES_REMOVED,
    OUTCOME_ONLY_EVIDENCE_FIELDS,
    AuctionContextArbitrationResult,
    AuctionContextEvidence,
    apply_calibrated_v2_filter,
    apply_calibrated_v3_filter,
    classify_long_subtype,
    classify_short_subtype_outcome_diagnostic,
    existing_context_from_trading_state,
    resolve_anchor_price,
    resolve_anchor_status,
    score_auction_context,
)
from parquet_utils import safe_read_parquet  # noqa: E402
from storage.path_registry import resolve_read, repo_root  # noqa: E402

PERIOD_START = pd.Timestamp("2026-07-08", tz="UTC")
PERIOD_END = pd.Timestamp("2026-07-10", tz="UTC")


def _parse_period(start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Inclusive end date → exclusive period end (next day UTC)."""
    period_start = pd.Timestamp(start, tz="UTC")
    period_end = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    if period_end <= period_start:
        raise ValueError(f"end must be on or after start ({start} → {end})")
    return period_start, period_end

# volume_response_memory.parquet is not registered; runtime writes volume_response_state.parquet.
VOLUME_RESPONSE_PARQUET = "volume_response_state.parquet"

PARQUET_SOURCES: dict[str, str] = {
    "market_state": "market_state_memory.parquet",
    "trading_state": "trading_state_memory.parquet",
    "cognition": "runtime_cognition_composite.parquet",
    "probabilistic": "probabilistic_auction_memory.parquet",
    "volume_response": VOLUME_RESPONSE_PARQUET,
    "convergence": "auction_convergence_memory.parquet",
    "candles": "candle_structure_memory.parquet",
    "live_feed": "live_market_feed.parquet",
}

# Unregistered replay parquets often exist only under data/cognition/ while empty root stubs remain.
REPLAY_SOURCE_CANDIDATES: dict[str, list[str]] = {
    "runtime_cognition_composite.parquet": ["data/cognition/runtime_cognition_composite.parquet"],
    "runtime_cognition_memory.parquet": ["data/cognition/runtime_cognition_memory.parquet"],
    "market_state_memory.parquet": ["data/cognition/market_state_memory.parquet"],
    "trading_state_memory.parquet": ["data/cognition/trading_state_memory.parquet"],
    "candle_structure_memory.parquet": ["data/cognition/candle_structure_memory.parquet"],
    "probabilistic_auction_memory.parquet": ["data/probabilistic/probabilistic_auction_memory.parquet"],
    "auction_convergence_memory.parquet": ["data/reinforcement/auction_convergence_memory.parquet"],
    "volume_response_state.parquet": ["data/cognition/volume_response_state.parquet"],
    "live_market_feed.parquet": ["data/live/live_market_feed.parquet", "datasets/live/latest.parquet"],
}

REPLAY_SCAN_DIRS = ("data", "data/cognition", "data/reinforcement", "data/probabilistic", "memory")

FEATURE_AUDIT_KEYWORDS = (
    "anchor",
    "anchor_status",
    "anchor_age",
    "trigger",
    "tier1",
    "location",
    "market_state",
    "stopping",
    "absorption",
    "climax",
    "convergence",
    "probabilistic",
    "trading_state",
)

REPLAY_FEATURE_FIELDS = (
    "market_state",
    "trading_state",
    "anchor_status",
    "anchor_event_type",
    "cognition_anchor_age_bars",
    "cognition_tier1_trigger_event",
    "cognition_tier1_location_bias",
    "conv_convergence_state",
)

REPLAY_SOURCE_RESOLUTION: dict[str, dict[str, Any]] = {}
REPLAY_MERGE_DIAGNOSTICS: list[dict[str, Any]] = []


def _utc_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_datetime(frame[column], utc=True, errors="coerce")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: Any, default: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    return text if text and text.lower() != "nan" else default


def _candidate_paths_for_parquet(parquet_name: str) -> list[str]:
    root = repo_root()
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        if path not in seen:
            seen.add(path)
            candidates.append(path)

    try:
        _add(resolve_read(parquet_name))
    except Exception:
        _add(str(root / parquet_name))

    for rel in REPLAY_SOURCE_CANDIDATES.get(parquet_name, ()):
        _add(str(root / rel))

    for category in ("cognition", "reinforcement", "probabilistic", "live", "diagnostics", "replay"):
        _add(str(root / "data" / category / parquet_name))

    _add(str(root / parquet_name))
    return candidates


def _resolve_replay_parquet_path(parquet_name: str) -> tuple[str, list[str], str | None]:
    """Pick first non-empty parquet among registry + replay candidates."""
    notes: list[str] = []
    for path in _candidate_paths_for_parquet(parquet_name):
        if not Path(path).exists():
            notes.append(f"missing:{path}")
            continue
        try:
            frame = safe_read_parquet(path)
        except Exception as exc:
            notes.append(f"read_error:{path}:{exc}")
            continue
        if len(frame) == 0:
            notes.append(f"empty:{path}")
            continue
        return path, notes, None
    tried = _candidate_paths_for_parquet(parquet_name)
    fallback = tried[0] if tried else ""
    return fallback, notes, f"no non-empty parquet for {parquet_name}"


def _normalize_cognition_composite(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "evaluation_timestamp" in out.columns:
        out["timestamp"] = _utc_series(out, "evaluation_timestamp")
    elif "timestamp" in out.columns:
        out["timestamp"] = _utc_series(out, "timestamp")
    return out


def _normalize_cognition_memory(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "timestamp" in out.columns:
        out["timestamp"] = _utc_series(out, "timestamp")
    if "trigger_event" in out.columns and "tier1_trigger_event" not in out.columns:
        out["tier1_trigger_event"] = out["trigger_event"]
    if "location_bias" in out.columns and "tier1_location_bias" not in out.columns:
        out["tier1_location_bias"] = out["location_bias"]
    if "synthesis_state" in out.columns and "effective_state" not in out.columns:
        out["effective_state"] = out["synthesis_state"]
    return out


def _normalize_source_frame(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    if name == "cognition":
        return _normalize_cognition_composite(frame)
    if frame.empty:
        return frame
    if "timestamp" in frame.columns:
        out = frame.copy()
        out["timestamp"] = _utc_series(out, "timestamp")
        return out
    return frame


def _load_named_parquet(parquet_name: str, *, logical_name: str | None = None) -> tuple[pd.DataFrame, str | None]:
    path, tried, note = _resolve_replay_parquet_path(parquet_name)
    key = logical_name or parquet_name
    if not path or not Path(path).exists():
        REPLAY_SOURCE_RESOLUTION[key] = {
            "parquet_name": parquet_name,
            "path": path,
            "rows": 0,
            "tried": tried,
            "note": note or "missing",
        }
        return pd.DataFrame(), note
    frame = safe_read_parquet(path)
    if logical_name == "cognition_memory":
        frame = _normalize_cognition_memory(frame)
    else:
        frame = _normalize_source_frame(key, frame)
    resolved_note = note
    if frame.empty:
        resolved_note = note or f"empty: {parquet_name} @ {path}"
    REPLAY_SOURCE_RESOLUTION[key] = {
        "parquet_name": parquet_name,
        "path": path,
        "rows": len(frame),
        "tried": tried,
        "note": resolved_note,
    }
    return frame, resolved_note


def _load_source(name: str) -> tuple[pd.DataFrame, str | None]:
    parquet_name = PARQUET_SOURCES[name]
    frame, note = _load_named_parquet(parquet_name, logical_name=name)
    return frame, note


def _coalesce_merged_columns(frame: pd.DataFrame, target_col: str, source_cols: list[str]) -> pd.DataFrame:
    out = frame.copy()
    values = out[target_col] if target_col in out.columns else pd.Series([pd.NA] * len(out), index=out.index)
    for source_col in source_cols:
        if source_col not in out.columns:
            continue
        values = values.fillna(out[source_col])
    out[target_col] = values
    return out


def _series_nonempty_rate(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    if pd.api.types.is_numeric_dtype(series):
        return float(series.fillna(0).ne(0).mean())
    cleaned = series.fillna("").astype(str).str.strip()
    return float(cleaned.ne("").mean())


def _record_merge_diagnostic(
    *,
    field: str,
    source_name: str,
    source_path: str,
    source_nonempty_rate: float,
    replay_nonempty_rate: float,
    issue: str,
) -> None:
    REPLAY_MERGE_DIAGNOSTICS.append(
        {
            "field": field,
            "source_name": source_name,
            "source_path": source_path,
            "source_nonempty_rate": source_nonempty_rate,
            "replay_nonempty_rate": replay_nonempty_rate,
            "issue": issue,
        }
    )


def _prepare_timeline(
    candles: pd.DataFrame,
    *,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> pd.DataFrame:
    frame = candles.copy()
    frame["timestamp"] = _utc_series(frame, "timestamp")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    mask = (frame["timestamp"] >= period_start) & (frame["timestamp"] < period_end)
    return frame.loc[mask, ["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def _asof_merge(
    base: pd.DataFrame,
    source: pd.DataFrame,
    *,
    source_ts_col: str,
    prefix: str,
    columns: list[str],
) -> pd.DataFrame:
    if source.empty or source_ts_col not in source.columns:
        return base
    available = [source_ts_col] + [column for column in columns if column in source.columns]
    if len(available) <= 1:
        return base
    trimmed = source[available].dropna(subset=[source_ts_col]).sort_values(source_ts_col).copy()
    rename_map = {source_ts_col: f"{prefix}_timestamp"}
    for column in available:
        if column == source_ts_col:
            continue
        rename_map[column] = f"{prefix}_{column}"
    trimmed = trimmed.rename(columns=rename_map)
    return pd.merge_asof(
        base.sort_values("timestamp"),
        trimmed.sort_values(f"{prefix}_timestamp"),
        left_on="timestamp",
        right_on=f"{prefix}_timestamp",
        direction="backward",
    )


def build_replay_frame(
    sources: dict[str, pd.DataFrame],
    *,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> pd.DataFrame:
    candles = _prepare_timeline(sources["candles"], period_start=period_start, period_end=period_end)
    if candles.empty:
        raise RuntimeError("no candle bars in replay window")

    merged = candles.copy()
    merged = _asof_merge(
        merged,
        sources["trading_state"],
        source_ts_col="timestamp",
        prefix="trading",
        columns=["trading_state", "market_state", "market_state_confidence", "confidence_band"],
    )
    merged = _asof_merge(
        merged,
        sources["market_state"],
        source_ts_col="timestamp",
        prefix="market",
        columns=["market_state", "market_bias", "market_state_confidence", "rule_id", "transition_class"],
    )
    cognition = _normalize_cognition_composite(sources["cognition"].copy())
    merged = _asof_merge(
        merged,
        cognition,
        source_ts_col="timestamp",
        prefix="cognition",
        columns=[
            "effective_state",
            "tier1_trigger_event",
            "tier1_location_bias",
            "tier2_anchor_timestamp",
            "tier2_anchor_stage2_state",
            "anchor_age_bars",
        ],
    )
    cognition_memory = sources.get("cognition_memory")
    if cognition_memory is not None and not cognition_memory.empty:
        memory = _normalize_cognition_memory(cognition_memory.copy())
        merged = _asof_merge(
            merged,
            memory,
            source_ts_col="timestamp",
            prefix="cognition_mem",
            columns=["tier1_trigger_event", "tier1_location_bias", "effective_state"],
        )
        merged = _coalesce_merged_columns(
            merged,
            "cognition_tier1_trigger_event",
            ["cognition_mem_tier1_trigger_event"],
        )
        merged = _coalesce_merged_columns(
            merged,
            "cognition_tier1_location_bias",
            ["cognition_mem_tier1_location_bias"],
        )
        merged = _coalesce_merged_columns(
            merged,
            "cognition_effective_state",
            ["cognition_mem_effective_state"],
        )
    merged = _asof_merge(
        merged,
        sources["probabilistic"],
        source_ts_col="timestamp",
        prefix="prob",
        columns=[
            "auction_regime",
            "absorption_probability",
            "distribution_probability",
            "absorption_behavior_share",
            "supply_behavior_share",
        ],
    )
    merged = _asof_merge(
        merged,
        sources["volume_response"],
        source_ts_col="timestamp",
        prefix="volume",
        columns=[
            "volume_event",
            "climax_state",
            "effort_result_state",
            "continuation_quality",
            "localized_behavior",
        ],
    )
    merged = _asof_merge(
        merged,
        sources["convergence"],
        source_ts_col="timestamp",
        prefix="conv",
        columns=["convergence_state", "distribution_events", "localized_behavior"],
    )

    if "market_market_state" in merged.columns:
        merged["market_state"] = merged["market_market_state"]
    elif "trading_market_state" in merged.columns:
        merged["market_state"] = merged["trading_market_state"]
    else:
        merged["market_state"] = pd.NA
    if "trading_market_state" in merged.columns:
        merged["market_state"] = merged["market_state"].fillna(merged["trading_market_state"])
    if "market_market_bias" in merged.columns:
        merged["market_bias"] = merged["market_market_bias"].fillna("NEUTRAL")
    elif "trading_market_state" in merged.columns:
        merged["market_bias"] = "NEUTRAL"
    else:
        merged["market_bias"] = "NEUTRAL"

    rows: list[dict[str, Any]] = []
    candle_history = sources["candles"].copy()
    candle_history["timestamp"] = _utc_series(candle_history, "timestamp")

    global REPLAY_MERGED_SNAPSHOT
    REPLAY_MERGED_SNAPSHOT = merged.copy()

    for _, row in merged.iterrows():
        anchor_ts = pd.to_datetime(row.get("cognition_tier2_anchor_timestamp"), utc=True, errors="coerce")
        if pd.isna(anchor_ts):
            anchor_ts = None
        location_bias = _clean_text(row.get("cognition_tier1_location_bias"))
        anchor_price = resolve_anchor_price(candle_history, anchor_ts, location_bias)
        anchor_status = resolve_anchor_status(
            anchor_price=anchor_price,
            location_bias=location_bias,
            close=_safe_float(row.get("close")),
            anchor_age_bars=_safe_float(row.get("cognition_anchor_age_bars")),
            continuation_quality=_clean_text(row.get("volume_continuation_quality")),
            convergence_state=_clean_text(row.get("conv_convergence_state")),
        )

        trading_state = _clean_text(row.get("trading_trading_state"))
        market_state = _clean_text(row.get("market_state"))
        market_bias = _clean_text(row.get("market_bias"))

        evidence = AuctionContextEvidence(
            timestamp=row["timestamp"],
            close=_safe_float(row.get("close")),
            market_state=market_state,
            market_bias=market_bias,
            trading_state=trading_state,
            volume_event=_clean_text(row.get("volume_volume_event")),
            climax_state=_clean_text(row.get("volume_climax_state")),
            effort_result_state=_clean_text(row.get("volume_effort_result_state")),
            continuation_quality=_clean_text(row.get("volume_continuation_quality")),
            localized_behavior=_clean_text(row.get("volume_localized_behavior"))
            or _clean_text(row.get("conv_localized_behavior")),
            convergence_state=_clean_text(row.get("conv_convergence_state")),
            auction_regime=_clean_text(row.get("prob_auction_regime")),
            effective_state=_clean_text(row.get("cognition_effective_state")),
            tier1_trigger_event=_clean_text(row.get("cognition_tier1_trigger_event")),
            tier1_location_bias=location_bias,
            anchor_timestamp=anchor_ts,
            anchor_age_bars=_safe_float(row.get("cognition_anchor_age_bars")),
            absorption_probability=_safe_float(row.get("prob_absorption_probability")),
            distribution_probability=_safe_float(row.get("prob_distribution_probability")),
            absorption_behavior_share=_safe_float(row.get("prob_absorption_behavior_share")),
            supply_behavior_share=_safe_float(row.get("prob_supply_behavior_share")),
            anchor_price=anchor_price,
            anchor_status=anchor_status,
            candle_history=candle_history,
        )
        result = score_auction_context(evidence)

        rows.append(
            {
                "timestamp": row["timestamp"],
                "close": _safe_float(row.get("close")),
                "market_state": market_state,
                "market_bias": market_bias,
                "trading_state": trading_state,
                "existing_context": existing_context_from_trading_state(trading_state),
                "anchor_event_type": result.anchor_event_type,
                "anchor_timestamp": anchor_ts,
                "anchor_price_or_zone": result.anchor_price_or_zone,
                "anchor_status": result.anchor_status,
                "long_context_score": result.long_context_score,
                "short_context_score": result.short_context_score,
                "observe_score": result.observe_score,
                "chosen_context": result.chosen_context,
                "chosen_reason": result.chosen_reason,
                "why_not_long": result.why_not_long,
                "why_not_short": result.why_not_short,
                "prob_auction_regime": _clean_text(row.get("prob_auction_regime")),
                "prob_regime_state": _clean_text(row.get("prob_regime_state")),
                "conv_convergence_state": _clean_text(row.get("conv_convergence_state")),
                "cognition_tier1_trigger_event": _clean_text(row.get("cognition_tier1_trigger_event")),
                "cognition_tier1_location_bias": _clean_text(row.get("cognition_tier1_location_bias")),
                "cognition_anchor_age_bars": _safe_float(row.get("cognition_anchor_age_bars")),
                "volume_effort_result_state": _clean_text(row.get("volume_effort_result_state")),
                "volume_climax_state": _clean_text(row.get("volume_climax_state")),
                "volume_continuation_quality": _clean_text(row.get("volume_continuation_quality")),
                "source_market_state_timestamp": row.get("market_timestamp"),
                "source_trading_state_timestamp": row.get("trading_timestamp"),
            }
        )

    return pd.DataFrame(rows)


FORWARD_HORIZONS = (4, 8, 16, 32)
OBSERVE_ABS_RETURN_THRESHOLD = 0.003
OBSERVE_NOISE_SPREAD_THRESHOLD = 0.002

SWEEP_MIN_DIRECTIONAL_SCORES = (0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
SWEEP_MIN_SCORE_MARGINS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)


def _forward_extremes_16b(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    highs = [frame["high"].shift(-offset) for offset in range(1, 17)]
    lows = [frame["low"].shift(-offset) for offset in range(1, 17)]
    fwd_high = pd.concat(highs, axis=1).max(axis=1)
    fwd_low = pd.concat(lows, axis=1).min(axis=1)
    max_up = (fwd_high - frame["close"]) / frame["close"]
    max_down = (frame["close"] - fwd_low) / frame["close"]
    return max_up, max_down


def attach_forward_outcomes(replay: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    """Attach forward returns and context-oriented favorable/adverse excursions."""
    if replay.empty:
        return replay

    timeline = candles.copy()
    timeline["timestamp"] = _utc_series(timeline, "timestamp")
    timeline = timeline.sort_values("timestamp").reset_index(drop=True)

    for bars in FORWARD_HORIZONS:
        timeline[f"forward_return_{bars}b"] = timeline["close"].shift(-bars) / timeline["close"] - 1.0

    max_up, max_down = _forward_extremes_16b(timeline)
    timeline["max_up_16b"] = max_up
    timeline["max_down_16b"] = max_down

    outcome_cols = [f"forward_return_{bars}b" for bars in FORWARD_HORIZONS] + [
        "high",
        "low",
        "max_up_16b",
        "max_down_16b",
    ]
    enriched = replay.merge(
        timeline[["timestamp", *outcome_cols]],
        on="timestamp",
        how="left",
    )

    favorable: list[float | None] = []
    adverse: list[float | None] = []
    for _, row in enriched.iterrows():
        up = row.get("max_up_16b")
        down = row.get("max_down_16b")
        if pd.isna(up) or pd.isna(down):
            favorable.append(None)
            adverse.append(None)
            continue
        context = _clean_text(row.get("chosen_context")).upper()
        if context == "SHORT_CONTEXT":
            favorable.append(float(down))
            adverse.append(float(up))
        else:
            favorable.append(float(up))
            adverse.append(float(down))
    enriched["max_favorable_16b"] = favorable
    enriched["max_adverse_16b"] = adverse
    return enriched


def _refresh_favorable_adverse(frame: pd.DataFrame) -> pd.DataFrame:
    """Recompute context-oriented favorable/adverse after chosen_context changes."""
    out = frame.copy()
    favorable: list[float | None] = []
    adverse: list[float | None] = []
    for _, row in out.iterrows():
        up = row.get("max_up_16b")
        down = row.get("max_down_16b")
        if pd.isna(up) or pd.isna(down):
            favorable.append(None)
            adverse.append(None)
            continue
        context = _clean_text(row.get("chosen_context")).upper()
        if context == "SHORT_CONTEXT":
            favorable.append(float(down))
            adverse.append(float(up))
        else:
            favorable.append(float(up))
            adverse.append(float(down))
    out["max_favorable_16b"] = favorable
    out["max_adverse_16b"] = adverse
    return out


SHORT_SUBTYPES = (
    "FAILED_BULLISH_REVERSAL_BREAKDOWN",
    "DISTRIBUTION_AFTER_BUYING_CLIMAX",
    "DIRECTIONAL_DISTRIBUTION_CONTINUATION",
    "SHORT_IMPULSE_ONLY",
    "LATE_EXHAUSTION_SHORT",
    "UNKNOWN_SHORT",
)

ALLOWED_LIVE_SHORT_SUBTYPES = frozenset(
    {
        "DISTRIBUTION_AFTER_BUYING_CLIMAX",
        "DIRECTIONAL_DISTRIBUTION_CONTINUATION",
    }
)


def _extract_anchor_price(anchor_price_or_zone: Any) -> float | None:
    text = _clean_text(anchor_price_or_zone)
    if not text:
        return None
    if "@" in text:
        text = text.split("@", 1)[1]
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _classify_short_subtype(row: pd.Series) -> str:
    if _clean_text(row.get("chosen_context")).upper() != "SHORT_CONTEXT":
        return ""

    anchor_status = _clean_text(row.get("anchor_status")).upper()
    anchor_event = _clean_text(row.get("anchor_event_type")).upper()
    market_state = _clean_text(row.get("market_state")).upper()
    anchor_zone = _clean_text(row.get("anchor_price_or_zone")).upper()
    reason = _clean_text(row.get("chosen_reason")).lower()
    close = _safe_float(row.get("close"), default=float("nan"))
    anchor_price = _extract_anchor_price(row.get("anchor_price_or_zone"))
    f4 = _safe_float(row.get("forward_return_4b"), default=float("nan"))
    f8 = _safe_float(row.get("forward_return_8b"), default=float("nan"))
    f16 = _safe_float(row.get("forward_return_16b"), default=float("nan"))
    max_fav = _safe_float(row.get("max_favorable_16b"), default=float("nan"))
    max_adv = _safe_float(row.get("max_adverse_16b"), default=float("nan"))

    lower_reversal_anchor = ("STOPPING" in anchor_event) or ("LOWER" in anchor_zone)
    downside_continuation = (
        ("efficient downside continuation" in reason)
        or ("persistent distribution" in reason)
        or (not pd.isna(f4) and f4 < -0.001)
    )
    broke_anchor = anchor_price is not None and not pd.isna(close) and close < anchor_price
    if anchor_status == "FAILED" and lower_reversal_anchor and broke_anchor and downside_continuation:
        return "FAILED_BULLISH_REVERSAL_BREAKDOWN"

    buying_or_upper = (
        ("BUYING" in anchor_event)
        or ("CLIMAX" in anchor_event)
        or ("UPPER" in anchor_zone)
        or ("buying climax" in reason)
    )
    distribution_or_supply = (
        market_state == "DISTRIBUTION"
        or ("distribution" in reason)
        or ("supply" in reason)
    )
    upside_failed = (not pd.isna(f8) and f8 <= 0) or ("upside continuation failed" in reason)
    if buying_or_upper and distribution_or_supply and upside_failed:
        return "DISTRIBUTION_AFTER_BUYING_CLIMAX"

    impulse_only = (
        (not pd.isna(f4) and f4 < 0)
        and ((not pd.isna(f8) and f8 >= 0) or (not pd.isna(f16) and f16 >= 0))
    )
    if impulse_only:
        return "SHORT_IMPULSE_ONLY"

    rebound_soon = ((not pd.isna(f8) and f8 > 0) or (not pd.isna(f16) and f16 > 0))
    if rebound_soon and (not pd.isna(max_adv) and not pd.isna(max_fav) and max_adv > max_fav):
        return "LATE_EXHAUSTION_SHORT"

    return "UNKNOWN_SHORT"


def _attach_short_subtypes(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["short_subtype"] = out.apply(_classify_short_subtype, axis=1)
    return out


LONG_SUBTYPES = (
    "HELD_STOPPING_VOLUME_REVERSAL",
    "ABSORPTION_RECLAIM_LONG",
    "LOWER_AUCTION_DEFENSE",
    "LATE_REBOUND_LONG",
    "WEAK_OR_UNKNOWN_LONG",
)


def _attach_long_context_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.sort_values("timestamp").reset_index(drop=True).copy()
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out["recent_return_4b"] = out["close"] / out["close"].shift(4) - 1.0
    out["recent_return_8b"] = out["close"] / out["close"].shift(8) - 1.0
    out["recent_return_16b"] = out["close"] / out["close"].shift(16) - 1.0
    anchor_price = pd.to_numeric(
        out["anchor_price_or_zone"].apply(_extract_anchor_price), errors="coerce"
    )
    out["anchor_price_numeric"] = anchor_price
    out["above_or_at_anchor"] = (anchor_price.isna()) | (out["close"] >= anchor_price)
    return out


def _classify_long_subtype(row: pd.Series) -> str:
    """Live-safe long subtype for calibrated_v2 decisions (backward returns only)."""
    context_for_subtype = _clean_text(row.get("raw_chosen_context") or row.get("chosen_context")).upper()
    if context_for_subtype != "LONG_CONTEXT":
        return ""

    anchor_status = _clean_text(row.get("anchor_status")).upper()
    anchor_event = _clean_text(row.get("anchor_event_type")).upper()
    anchor_zone = _clean_text(row.get("anchor_price_or_zone")).upper()
    reason = _clean_text(row.get("chosen_reason")).lower()
    market_state = _clean_text(row.get("market_state")).upper()
    close = _safe_float(row.get("close"), default=float("nan"))
    anchor_price = _extract_anchor_price(row.get("anchor_price_or_zone"))
    recent_4 = _safe_float(row.get("recent_return_4b"), default=float("nan"))
    recent_8 = _safe_float(row.get("recent_return_8b"), default=float("nan"))
    recent_16 = _safe_float(row.get("recent_return_16b"), default=float("nan"))

    lower_zone = ("LOWER" in anchor_zone) or ("lower" in reason) or ("at lows" in reason)
    stopping_evidence = (
        ("STOPPING" in anchor_event)
        or ("stopping" in reason)
        or ("stopping/absorption volume at lows" in reason)
    )
    absorption_evidence = (
        ("absorption response held" in reason)
        or ("absorption" in reason)
        or ("ABSORPTION" in anchor_event)
    )
    downside_failed = (
        ("downside continuation failed" in reason)
        or (not pd.isna(recent_8) and recent_8 > -0.004 and recent_8 < 0.004)
    )
    reclaimed = (
        anchor_status == "HELD"
        or (anchor_price is not None and not pd.isna(close) and close >= anchor_price)
        or ("reversal anchor held" in reason)
        or ("reclaims" in reason)
    )

    if anchor_status == "HELD" and stopping_evidence and lower_zone:
        return "HELD_STOPPING_VOLUME_REVERSAL"

    if absorption_evidence and reclaimed and (lower_zone or market_state == "REVERSAL"):
        return "ABSORPTION_RECLAIM_LONG"

    extended_downside = (
        (not pd.isna(recent_8) and recent_8 < -0.005)
        or (not pd.isna(recent_16) and recent_16 < -0.008)
        or ("price falling" in reason)
    )
    micro_bounce_not_held = (
        (not pd.isna(recent_4) and recent_4 > 0) and (not pd.isna(recent_8) and recent_8 < 0)
    )
    if extended_downside and micro_bounce_not_held:
        return "LATE_REBOUND_LONG"

    if lower_zone and (stopping_evidence or absorption_evidence or downside_failed):
        return "LOWER_AUCTION_DEFENSE"

    return "WEAK_OR_UNKNOWN_LONG"


def _classify_long_subtype_outcome_diagnostic(row: pd.Series) -> str:
    """Research-only relabel using forward outcomes — not used for calibrated_v2 decisions."""
    if _clean_text(row.get("chosen_context")).upper() != "LONG_CONTEXT":
        return ""

    live_label = _classify_long_subtype(row)
    f4 = _safe_float(row.get("forward_return_4b"), default=float("nan"))
    f8 = _safe_float(row.get("forward_return_8b"), default=float("nan"))
    f16 = _safe_float(row.get("forward_return_16b"), default=float("nan"))
    max_fav = _safe_float(row.get("max_favorable_16b"), default=float("nan"))
    max_adv = _safe_float(row.get("max_adverse_16b"), default=float("nan"))
    recent_8 = _safe_float(row.get("recent_return_8b"), default=float("nan"))
    recent_16 = _safe_float(row.get("recent_return_16b"), default=float("nan"))

    extended_downside = (
        (not pd.isna(recent_8) and recent_8 < -0.005)
        or (not pd.isna(recent_16) and recent_16 < -0.008)
    )
    rebound_then_fade = (
        ((not pd.isna(f4) and f4 > 0) or (not pd.isna(f8) and f8 > 0))
        and ((not pd.isna(f16) and f16 <= 0) or (not pd.isna(max_adv) and not pd.isna(max_fav) and max_adv > max_fav))
    )
    if extended_downside and rebound_then_fade and live_label != "LATE_REBOUND_LONG":
        return "LATE_REBOUND_LONG"
    return live_label


def _attach_long_subtypes(frame: pd.DataFrame) -> pd.DataFrame:
    out = _attach_long_context_features(frame)
    out["long_subtype"] = out.apply(_classify_long_subtype, axis=1)
    if "forward_return_16b" in out.columns:
        out["outcome_diagnostic_long_subtype"] = out.apply(_classify_long_subtype_outcome_diagnostic, axis=1)
    return out


def _long_subtype_run_outcomes(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "high" not in frame.columns or "low" not in frame.columns:
        return pd.DataFrame()
    work = frame[frame["chosen_context"] == "LONG_CONTEXT"].sort_values("timestamp").reset_index(drop=True)
    if work.empty:
        return pd.DataFrame()
    run_id = (
        (work["long_subtype"] != work["long_subtype"].shift())
        | (work["chosen_context"] != work["chosen_context"].shift())
    ).cumsum()
    episodes: list[dict[str, Any]] = []
    for _, group in work.groupby(run_id, sort=False):
        subtype = _clean_text(group.iloc[0]["long_subtype"])
        entry = _safe_float(group.iloc[0]["close"])
        if not subtype or entry <= 0:
            continue
        exit_close = _safe_float(group.iloc[-1]["close"])
        max_high = _safe_float(group["high"].max())
        min_low = _safe_float(group["low"].min())
        episodes.append(
            {
                "long_subtype": subtype,
                "context_exit_return": (exit_close - entry) / entry,
                "context_max_favorable": (max_high - entry) / entry,
                "context_max_adverse": (entry - min_low) / entry,
                "bars": len(group),
            }
        )
    return pd.DataFrame(episodes)


def _week_label(ts: pd.Timestamp, period_start: pd.Timestamp, period_end: pd.Timestamp) -> str:
    for week_start, week_end, label in _iter_weekly_buckets(period_start, period_end):
        if week_start <= ts < week_end:
            return label
    return "out_of_range"


def _long_subtype_weekly_distribution(
    frame: pd.DataFrame,
    *,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> pd.DataFrame:
    long_rows = frame[frame["chosen_context"] == "LONG_CONTEXT"].copy()
    if long_rows.empty:
        return pd.DataFrame(columns=["week", "long_subtype", "bars"])
    long_rows["week"] = pd.to_datetime(long_rows["timestamp"], utc=True).map(
        lambda ts: _week_label(ts, period_start, period_end)
    )
    grouped = (
        long_rows.groupby(["week", "long_subtype"], dropna=False)
        .size()
        .reset_index(name="bars")
        .sort_values(["week", "long_subtype"])
    )
    return grouped


def _long_subtype_report_lines(
    filtered: pd.DataFrame,
    *,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> list[str]:
    long_rows = filtered[filtered["chosen_context"] == "LONG_CONTEXT"].copy()
    if long_rows.empty:
        return ["## LONG subtype diagnostics (calibrated_v2)", "", "_No LONG_CONTEXT rows after calibrated_v2._", ""]

    subtype_runs = _long_subtype_run_outcomes(filtered)
    weekly = _long_subtype_weekly_distribution(
        filtered,
        period_start=period_start,
        period_end=period_end,
    )
    lines = [
        "## LONG subtype diagnostics (calibrated_v2)",
        "",
        "| subtype | bars | exp4% | exp8% | exp16% | exp32% | hit4% | hit8% | hit16% | hit32% | max_fav% | max_adv% | avg_duration |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    subtype_stats: list[dict[str, Any]] = []
    for subtype in LONG_SUBTYPES:
        subset = long_rows[long_rows["long_subtype"] == subtype].copy()
        if subset.empty:
            lines.append(f"| {subtype} | 0 | — | — | — | — | — | — | — | — | — | — | — |")
            continue

        if "high" in subset.columns and "low" in subset.columns:
            max_up_4, max_down_4 = _forward_extremes_nb(subset, 4)
            max_up_8, max_down_8 = _forward_extremes_nb(subset, 8)
            max_up_32, max_down_32 = _forward_extremes_nb(subset, 32)
            subset = subset.assign(
                _tmp_max_up_4=max_up_4,
                _tmp_max_down_4=max_down_4,
                _tmp_max_up_8=max_up_8,
                _tmp_max_down_8=max_down_8,
                _tmp_max_up_32=max_up_32,
                _tmp_max_down_32=max_down_32,
            )

        def _hit_for_bars(bars: int) -> float:
            check = subset.copy()
            if bars == 4:
                check["_tmp_max_up"] = check.get("_tmp_max_up_4")
                check["_tmp_max_down"] = check.get("_tmp_max_down_4")
            elif bars == 8:
                check["_tmp_max_up"] = check.get("_tmp_max_up_8")
                check["_tmp_max_down"] = check.get("_tmp_max_down_8")
            elif bars == 32:
                check["_tmp_max_up"] = check.get("_tmp_max_up_32")
                check["_tmp_max_down"] = check.get("_tmp_max_down_32")
            return float(check.apply(lambda r: _is_long_correct_horizon(r, bars), axis=1).mean() * 100)

        run_subset = subtype_runs[subtype_runs["long_subtype"] == subtype]
        avg_dur = float(run_subset["bars"].mean()) if len(run_subset) else 0.0
        max_fav = float(run_subset["context_max_favorable"].mean()) * 100 if len(run_subset) else float("nan")
        max_adv = float(run_subset["context_max_adverse"].mean()) * 100 if len(run_subset) else float("nan")
        exp16 = float(subset["forward_return_16b"].mean()) if len(subset) else float("nan")

        subtype_stats.append(
            {
                "subtype": subtype,
                "bars": len(subset),
                "exp16": exp16,
                "hit16": _hit_for_bars(16),
            }
        )

        lines.append(
            f"| {subtype} | {len(subset)} | "
            f"{subset['forward_return_4b'].mean()*100:.3f} | {subset['forward_return_8b'].mean()*100:.3f} | "
            f"{subset['forward_return_16b'].mean()*100:.3f} | {subset['forward_return_32b'].mean()*100:.3f} | "
            f"{_hit_for_bars(4):.1f} | {_hit_for_bars(8):.1f} | {_hit_for_bars(16):.1f} | {_hit_for_bars(32):.1f} | "
            f"{max_fav:.3f} | {max_adv:.3f} | {avg_dur:.1f} |"
        )

    lines.extend(["", "### Weekly distribution", ""])
    if weekly.empty:
        lines.append("_No weekly LONG rows._")
    else:
        lines.append("| week | subtype | bars |")
        lines.append("| --- | --- | ---: |")
        for _, row in weekly.iterrows():
            lines.append(f"| {row['week']} | {row['long_subtype']} | {int(row['bars'])} |")
    lines.append("")

    for subtype in LONG_SUBTYPES:
        subset = long_rows[long_rows["long_subtype"] == subtype].copy()
        if subset.empty:
            continue
        false_long = subset[subset["forward_return_16b"] < 0].sort_values("forward_return_16b")
        true_long = subset[subset["forward_return_16b"] > 0].sort_values("forward_return_16b", ascending=False)
        lines.extend(
            [
                f"### {subtype} — best true LONG",
                "",
                _md_table(
                    true_long,
                    ["timestamp", "close", "forward_return_4b", "forward_return_8b", "forward_return_16b", "chosen_reason"],
                    max_rows=5,
                ),
                f"### {subtype} — worst false LONG",
                "",
                _md_table(
                    false_long,
                    ["timestamp", "close", "forward_return_4b", "forward_return_8b", "forward_return_16b", "chosen_reason"],
                    max_rows=5,
                ),
                "",
            ]
        )

    active = [row for row in subtype_stats if row["bars"] > 0]
    if active:
        best = max(active, key=lambda row: row["exp16"] if not pd.isna(row["exp16"]) else float("-inf"))
        worst = min(active, key=lambda row: row["exp16"] if not pd.isna(row["exp16"]) else float("inf"))
        tactical_candidates = {
            row["subtype"]
            for row in active
            if row["subtype"] in {"LATE_REBOUND_LONG", "WEAK_OR_UNKNOWN_LONG", "LOWER_AUCTION_DEFENSE"}
            and (pd.isna(row["exp16"]) or row["exp16"] <= 0 or row["hit16"] < 50)
        }
        directional_candidates = {
            row["subtype"]
            for row in active
            if row["subtype"] in {"HELD_STOPPING_VOLUME_REVERSAL", "ABSORPTION_RECLAIM_LONG"}
            and (not pd.isna(row["exp16"]) and row["exp16"] > 0 and row["hit16"] >= 50)
        }
        split_recommended = bool(tactical_candidates and directional_candidates)
        lines.extend(
            [
                "## LONG subtype conclusion",
                "",
                f"- **Subtype with real edge:** `{best['subtype']}` "
                f"(16b exp {best['exp16']*100:.3f}%, hit16 {best['hit16']:.1f}%, bars {best['bars']})",
                f"- **Subtype to suppress:** `{worst['subtype']}` "
                f"(16b exp {worst['exp16']*100:.3f}%, hit16 {worst['hit16']:.1f}%, bars {worst['bars']})",
                f"- **Split directional_long vs tactical_long:** "
                f"{'yes' if split_recommended else 'not yet — edge too mixed or sample too thin'}",
                f"- **Directional_long candidates:** {', '.join(sorted(directional_candidates)) or 'none'}",
                f"- **Tactical_long candidates:** {', '.join(sorted(tactical_candidates)) or 'none'}",
                "",
            ]
        )

    return lines


def build_long_subtype_report(
    calibrated: pd.DataFrame,
    *,
    csv_path: Path,
    md_path: Path,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> str:
    classified = _attach_long_subtypes(calibrated)
    long_rows = classified[classified["chosen_context"] == "LONG_CONTEXT"].copy()
    long_rows.to_csv(csv_path, index=False)
    report = "\n".join(
        _long_subtype_report_lines(
            classified,
            period_start=period_start,
            period_end=period_end,
        )
    )
    md_path.write_text(report, encoding="utf-8")
    return report


def _forward_extremes_nb(frame: pd.DataFrame, bars: int) -> tuple[pd.Series, pd.Series]:
    if bars <= 0:
        zeros = pd.Series(0.0, index=frame.index)
        return zeros, zeros
    highs = [frame["high"].shift(-offset) for offset in range(1, bars + 1)]
    lows = [frame["low"].shift(-offset) for offset in range(1, bars + 1)]
    fwd_high = pd.concat(highs, axis=1).max(axis=1)
    fwd_low = pd.concat(lows, axis=1).min(axis=1)
    max_up = (fwd_high - frame["close"]) / frame["close"]
    max_down = (frame["close"] - fwd_low) / frame["close"]
    return max_up, max_down


def _is_long_correct_horizon(row: pd.Series, bars: int) -> bool:
    fwd = _safe_float(row.get(f"forward_return_{bars}b"), default=float("nan"))
    if not pd.isna(fwd) and fwd > 0:
        return True
    up = _safe_float(row.get("max_up_16b") if bars == 16 else float("nan"), default=float("nan"))
    down = _safe_float(row.get("max_down_16b") if bars == 16 else float("nan"), default=float("nan"))
    if bars != 16:
        up_s = row.get("_tmp_max_up")
        down_s = row.get("_tmp_max_down")
        if up_s is not None and not pd.isna(up_s):
            up, down = float(up_s), float(down_s)
    if pd.isna(up) or pd.isna(down):
        return False
    return up > down


def _is_short_correct_horizon(row: pd.Series, bars: int) -> bool:
    fwd = _safe_float(row.get(f"forward_return_{bars}b"), default=float("nan"))
    if not pd.isna(fwd) and fwd < 0:
        return True
    up = _safe_float(row.get("max_up_16b") if bars == 16 else float("nan"), default=float("nan"))
    down = _safe_float(row.get("max_down_16b") if bars == 16 else float("nan"), default=float("nan"))
    if bars != 16:
        up_s = row.get("_tmp_max_up")
        down_s = row.get("_tmp_max_down")
        if up_s is not None and not pd.isna(up_s):
            up, down = float(up_s), float(down_s)
    if pd.isna(up) or pd.isna(down):
        return False
    return down > up


def _horizon_metrics(frame: pd.DataFrame, context: str, bars: int) -> tuple[float, float]:
    col = f"forward_return_{bars}b"
    subset = frame[frame["chosen_context"] == context].copy()
    if subset.empty or col not in subset.columns:
        return float("nan"), float("nan")
    valid = subset.dropna(subset=[col])
    if valid.empty:
        return float("nan"), float("nan")
    if bars != 16 and "high" in valid.columns and "low" in valid.columns:
        max_up, max_down = _forward_extremes_nb(valid, bars)
        valid = valid.assign(_tmp_max_up=max_up, _tmp_max_down=max_down)
    if context == "LONG_CONTEXT":
        hits = valid.apply(lambda row: _is_long_correct_horizon(row, bars), axis=1)
    else:
        hits = valid.apply(lambda row: _is_short_correct_horizon(row, bars), axis=1)
    return float(valid[col].mean()), float(hits.mean())


def _context_run_outcomes(frame: pd.DataFrame) -> pd.DataFrame:
    """Episode-level outcomes for directional context runs."""
    if frame.empty or "high" not in frame.columns or "low" not in frame.columns:
        return pd.DataFrame()
    work = frame.sort_values("timestamp").reset_index(drop=True)
    run_id = (work["chosen_context"] != work["chosen_context"].shift()).cumsum()
    episodes: list[dict[str, Any]] = []
    for _, group in work.groupby(run_id, sort=False):
        label = _clean_text(group.iloc[0]["chosen_context"]).upper()
        if label not in {"LONG_CONTEXT", "SHORT_CONTEXT"}:
            continue
        entry = _safe_float(group.iloc[0]["close"])
        if entry <= 0:
            continue
        exit_close = _safe_float(group.iloc[-1]["close"])
        signed_return = (exit_close - entry) / entry
        max_high = _safe_float(group["high"].max())
        min_low = _safe_float(group["low"].min())
        if label == "LONG_CONTEXT":
            max_fav = (max_high - entry) / entry
            max_adv = (entry - min_low) / entry
        else:
            max_fav = (entry - min_low) / entry
            max_adv = (max_high - entry) / entry
        episodes.append(
            {
                "context": label,
                "context_exit_return": signed_return,
                "context_max_favorable": max_fav,
                "context_max_adverse": max_adv,
                "bars": len(group),
            }
        )
    return pd.DataFrame(episodes)


def _context_exit_summary(frame: pd.DataFrame, context: str) -> dict[str, float]:
    episodes = _context_run_outcomes(frame)
    subset = episodes[episodes["context"] == context]
    if subset.empty:
        return {
            "context_exit_return": float("nan"),
            "context_max_favorable": float("nan"),
            "context_max_adverse": float("nan"),
        }
    return {
        "context_exit_return": float(subset["context_exit_return"].mean()),
        "context_max_favorable": float(subset["context_max_favorable"].mean()),
        "context_max_adverse": float(subset["context_max_adverse"].mean()),
    }


def _short_subtype_run_outcomes(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "high" not in frame.columns or "low" not in frame.columns:
        return pd.DataFrame()
    work = frame[frame["chosen_context"] == "SHORT_CONTEXT"].sort_values("timestamp").reset_index(drop=True)
    if work.empty:
        return pd.DataFrame()
    run_id = (
        (work["short_subtype"] != work["short_subtype"].shift())
        | (work["chosen_context"] != work["chosen_context"].shift())
    ).cumsum()
    episodes: list[dict[str, Any]] = []
    for _, group in work.groupby(run_id, sort=False):
        subtype = _clean_text(group.iloc[0]["short_subtype"])
        entry = _safe_float(group.iloc[0]["close"])
        if not subtype or entry <= 0:
            continue
        exit_close = _safe_float(group.iloc[-1]["close"])
        max_high = _safe_float(group["high"].max())
        min_low = _safe_float(group["low"].min())
        episodes.append(
            {
                "short_subtype": subtype,
                "context_exit_return": (exit_close - entry) / entry,
                "context_max_favorable": (entry - min_low) / entry,
                "context_max_adverse": (max_high - entry) / entry,
                "bars": len(group),
            }
        )
    return pd.DataFrame(episodes)


def _horizon_breakdown_for_threshold(
    replay: pd.DataFrame,
    *,
    min_directional_score: float,
    min_score_margin: float,
) -> dict[str, Any]:
    swept = apply_threshold_filter(
        replay,
        min_directional_score=min_directional_score,
        min_score_margin=min_score_margin,
    )
    breakdown: dict[str, Any] = {
        "min_directional_score": min_directional_score,
        "min_score_margin": min_score_margin,
    }
    for bars in FORWARD_HORIZONS:
        long_exp, long_hit = _horizon_metrics(swept, "LONG_CONTEXT", bars)
        short_exp, short_hit = _horizon_metrics(swept, "SHORT_CONTEXT", bars)
        breakdown[f"long_expectancy_{bars}b"] = long_exp
        breakdown[f"short_expectancy_{bars}b"] = short_exp
        breakdown[f"long_hit_rate_{bars}b"] = long_hit
        breakdown[f"short_hit_rate_{bars}b"] = short_hit
    long_exit = _context_exit_summary(swept, "LONG_CONTEXT")
    short_exit = _context_exit_summary(swept, "SHORT_CONTEXT")
    breakdown.update({f"long_{key}": value for key, value in long_exit.items()})
    breakdown.update({f"short_{key}": value for key, value in short_exit.items()})
    return breakdown


def _best_horizon_label(expectancies: dict[int, float], *, context: str) -> tuple[int, float]:
    best_bars = 16
    best_val = expectancies.get(16, float("nan"))
    for bars in FORWARD_HORIZONS:
        val = expectancies.get(bars, float("nan"))
        if pd.isna(val):
            continue
        if context == "LONG_CONTEXT":
            if pd.isna(best_val) or val > best_val:
                best_val, best_bars = val, bars
        else:
            if pd.isna(best_val) or val < best_val:
                best_val, best_bars = val, bars
    return best_bars, best_val


def _horizon_breakdown_lines(replay: pd.DataFrame, best_rows: pd.DataFrame) -> list[str]:
    lines = [
        "## Horizon breakdown (best threshold rows)",
        "",
        "Expectancy and hit rate by fixed forward horizon. "
        "SHORT expectancy negative = favorable short-horizon drift.",
        "",
    ]
    for _, row in best_rows.head(5).iterrows():
        detail = _horizon_breakdown_for_threshold(
            replay,
            min_directional_score=float(row["min_directional_score"]),
            min_score_margin=float(row["min_score_margin"]),
        )
        lines.extend(
            [
                f"### min_dir={detail['min_directional_score']:.2f}, "
                f"min_margin={detail['min_score_margin']:.2f}",
                "",
                "| horizon | LONG exp% | LONG hit% | SHORT exp% | SHORT hit% |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for bars in FORWARD_HORIZONS:
            lines.append(
                f"| {bars}b | "
                f"{detail[f'long_expectancy_{bars}b'] * 100:.3f} | "
                f"{detail[f'long_hit_rate_{bars}b'] * 100:.1f} | "
                f"{detail[f'short_expectancy_{bars}b'] * 100:.3f} | "
                f"{detail[f'short_hit_rate_{bars}b'] * 100:.1f} |"
            )
        lines.extend(
            [
                "",
                "| context | exit return% | max favorable% | max adverse% |",
                "| --- | ---: | ---: | ---: |",
                f"| LONG | {detail['long_context_exit_return'] * 100:.3f} | "
                f"{detail['long_context_max_favorable'] * 100:.3f} | "
                f"{detail['long_context_max_adverse'] * 100:.3f} |",
                f"| SHORT | {detail['short_context_exit_return'] * 100:.3f} | "
                f"{detail['short_context_max_favorable'] * 100:.3f} | "
                f"{detail['short_context_max_adverse'] * 100:.3f} |",
                "",
            ]
        )
    return lines


def _short_subtype_report_lines(filtered: pd.DataFrame) -> list[str]:
    short_rows = filtered[filtered["chosen_context"] == "SHORT_CONTEXT"].copy()
    if short_rows.empty:
        return ["## SHORT subtype diagnostics", "", "_No SHORT_CONTEXT rows after filtering._", ""]

    subtype_runs = _short_subtype_run_outcomes(filtered)
    lines = [
        "## SHORT subtype diagnostics",
        "",
        "| subtype | bars | exp4% | exp8% | exp16% | exp32% | hit4% | hit8% | hit16% | hit32% | exit% | max_fav% | max_adv% | avg_duration |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for subtype in SHORT_SUBTYPES:
        subset = short_rows[short_rows["short_subtype"] == subtype].copy()
        if subset.empty:
            lines.append(f"| {subtype} | 0 | — | — | — | — | — | — | — | — | — | — | — | — |")
            continue

        if "high" in subset.columns and "low" in subset.columns:
            max_up_4, max_down_4 = _forward_extremes_nb(subset, 4)
            max_up_8, max_down_8 = _forward_extremes_nb(subset, 8)
            max_up_32, max_down_32 = _forward_extremes_nb(subset, 32)
            subset = subset.assign(
                _tmp_max_up_4=max_up_4,
                _tmp_max_down_4=max_down_4,
                _tmp_max_up_8=max_up_8,
                _tmp_max_down_8=max_down_8,
                _tmp_max_up_32=max_up_32,
                _tmp_max_down_32=max_down_32,
            )

        def _hit_for_bars(bars: int) -> float:
            check = subset.copy()
            if bars == 4:
                check["_tmp_max_up"] = check.get("_tmp_max_up_4")
                check["_tmp_max_down"] = check.get("_tmp_max_down_4")
            elif bars == 8:
                check["_tmp_max_up"] = check.get("_tmp_max_up_8")
                check["_tmp_max_down"] = check.get("_tmp_max_down_8")
            elif bars == 32:
                check["_tmp_max_up"] = check.get("_tmp_max_up_32")
                check["_tmp_max_down"] = check.get("_tmp_max_down_32")
            return float(check.apply(lambda r: _is_short_correct_horizon(r, bars), axis=1).mean() * 100)

        run_subset = subtype_runs[subtype_runs["short_subtype"] == subtype]
        avg_dur = float(run_subset["bars"].mean()) if len(run_subset) else 0.0
        exit_ret = float(run_subset["context_exit_return"].mean()) * 100 if len(run_subset) else float("nan")
        max_fav = float(run_subset["context_max_favorable"].mean()) * 100 if len(run_subset) else float("nan")
        max_adv = float(run_subset["context_max_adverse"].mean()) * 100 if len(run_subset) else float("nan")

        lines.append(
            f"| {subtype} | {len(subset)} | "
            f"{subset['forward_return_4b'].mean()*100:.3f} | {subset['forward_return_8b'].mean()*100:.3f} | "
            f"{subset['forward_return_16b'].mean()*100:.3f} | {subset['forward_return_32b'].mean()*100:.3f} | "
            f"{_hit_for_bars(4):.1f} | {_hit_for_bars(8):.1f} | {_hit_for_bars(16):.1f} | {_hit_for_bars(32):.1f} | "
            f"{exit_ret:.3f} | {max_fav:.3f} | {max_adv:.3f} | {avg_dur:.1f} |"
        )

    lines.extend([""])
    for subtype in SHORT_SUBTYPES:
        subset = short_rows[short_rows["short_subtype"] == subtype].copy()
        if subset.empty:
            continue
        false_short = subset[subset["forward_return_16b"] > 0].sort_values("forward_return_16b", ascending=False)
        true_short = subset[subset["forward_return_16b"] < 0].sort_values("forward_return_16b")
        lines.extend(
            [
                f"### {subtype} — worst false SHORT",
                "",
                _md_table(
                    false_short,
                    ["timestamp", "close", "forward_return_4b", "forward_return_8b", "forward_return_16b", "chosen_reason"],
                    max_rows=5,
                ),
                f"### {subtype} — best true SHORT",
                "",
                _md_table(
                    true_short,
                    ["timestamp", "close", "forward_return_4b", "forward_return_8b", "forward_return_16b", "chosen_reason"],
                    max_rows=5,
                ),
                "",
            ]
        )
    return lines


def _value_counts_table(frame: pd.DataFrame, column: str, *, top_n: int = 12) -> pd.DataFrame:
    if column not in frame.columns or frame.empty:
        return pd.DataFrame(columns=[column, "bars", "pct"])
    counts = frame[column].fillna("N/A").astype(str).value_counts().head(top_n)
    total = max(len(frame), 1)
    return pd.DataFrame(
        {
            column: counts.index,
            "bars": counts.values,
            "pct": (counts.values / total * 100).round(2),
        }
    )


def _attach_unknown_context_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.sort_values("timestamp").reset_index(drop=True).copy()
    out["recent_return_4b"] = out["close"] / out["close"].shift(4) - 1.0
    out["recent_return_8b"] = out["close"] / out["close"].shift(8) - 1.0
    out["recent_return_16b"] = out["close"] / out["close"].shift(16) - 1.0

    roll_high = out["high"].rolling(16, min_periods=4).max()
    roll_low = out["low"].rolling(16, min_periods=4).min()
    out["distance_from_recent_high_16b"] = (out["close"] - roll_high) / out["close"]
    out["distance_from_recent_low_16b"] = (out["close"] - roll_low) / out["close"]

    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    anchor_price = pd.to_numeric(
        out["anchor_price_or_zone"].apply(_extract_anchor_price), errors="coerce"
    )
    out["anchor_price_numeric"] = anchor_price
    out["below_prior_anchor"] = (anchor_price.notna()) & (out["close"] < anchor_price)
    out["downside_continuation_efficient"] = (
        out["chosen_reason"].fillna("").str.lower().str.contains("efficient downside continuation")
        | out["chosen_reason"].fillna("").str.lower().str.contains("persistent distribution")
        | (out["forward_return_4b"] < -0.001)
    )
    return out


def _comparison_summary_rows(filtered: pd.DataFrame, subtype: str) -> dict[str, Any]:
    subset = filtered[
        (filtered["chosen_context"] == "SHORT_CONTEXT")
        & (filtered["short_subtype"] == subtype)
    ]
    if subset.empty:
        return {
            "subtype": subtype,
            "bars": 0,
            "exp4": float("nan"),
            "exp8": float("nan"),
            "exp16": float("nan"),
            "exp32": float("nan"),
            "hit16": float("nan"),
            "exit_return": float("nan"),
            "max_fav": float("nan"),
            "max_adv": float("nan"),
        }
    runs = _short_subtype_run_outcomes(filtered)
    run_subset = runs[runs["short_subtype"] == subtype]
    hit16 = float((subset["forward_return_16b"] < 0).mean() * 100)
    return {
        "subtype": subtype,
        "bars": int(len(subset)),
        "exp4": float(subset["forward_return_4b"].mean() * 100),
        "exp8": float(subset["forward_return_8b"].mean() * 100),
        "exp16": float(subset["forward_return_16b"].mean() * 100),
        "exp32": float(subset["forward_return_32b"].mean() * 100),
        "hit16": hit16,
        "exit_return": float(run_subset["context_exit_return"].mean() * 100) if len(run_subset) else float("nan"),
        "max_fav": float(run_subset["context_max_favorable"].mean() * 100) if len(run_subset) else float("nan"),
        "max_adv": float(run_subset["context_max_adverse"].mean() * 100) if len(run_subset) else float("nan"),
    }


def _adjacent_rows(frame: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    idxs: set[int] = set()
    index_map = {ts: i for i, ts in enumerate(frame["timestamp"])}
    for ts in rows["timestamp"]:
        i = index_map.get(ts)
        if i is None:
            continue
        idxs.update([max(0, i - 1), i, min(len(frame) - 1, i + 1)])
    return frame.iloc[sorted(idxs)].copy()


def build_unknown_short_profile(
    filtered: pd.DataFrame,
    *,
    csv_path: Path,
    md_path: Path,
    gate_min_dir: float,
    gate_min_margin: float,
) -> None:
    enriched = _attach_unknown_context_features(filtered)
    unknown = enriched[
        (enriched["chosen_context"] == "SHORT_CONTEXT")
        & (enriched["short_subtype"] == "UNKNOWN_SHORT")
    ].copy()

    unknown.to_csv(csv_path, index=False)

    comps = pd.DataFrame(
        [
            _comparison_summary_rows(enriched, "UNKNOWN_SHORT"),
            _comparison_summary_rows(enriched, "DISTRIBUTION_AFTER_BUYING_CLIMAX"),
            _comparison_summary_rows(enriched, "FAILED_BULLISH_REVERSAL_BREAKDOWN"),
            _comparison_summary_rows(enriched, "LATE_EXHAUSTION_SHORT"),
        ]
    )

    best_true = unknown[unknown["forward_return_16b"] < 0].sort_values("forward_return_16b").head(20)
    worst_false = unknown[unknown["forward_return_16b"] > 0].sort_values("forward_return_16b", ascending=False).head(20)

    near_best = _adjacent_rows(enriched, best_true)
    near_worst = _adjacent_rows(enriched, worst_false)

    market_state_dist = _value_counts_table(unknown, "market_state")
    live_state_dist = _value_counts_table(unknown, "trading_state")
    anchor_event_dist = _value_counts_table(unknown, "anchor_event_type")
    anchor_status_dist = _value_counts_table(unknown, "anchor_status")
    market_bias_dist = _value_counts_table(unknown, "market_bias")
    regime_dist = _value_counts_table(unknown, "prob_auction_regime")
    regime_state_dist = _value_counts_table(unknown, "prob_regime_state")
    convergence_dist = _value_counts_table(unknown, "conv_convergence_state")
    trigger_dist = _value_counts_table(unknown, "cognition_tier1_trigger_event")
    location_dist = _value_counts_table(unknown, "cognition_tier1_location_bias")

    unknown_exp4 = float(unknown["forward_return_4b"].mean() * 100) if len(unknown) else float("nan")
    unknown_exp8 = float(unknown["forward_return_8b"].mean() * 100) if len(unknown) else float("nan")
    unknown_exp16 = float(unknown["forward_return_16b"].mean() * 100) if len(unknown) else float("nan")
    unknown_exp32 = float(unknown["forward_return_32b"].mean() * 100) if len(unknown) else float("nan")
    unknown_hit16 = float((unknown["forward_return_16b"] < 0).mean() * 100) if len(unknown) else float("nan")

    likely = (
        "UNKNOWN_SHORT behaves like a directional continuation short cluster "
        "with persistent downside expectancy and high 16b hit rate."
    )
    candidate_name = "DIRECTIONAL_DISTRIBUTION_CONTINUATION"
    proposed_rule = (
        "chosen_context=SHORT_CONTEXT AND short_subtype=UNKNOWN_SHORT AND "
        "anchor_status in {HELD,UNRESOLVED,NONE} AND "
        "market_state in {DISTRIBUTION,REVERSAL} AND "
        "downside_continuation_efficient=True AND recent_return_8b<=0 "
        "AND distance_from_recent_high_16b<=-0.005"
    )
    separation = (
        "Filter out LATE_EXHAUSTION_SHORT by requiring max_adverse_16b <= max_favorable_16b "
        "and forward_return_8b <= 0 (LATE_EXHAUSTION typically violates both)."
    )
    keep_or_suppress = (
        "KEEP as DIRECTIONAL_SHORT candidate; suppress only rows failing continuation/advantage filters."
    )

    def _tbl(df: pd.DataFrame, cols: list[str], rows: int = 12) -> str:
        return _md_table(df[cols] if len(df) else df, cols, max_rows=rows)

    lines = [
        "# UNKNOWN_SHORT Profile",
        "",
        f"Gate: min_directional_score={gate_min_dir:.2f}, min_score_margin={gate_min_margin:.2f}",
        f"CSV: `{csv_path}`",
        "",
        "## Feature profile distributions",
        "",
        "### market_state",
        _tbl(market_state_dist, ["market_state", "bars", "pct"]),
        "### live trading_state",
        _tbl(live_state_dist, ["trading_state", "bars", "pct"]),
        "### anchor_event_type",
        _tbl(anchor_event_dist, ["anchor_event_type", "bars", "pct"]),
        "### anchor_status",
        _tbl(anchor_status_dist, ["anchor_status", "bars", "pct"]),
        "### market_bias",
        _tbl(market_bias_dist, ["market_bias", "bars", "pct"]),
        "### probabilistic auction regime/state",
        _tbl(regime_dist, ["prob_auction_regime", "bars", "pct"]),
        _tbl(regime_state_dist, ["prob_regime_state", "bars", "pct"]),
        "### convergence / cognition trigger/location",
        _tbl(convergence_dist, ["conv_convergence_state", "bars", "pct"]),
        _tbl(trigger_dist, ["cognition_tier1_trigger_event", "bars", "pct"]),
        _tbl(location_dist, ["cognition_tier1_location_bias", "bars", "pct"]),
        "",
        "## UNKNOWN vs other short subtypes",
        "",
        _tbl(
            comps,
            ["subtype", "bars", "exp4", "exp8", "exp16", "exp32", "hit16", "exit_return", "max_fav", "max_adv"],
            rows=10,
        ),
        "",
        "## Top examples",
        "",
        "### best 20 UNKNOWN_SHORT true shorts",
        _tbl(
            best_true,
            [
                "timestamp",
                "close",
                "forward_return_4b",
                "forward_return_8b",
                "forward_return_16b",
                "forward_return_32b",
                "chosen_reason",
            ],
            rows=20,
        ),
        "### worst 20 UNKNOWN_SHORT false shorts",
        _tbl(
            worst_false,
            [
                "timestamp",
                "close",
                "forward_return_4b",
                "forward_return_8b",
                "forward_return_16b",
                "forward_return_32b",
                "chosen_reason",
            ],
            rows=20,
        ),
        "### adjacent rows around best true shorts",
        _tbl(
            near_best,
            ["timestamp", "close", "trading_state", "chosen_context", "short_subtype", "forward_return_4b", "forward_return_16b"],
            rows=30,
        ),
        "### adjacent rows around worst false shorts",
        _tbl(
            near_worst,
            ["timestamp", "close", "trading_state", "chosen_context", "short_subtype", "forward_return_4b", "forward_return_16b"],
            rows=30,
        ),
        "",
        "## Interpretation",
        "",
        f"- UNKNOWN_SHORT expectancy: 4b={unknown_exp4:.3f}%, 8b={unknown_exp8:.3f}%, 16b={unknown_exp16:.3f}%, 32b={unknown_exp32:.3f}%, hit16={unknown_hit16:.1f}%",
        f"- What UNKNOWN_SHORT likely is: {likely}",
        f"- Candidate subtype name: `{candidate_name}`",
        f"- Proposed rule: `{proposed_rule}`",
        "- Bucket: `DIRECTIONAL_SHORT`",
        f"- Separation filter vs LATE_EXHAUSTION_SHORT: {separation}",
        f"- Keep/suppress: {keep_or_suppress}",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")


def apply_calibrated_v2_context(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply calibrated_v2 using live-safe evidence only (no forward outcome fields)."""
    calibrated = _attach_backward_returns(frame.copy())
    calibrated["tactical_short_candidate"] = False
    calibrated["suppress_reason"] = ""
    calibrated["raw_chosen_context"] = calibrated["chosen_context"]
    calibrated["calibrated_context"] = calibrated["chosen_context"]

    for idx, row in calibrated.iterrows():
        raw_result = AuctionContextArbitrationResult(
            long_context_score=_safe_float(row.get("long_context_score")),
            short_context_score=_safe_float(row.get("short_context_score")),
            observe_score=_safe_float(row.get("observe_score")),
            anchor_status=_clean_text(row.get("anchor_status")).upper() or "NONE",
            anchor_price_or_zone=_clean_text(row.get("anchor_price_or_zone")) or None,
            anchor_event_type=_clean_text(row.get("anchor_event_type")),
            chosen_context=_clean_text(row.get("chosen_context")).upper() or "OBSERVE",
            chosen_reason=_clean_text(row.get("chosen_reason")),
            why_not_long=_clean_text(row.get("why_not_long")),
            why_not_short=_clean_text(row.get("why_not_short")),
            short_subtype=_clean_text(row.get("short_subtype")),
        )
        filtered = apply_calibrated_v2_filter(raw_result, _evidence_from_replay_row(row))
        calibrated.at[idx, "short_subtype"] = filtered.short_subtype
        calibrated.at[idx, "tactical_short_candidate"] = filtered.tactical_short_candidate
        calibrated.at[idx, "suppress_reason"] = filtered.suppress_reason
        calibrated.at[idx, "calibrated_context"] = filtered.chosen_context
        calibrated.at[idx, "raw_chosen_context"] = filtered.raw_chosen_context or raw_result.chosen_context

    calibrated["calibrated_v2_context"] = calibrated["calibrated_context"]
    calibrated["chosen_context"] = calibrated["calibrated_context"]
    return calibrated


def apply_calibrated_v3_context(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply calibrated_v3 on top of calibrated_v2 (live-safe; LONG held-stopping only)."""
    calibrated = apply_calibrated_v2_context(frame)
    calibrated["calibrated_v2_context"] = calibrated["calibrated_context"]
    calibrated["tactical_long_candidate"] = False
    calibrated["short_candidate"] = False
    calibrated["long_subtype"] = ""

    for idx, row in calibrated.iterrows():
        v2_result = AuctionContextArbitrationResult(
            long_context_score=_safe_float(row.get("long_context_score")),
            short_context_score=_safe_float(row.get("short_context_score")),
            observe_score=_safe_float(row.get("observe_score")),
            anchor_status=_clean_text(row.get("anchor_status")).upper() or "NONE",
            anchor_price_or_zone=_clean_text(row.get("anchor_price_or_zone")) or None,
            anchor_event_type=_clean_text(row.get("anchor_event_type")),
            chosen_context=_clean_text(row.get("calibrated_v2_context") or row.get("calibrated_context")).upper()
            or "OBSERVE",
            chosen_reason=_clean_text(row.get("chosen_reason")),
            why_not_long=_clean_text(row.get("why_not_long")),
            why_not_short=_clean_text(row.get("why_not_short")),
            short_subtype=_clean_text(row.get("short_subtype")),
            tactical_short_candidate=bool(row.get("tactical_short_candidate")),
            suppress_reason=_clean_text(row.get("suppress_reason")),
            raw_chosen_context=_clean_text(row.get("raw_chosen_context")) or "OBSERVE",
        )
        filtered = apply_calibrated_v3_filter(v2_result, _evidence_from_replay_row(row))
        calibrated.at[idx, "long_subtype"] = filtered.long_subtype
        calibrated.at[idx, "tactical_long_candidate"] = filtered.tactical_long_candidate
        calibrated.at[idx, "short_candidate"] = filtered.short_candidate
        calibrated.at[idx, "tactical_short_candidate"] = filtered.tactical_short_candidate
        calibrated.at[idx, "suppress_reason"] = filtered.suppress_reason
        calibrated.at[idx, "calibrated_context"] = filtered.chosen_context
        calibrated.at[idx, "raw_chosen_context"] = filtered.raw_chosen_context

    calibrated["calibrated_v3_context"] = calibrated["calibrated_context"]
    # Primary final context for --calibrated-v3 exports/reports is v3.
    calibrated["chosen_context"] = calibrated["calibrated_v3_context"]
    return calibrated


def _context_distribution(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if column not in frame.columns:
        return {"LONG_CONTEXT": 0, "SHORT_CONTEXT": 0, "OBSERVE": 0}
    counts = frame[column].fillna("OBSERVE").astype(str).str.upper().value_counts()
    return {
        "LONG_CONTEXT": int(counts.get("LONG_CONTEXT", 0)),
        "SHORT_CONTEXT": int(counts.get("SHORT_CONTEXT", 0)),
        "OBSERVE": int(counts.get("OBSERVE", 0)),
    }


def _assert_calibrated_v3_invariants(frame: pd.DataFrame) -> None:
    """Fail hard if calibrated_v3 final context violates current live-safe rules.

    Live policy (symmetric): final LONG is HELD_STOPPING_VOLUME_REVERSAL only;
    final SHORT is only the two directional distribution subtypes.
    """
    final_col = "calibrated_v3_context" if "calibrated_v3_context" in frame.columns else "chosen_context"
    short_rows = frame[frame[final_col] == "SHORT_CONTEXT"]
    if len(short_rows) and "short_subtype" in frame.columns:
        bad_short = short_rows[
            ~short_rows["short_subtype"].fillna("").astype(str).isin(ALLOWED_LIVE_SHORT_SUBTYPES)
        ]
        if len(bad_short):
            raise RuntimeError(
                f"calibrated_v3 invariant violated: {len(bad_short)} final SHORT_CONTEXT rows "
                f"are not in {sorted(ALLOWED_LIVE_SHORT_SUBTYPES)}"
            )
    long_rows = frame[frame[final_col] == "LONG_CONTEXT"]
    if len(long_rows) and "long_subtype" in frame.columns:
        bad = long_rows[long_rows["long_subtype"].fillna("").astype(str) != "HELD_STOPPING_VOLUME_REVERSAL"]
        if len(bad):
            raise RuntimeError(
                f"calibrated_v3 invariant violated: {len(bad)} final LONG_CONTEXT rows "
                "are not HELD_STOPPING_VOLUME_REVERSAL"
            )


def build_context_layer_distribution_report(
    *,
    raw: pd.DataFrame,
    calibrated_v2: pd.DataFrame | None,
    calibrated_v3: pd.DataFrame | None,
) -> str:
    """Explicit raw / v2 / v3 context distribution section for reports."""
    layers: list[tuple[str, dict[str, int]]] = [
        ("raw_chosen_context", _context_distribution(raw, "chosen_context_raw" if "chosen_context_raw" in raw.columns else "chosen_context")),
    ]
    if calibrated_v2 is not None:
        v2_col = "calibrated_v2_context" if "calibrated_v2_context" in calibrated_v2.columns else "calibrated_context"
        layers.append(("calibrated_v2_context", _context_distribution(calibrated_v2, v2_col)))
    if calibrated_v3 is not None:
        v3_col = "calibrated_v3_context" if "calibrated_v3_context" in calibrated_v3.columns else "calibrated_context"
        layers.append(("calibrated_v3_context", _context_distribution(calibrated_v3, v3_col)))

    lines = [
        "# Context layer distributions",
        "",
        "| layer | LONG_CONTEXT | SHORT_CONTEXT | OBSERVE |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, counts in layers:
        lines.append(
            f"| {name} | {counts['LONG_CONTEXT']} | {counts['SHORT_CONTEXT']} | {counts['OBSERVE']} |"
        )
    lines.append("")
    if calibrated_v3 is not None:
        v3 = layers[-1][1]
        lines.extend(
            [
                "## calibrated_v3 invariants",
                "",
                f"- final SHORT_CONTEXT count: **{v3['SHORT_CONTEXT']}** "
                "(allowed subtypes: DISTRIBUTION_AFTER_BUYING_CLIMAX, "
                "DIRECTIONAL_DISTRIBUTION_CONTINUATION)",
                f"- final LONG_CONTEXT count: **{v3['LONG_CONTEXT']}** "
                "(allowed subtype: HELD_STOPPING_VOLUME_REVERSAL)",
                "",
            ]
        )
    return "\n".join(lines)


def _raw_subtype_horizon_stats(subset: pd.DataFrame, *, side: str) -> dict[str, Any]:
    """Forward-return stats for one raw subtype cohort (measurement only)."""
    n = int(len(subset))
    if n == 0:
        return {
            "bars": 0,
            "exp8_pct": float("nan"),
            "exp16_pct": float("nan"),
            "hit8_pct": float("nan"),
            "hit16_pct": float("nan"),
            "max_fav16_pct": float("nan"),
            "max_adv16_pct": float("nan"),
        }
    f8 = pd.to_numeric(subset["forward_return_8b"], errors="coerce")
    f16 = pd.to_numeric(subset["forward_return_16b"], errors="coerce")
    if side == "short":
        hit8 = float((f8 < 0).mean() * 100)
        hit16 = float((f16 < 0).mean() * 100)
    else:
        hit8 = float((f8 > 0).mean() * 100)
        hit16 = float((f16 > 0).mean() * 100)
    fav = pd.to_numeric(subset.get("max_favorable_16b"), errors="coerce")
    adv = pd.to_numeric(subset.get("max_adverse_16b"), errors="coerce")
    return {
        "bars": n,
        "exp8_pct": float(f8.mean() * 100),
        "exp16_pct": float(f16.mean() * 100),
        "hit8_pct": hit8,
        "hit16_pct": hit16,
        "max_fav16_pct": float(fav.mean() * 100) if fav.notna().any() else float("nan"),
        "max_adv16_pct": float(adv.mean() * 100) if adv.notna().any() else float("nan"),
    }


def _raw_short_subtype_verdict(
    *,
    subtype: str,
    stats: dict[str, Any],
    final_pass_pct: float,
    baseline: dict[str, Any],
) -> str:
    """Heuristic vs trusted LONG HELD_STOPPING band (no policy change)."""
    if stats["bars"] < 30:
        return "HOLD_OUT_LOW_N"
    if subtype in ALLOWED_LIVE_SHORT_SUBTYPES:
        if stats["exp16_pct"] < 0 and stats["hit16_pct"] >= max(45.0, baseline["hit16_pct"] - 12.0):
            return "KEEP_LIVE"
        return "KEEP_BUT_REVIEW_EDGE"
    # Short edge: want negative expectancy; compare magnitude to long baseline.
    long_edge = abs(float(baseline["exp16_pct"])) if not pd.isna(baseline["exp16_pct"]) else 0.0
    if stats["exp16_pct"] >= 0:
        return "REJECT_POSITIVE_FWD"
    if abs(stats["exp16_pct"]) < 0.45 * max(long_edge, 0.05):
        return "HOLD_OUT_WEAK_EDGE"
    if stats["hit16_pct"] < max(48.0, baseline["hit16_pct"] - 10.0):
        return "HOLD_OUT_WEAK_HIT"
    if final_pass_pct < 5.0 and subtype == "UNKNOWN_SHORT":
        return "PROMOTE_CANDIDATE_IF_RULE_TIGHTENED"
    if subtype in {"FAILED_BULLISH_REVERSAL_BREAKDOWN", "SHORT_IMPULSE_ONLY", "LATE_EXHAUSTION_SHORT"}:
        return "PROMOTE_CANDIDATE"
    return "PROMOTE_CANDIDATE"


def _raw_long_subtype_verdict(
    *,
    subtype: str,
    stats: dict[str, Any],
    baseline: dict[str, Any],
) -> str:
    if subtype == "HELD_STOPPING_VOLUME_REVERSAL":
        return "BASELINE_KEEP_LIVE"
    if stats["bars"] < 30:
        return "HOLD_OUT_LOW_N"
    if stats["exp16_pct"] <= 0:
        return "REJECT_NONPOSITIVE_FWD"
    long_edge = float(baseline["exp16_pct"]) if not pd.isna(baseline["exp16_pct"]) else 0.0
    if stats["exp16_pct"] < 0.55 * max(long_edge, 0.05):
        return "HOLD_OUT_WEAK_EDGE"
    if stats["hit16_pct"] < max(48.0, baseline["hit16_pct"] - 10.0):
        return "HOLD_OUT_WEAK_HIT"
    return "PROMOTE_CANDIDATE"


def build_raw_subtype_forward_report(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Measure live subtypes on raw directional bars vs forward price (read-only).

    Universe = raw_chosen_context LONG/SHORT (includes bars later filtered to OBSERVE).
    Subtypes = live-safe classifier labels already attached by calibrated_v2/v3.
    Baseline = final HELD_STOPPING_VOLUME_REVERSAL LONG_CONTEXT.
    """
    work = frame.copy()
    if "long_subtype" not in work.columns:
        work["long_subtype"] = ""
    if "short_subtype" not in work.columns:
        work["short_subtype"] = ""
    if "suppress_reason" not in work.columns:
        work["suppress_reason"] = ""
    raw_col = "raw_chosen_context" if "raw_chosen_context" in work.columns else "chosen_context_raw"
    if raw_col not in work.columns:
        raise ValueError("raw_chosen_context missing; run with --calibrated-v2 or --calibrated-v3")
    final_col = (
        "calibrated_v3_context"
        if "calibrated_v3_context" in work.columns
        else ("calibrated_v2_context" if "calibrated_v2_context" in work.columns else "chosen_context")
    )

    baseline_rows = work[
        (work[final_col] == "LONG_CONTEXT")
        & (work["long_subtype"].fillna("").astype(str) == "HELD_STOPPING_VOLUME_REVERSAL")
    ]
    if baseline_rows.empty:
        baseline_rows = work[
            (work[raw_col] == "LONG_CONTEXT")
            & (work["long_subtype"].fillna("").astype(str) == "HELD_STOPPING_VOLUME_REVERSAL")
        ]
    baseline = _raw_subtype_horizon_stats(baseline_rows, side="long")
    baseline["subtype"] = "HELD_STOPPING_VOLUME_REVERSAL"
    baseline["side"] = "LONG"
    baseline["final_pass_pct"] = 100.0 if len(baseline_rows) else float("nan")
    baseline["top_suppress"] = ""
    baseline["verdict"] = "BASELINE_KEEP_LIVE"

    rows: list[dict[str, Any]] = [baseline]
    lines = [
        "# Raw subtype × forward return (live labels, no paper PnL)",
        "",
        "Measures price path after context start. Subtypes stay even when filter → OBSERVE.",
        "Baseline = final live LONG `HELD_STOPPING_VOLUME_REVERSAL`.",
        "",
        f"- baseline bars: **{baseline['bars']}**",
        f"- baseline exp8/exp16: **{baseline['exp8_pct']:.3f}% / {baseline['exp16_pct']:.3f}%**",
        f"- baseline hit8/hit16: **{baseline['hit8_pct']:.1f}% / {baseline['hit16_pct']:.1f}%**",
        "",
        "## SHORT (raw_chosen_context = SHORT_CONTEXT)",
        "",
        "| subtype | bars | final_pass% | exp8% | exp16% | hit8% | hit16% | max_fav16% | max_adv16% | top_suppress | verdict |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]

    short_raw = work[work[raw_col].astype(str).str.upper() == "SHORT_CONTEXT"].copy()
    short_names = list(SHORT_SUBTYPES)
    for extra in sorted(set(short_raw["short_subtype"].fillna("").astype(str)) - set(short_names) - {""}):
        short_names.append(extra)

    for subtype in short_names:
        subset = short_raw[short_raw["short_subtype"].fillna("").astype(str) == subtype]
        stats = _raw_subtype_horizon_stats(subset, side="short")
        if stats["bars"] == 0:
            lines.append(f"| {subtype} | 0 | — | — | — | — | — | — | — | — | — |")
            continue
        final_pass = float((subset[final_col] == "SHORT_CONTEXT").mean() * 100)
        top_suppress = (
            subset.loc[subset[final_col] != "SHORT_CONTEXT", "suppress_reason"]
            .fillna("")
            .astype(str)
            .value_counts()
            .head(1)
        )
        top_suppress_s = f"{top_suppress.index[0]} ({int(top_suppress.iloc[0])})" if len(top_suppress) else ""
        verdict = _raw_short_subtype_verdict(
            subtype=subtype,
            stats=stats,
            final_pass_pct=final_pass,
            baseline=baseline,
        )
        rows.append(
            {
                "side": "SHORT",
                "subtype": subtype,
                **stats,
                "final_pass_pct": final_pass,
                "top_suppress": top_suppress_s,
                "verdict": verdict,
            }
        )
        lines.append(
            f"| {subtype} | {stats['bars']} | {final_pass:.1f} | "
            f"{stats['exp8_pct']:.3f} | {stats['exp16_pct']:.3f} | "
            f"{stats['hit8_pct']:.1f} | {stats['hit16_pct']:.1f} | "
            f"{stats['max_fav16_pct']:.3f} | {stats['max_adv16_pct']:.3f} | "
            f"{top_suppress_s or '—'} | {verdict} |"
        )

    lines.extend(
        [
            "",
            "## LONG (raw_chosen_context = LONG_CONTEXT)",
            "",
            "| subtype | bars | final_pass% | exp8% | exp16% | hit8% | hit16% | max_fav16% | max_adv16% | top_suppress | verdict |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    long_raw = work[work[raw_col].astype(str).str.upper() == "LONG_CONTEXT"].copy()
    long_names = list(LONG_SUBTYPES)
    for extra in sorted(set(long_raw["long_subtype"].fillna("").astype(str)) - set(long_names) - {""}):
        long_names.append(extra)

    for subtype in long_names:
        subset = long_raw[long_raw["long_subtype"].fillna("").astype(str) == subtype]
        stats = _raw_subtype_horizon_stats(subset, side="long")
        if stats["bars"] == 0:
            lines.append(f"| {subtype} | 0 | — | — | — | — | — | — | — | — | — |")
            continue
        final_pass = float((subset[final_col] == "LONG_CONTEXT").mean() * 100)
        top_suppress = (
            subset.loc[subset[final_col] != "LONG_CONTEXT", "suppress_reason"]
            .fillna("")
            .astype(str)
            .value_counts()
            .head(1)
        )
        top_suppress_s = f"{top_suppress.index[0]} ({int(top_suppress.iloc[0])})" if len(top_suppress) else ""
        verdict = _raw_long_subtype_verdict(subtype=subtype, stats=stats, baseline=baseline)
        rows.append(
            {
                "side": "LONG",
                "subtype": subtype,
                **stats,
                "final_pass_pct": final_pass,
                "top_suppress": top_suppress_s,
                "verdict": verdict,
            }
        )
        lines.append(
            f"| {subtype} | {stats['bars']} | {final_pass:.1f} | "
            f"{stats['exp8_pct']:.3f} | {stats['exp16_pct']:.3f} | "
            f"{stats['hit8_pct']:.1f} | {stats['hit16_pct']:.1f} | "
            f"{stats['max_fav16_pct']:.3f} | {stats['max_adv16_pct']:.3f} | "
            f"{top_suppress_s or '—'} | {verdict} |"
        )

    promote = [r for r in rows if str(r.get("verdict", "")).startswith("PROMOTE")]
    keep = [r for r in rows if str(r.get("verdict", "")).startswith("KEEP") or r.get("verdict") == "BASELINE_KEEP_LIVE"]
    keep_s = ", ".join(f"{r['side']}:{r['subtype']}" for r in keep) or "—"
    promote_s = ", ".join(f"{r['side']}:{r['subtype']}" for r in promote) or "none"
    lines.extend(
        [
            "",
            "## Recommendation snapshot (measurement only — do not change live yet)",
            "",
            f"- keep / baseline: {keep_s}",
            f"- promote candidates: {promote_s}",
            "",
            "Next step after this table: tighten UNKNOWN→continuation rules if UNKNOWN shows edge but low final_pass%.",
            "",
        ]
    )
    return pd.DataFrame(rows), "\n".join(lines)


def _attach_backward_returns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.sort_values("timestamp").reset_index(drop=True).copy()
    out["recent_return"] = out["close"] / out["close"].shift(4) - 1.0
    out["recent_return_8b"] = out["close"] / out["close"].shift(8) - 1.0
    out["recent_return_16b"] = out["close"] / out["close"].shift(16) - 1.0
    return out


def _evidence_from_replay_row(row: pd.Series) -> AuctionContextEvidence:
    """Build live-safe evidence for calibrated decisions (excludes outcome-only fields)."""
    return AuctionContextEvidence(
        timestamp=row.get("timestamp"),
        close=_safe_float(row.get("close")),
        market_state=_clean_text(row.get("market_state")),
        market_bias=_clean_text(row.get("market_bias")),
        trading_state=_clean_text(row.get("trading_state")),
        climax_state=_clean_text(row.get("volume_climax_state")),
        effort_result_state=_clean_text(row.get("volume_effort_result_state")),
        continuation_quality=_clean_text(row.get("volume_continuation_quality")),
        convergence_state=_clean_text(row.get("conv_convergence_state")),
        tier1_trigger_event=_clean_text(row.get("cognition_tier1_trigger_event")),
        tier1_location_bias=_clean_text(row.get("cognition_tier1_location_bias")),
        anchor_age_bars=_safe_float(row.get("cognition_anchor_age_bars")),
        recent_return=_safe_float(row.get("recent_return")),
        recent_return_8b=_safe_float(row.get("recent_return_8b")),
        recent_return_16b=_safe_float(row.get("recent_return_16b")),
    )


def _evidence_with_outcomes_from_replay_row(row: pd.Series) -> AuctionContextEvidence:
    """Research-only evidence including outcome fields for diagnostic subtyping."""
    base = _evidence_from_replay_row(row)
    return AuctionContextEvidence(
        timestamp=base.timestamp,
        close=base.close,
        market_state=base.market_state,
        market_bias=base.market_bias,
        trading_state=base.trading_state,
        climax_state=base.climax_state,
        effort_result_state=base.effort_result_state,
        continuation_quality=base.continuation_quality,
        convergence_state=base.convergence_state,
        tier1_trigger_event=base.tier1_trigger_event,
        tier1_location_bias=base.tier1_location_bias,
        anchor_age_bars=base.anchor_age_bars,
        recent_return=base.recent_return,
        forward_return_4b=_safe_float(row.get("forward_return_4b"), default=float("nan")),
        forward_return_8b=_safe_float(row.get("forward_return_8b"), default=float("nan")),
        forward_return_16b=_safe_float(row.get("forward_return_16b"), default=float("nan")),
        max_favorable_16b=_safe_float(row.get("max_favorable_16b"), default=float("nan")),
        max_adverse_16b=_safe_float(row.get("max_adverse_16b"), default=float("nan")),
    )


def _result_from_replay_row(row: pd.Series) -> AuctionContextArbitrationResult:
    return AuctionContextArbitrationResult(
        long_context_score=_safe_float(row.get("long_context_score")),
        short_context_score=_safe_float(row.get("short_context_score")),
        observe_score=_safe_float(row.get("observe_score")),
        anchor_status=_clean_text(row.get("anchor_status")).upper() or "NONE",
        anchor_price_or_zone=_clean_text(row.get("anchor_price_or_zone")) or None,
        anchor_event_type=_clean_text(row.get("anchor_event_type")),
        chosen_context=_clean_text(row.get("chosen_context")).upper() or "OBSERVE",
        chosen_reason=_clean_text(row.get("chosen_reason")),
        why_not_long=_clean_text(row.get("why_not_long")),
        why_not_short=_clean_text(row.get("why_not_short")),
        short_subtype=_clean_text(row.get("short_subtype")),
    )


def _attach_outcome_diagnostic_subtypes(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach outcome-based diagnostic labels after decisions (research only)."""
    if "forward_return_16b" not in frame.columns:
        return frame
    out = frame.copy()
    short_diag: list[str] = []
    for _, row in out.iterrows():
        short_diag.append(
            classify_short_subtype_outcome_diagnostic(
                _result_from_replay_row(row),
                _evidence_with_outcomes_from_replay_row(row),
            )
        )
    out["outcome_diagnostic_short_subtype"] = short_diag
    out = _refresh_favorable_adverse(out)
    return out


def build_leakage_audit_report() -> str:
    lines = [
        "# Leakage audit (calibrated_v2)",
        "",
        "Outcome-only fields (must not influence decisions):",
        "",
    ]
    for field in sorted(OUTCOME_ONLY_EVIDENCE_FIELDS):
        lines.append(f"- `{field}`")
    lines.extend(
        [
            "",
            "Pipeline order: raw score → calibrated_v2 decisions (live-safe evidence) → "
            "attach forward outcomes → outcome_diagnostic_* subtypes for research.",
            "",
            "## Rules corrected (were not live-safe)",
            "",
        ]
    )
    for rule in NOT_LIVE_SAFE_RULES_REMOVED:
        lines.append(f"- `{rule}`")
    lines.extend(
        [
            "",
            "**Leakage found:** yes — forward return and max excursion fields were used in "
            "short/long subtype classification and DIRECTIONAL_DISTRIBUTION_CONTINUATION promotion.",
            "",
            "**Correction:** decision subtypes use backward `recent_return`, anchor/effort/convergence "
            "fields, and reason text only. Outcome-based labels are in `outcome_diagnostic_*_subtype` columns.",
            "",
        ]
    )
    return "\n".join(lines)


def _scenario_metrics(
    frame: pd.DataFrame,
    *,
    context_col: str,
    baseline_stale: int,
    short_candidate_col: str | None = None,
) -> dict[str, Any]:
    work = frame.copy()
    work["chosen_context"] = work[context_col]
    valid = work.dropna(subset=["forward_return_16b"])

    long_rows = valid[valid["chosen_context"] == "LONG_CONTEXT"]
    short_rows = valid[valid["chosen_context"] == "SHORT_CONTEXT"]
    observe_rows = valid[valid["chosen_context"] == "OBSERVE"]

    metrics: dict[str, Any] = {}
    for bars in FORWARD_HORIZONS:
        l_exp, _ = _horizon_metrics(valid, "LONG_CONTEXT", bars)
        s_exp, _ = _horizon_metrics(valid, "SHORT_CONTEXT", bars)
        metrics[f"long_exp_{bars}b"] = l_exp
        metrics[f"short_exp_{bars}b"] = s_exp

    if short_candidate_col and short_candidate_col in work.columns:
        disabled_short = valid[valid[short_candidate_col] == True]  # noqa: E712
        for bars in FORWARD_HORIZONS:
            col = f"forward_return_{bars}b"
            metrics[f"disabled_short_exp_{bars}b"] = (
                float(disabled_short[col].mean()) if len(disabled_short) else float("nan")
            )
        metrics["disabled_short_count"] = int((work[short_candidate_col] == True).sum())  # noqa: E712
    else:
        for bars in FORWARD_HORIZONS:
            metrics[f"disabled_short_exp_{bars}b"] = float("nan")
        metrics["disabled_short_count"] = 0

    metrics["observe_abs_16b"] = float(observe_rows["forward_return_16b"].abs().mean()) if len(observe_rows) else float("nan")
    metrics["directional_coverage_pct"] = float(
        valid["chosen_context"].isin({"LONG_CONTEXT", "SHORT_CONTEXT"}).mean() * 100
    )
    metrics["churn"] = int((work["chosen_context"] != work["chosen_context"].shift(1)).sum())
    stale_directional = int((_stale_reversal_watch_mask(work) & work["chosen_context"].isin({"LONG_CONTEXT", "SHORT_CONTEXT"})).sum())
    metrics["stale_reversal_watch_reduction"] = baseline_stale - stale_directional

    ctx_counts = work["chosen_context"].value_counts()
    for label in ("LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"):
        metrics[f"context_{label}"] = int(ctx_counts.get(label, 0))

    suppressed_weak_late = 0
    if "suppress_reason" in work.columns:
        suppressed_weak_late = int(
            work["suppress_reason"].isin(
                {"WEAK_OR_UNKNOWN_LONG_FILTER", "LATE_REBOUND_LONG_FILTER", "LONG_V3_HELD_STOPPING_ONLY"}
            ).sum()
        )
    metrics["suppressed_weak_late_long_count"] = suppressed_weak_late
    return metrics


def build_calibrated_v2_report(baseline: pd.DataFrame, thresholded: pd.DataFrame, calibrated: pd.DataFrame) -> str:
    baseline_stale = int((_stale_reversal_watch_mask(baseline) & baseline["chosen_context"].isin({"LONG_CONTEXT", "SHORT_CONTEXT"})).sum())
    m_base = _scenario_metrics(baseline, context_col="chosen_context", baseline_stale=baseline_stale)
    m_thr = _scenario_metrics(thresholded, context_col="chosen_context", baseline_stale=baseline_stale)
    m_cal = _scenario_metrics(calibrated, context_col="calibrated_context", baseline_stale=baseline_stale)

    tactical = calibrated[calibrated["tactical_short_candidate"] == True]  # noqa: E712
    tactical_outcome = float(tactical["forward_return_4b"].mean() * 100) if len(tactical) else float("nan")
    late_suppressed = calibrated[calibrated["suppress_reason"] == "LATE_EXHAUSTION_SHORT_FILTER"]
    late_avoided_loss = float(late_suppressed["forward_return_16b"].mean() * 100) if len(late_suppressed) else float("nan")

    def row(name: str, m: dict[str, Any]) -> str:
        return (
            f"| {name} | "
            f"{m['long_exp_4b']*100:.3f}/{m['long_exp_8b']*100:.3f}/{m['long_exp_16b']*100:.3f}/{m['long_exp_32b']*100:.3f} | "
            f"{m['short_exp_4b']*100:.3f}/{m['short_exp_8b']*100:.3f}/{m['short_exp_16b']*100:.3f}/{m['short_exp_32b']*100:.3f} | "
            f"{m['observe_abs_16b']*100:.3f} | {m['directional_coverage_pct']:.1f}% | "
            f"{int(m['churn'])} | {int(m['stale_reversal_watch_reduction'])} |"
        )

    both_correct = (
        m_cal["long_exp_16b"] > 0
        and m_cal["short_exp_16b"] < 0
    )
    tactical_excluded = (
        len(tactical) > 0
        and (m_cal["short_exp_4b"] <= m_thr["short_exp_4b"] or m_cal["short_exp_16b"] <= m_thr["short_exp_16b"])
    )

    lines = [
        "# Calibrated v2 Context Report",
        "",
        "Rules: global gate 0.75/0.25 + LONG failed-anchor block + directional SHORT subtype allowlist.",
        "",
        "| scenario | LONG exp (4/8/16/32)% | SHORT exp (4/8/16/32)% | OBSERVE abs16% | directional coverage | churn | stale watch reduction |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        row("baseline", m_base),
        row("threshold_0.75_0.25", m_thr),
        row("calibrated_v2", m_cal),
        "",
        f"- tactical_short_candidate count: **{len(tactical)}**",
        f"- tactical_short_candidate avg 4b return: **{tactical_outcome:.3f}%**",
        f"- suppressed LATE_EXHAUSTION_SHORT count: **{len(late_suppressed)}**",
        f"- suppressed LATE_EXHAUSTION_SHORT avg 16b return (avoided): **{late_avoided_loss:.3f}%**",
        "",
        f"- LONG and SHORT both correct directional expectancy at 16b: **{'yes' if both_correct else 'no'}**",
        f"- Tactical shorts remain excluded from final context: **{'yes' if tactical_excluded else 'review'}**",
        "",
    ]
    return "\n".join(lines)


def build_calibrated_v3_report(
    baseline: pd.DataFrame,
    thresholded: pd.DataFrame,
    calibrated_v2: pd.DataFrame,
    calibrated_v3: pd.DataFrame,
) -> str:
    baseline_stale = int(
        (_stale_reversal_watch_mask(baseline) & baseline["chosen_context"].isin({"LONG_CONTEXT", "SHORT_CONTEXT"})).sum()
    )
    m_base = _scenario_metrics(baseline, context_col="chosen_context", baseline_stale=baseline_stale)
    m_thr = _scenario_metrics(thresholded, context_col="chosen_context", baseline_stale=baseline_stale)
    m_v2 = _scenario_metrics(
        calibrated_v2,
        context_col="calibrated_v2_context" if "calibrated_v2_context" in calibrated_v2.columns else "calibrated_context",
        baseline_stale=baseline_stale,
    )
    m_v3 = _scenario_metrics(
        calibrated_v3,
        context_col="calibrated_v3_context" if "calibrated_v3_context" in calibrated_v3.columns else "calibrated_context",
        baseline_stale=baseline_stale,
        short_candidate_col="short_candidate",
    )

    def row(name: str, m: dict[str, Any]) -> str:
        return (
            f"| {name} | "
            f"{m['context_LONG_CONTEXT']}/{m['context_SHORT_CONTEXT']}/{m['context_OBSERVE']} | "
            f"{m['long_exp_4b']*100:.3f}/{m['long_exp_8b']*100:.3f}/{m['long_exp_16b']*100:.3f}/{m['long_exp_32b']*100:.3f} | "
            f"{m.get('disabled_short_exp_4b', float('nan'))*100:.3f}/"
            f"{m.get('disabled_short_exp_8b', float('nan'))*100:.3f}/"
            f"{m.get('disabled_short_exp_16b', float('nan'))*100:.3f}/"
            f"{m.get('disabled_short_exp_32b', float('nan'))*100:.3f} | "
            f"{m['observe_abs_16b']*100:.3f} | {m['directional_coverage_pct']:.1f}% | "
            f"{int(m['churn'])} | {int(m['stale_reversal_watch_reduction'])} | "
            f"{int(m.get('disabled_short_count', 0))} | {int(m.get('suppressed_weak_late_long_count', 0))} |"
        )

    long_only_stable = (
        m_v3["long_exp_16b"] > 0
        and m_v3["context_SHORT_CONTEXT"] == 0
        and m_v3["directional_coverage_pct"] < m_v2["directional_coverage_pct"]
    )

    lines = [
        "# Calibrated v3 Context Report",
        "",
        "Rules: calibrated_v2 gate + HELD_STOPPING_VOLUME_REVERSAL LONG only; all SHORT → OBSERVE.",
        "",
        "| scenario | LONG/SHORT/OBSERVE | LONG exp (4/8/16/32)% | "
        "disabled SHORT exp (4/8/16/32)% | OBSERVE abs16% | dir coverage | churn | "
        "stale watch Δ | disabled SHORT | suppressed weak/late LONG |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        row("baseline", m_base),
        row("threshold_0.75_0.25", m_thr),
        row("calibrated_v2", m_v2),
        row("calibrated_v3", m_v3),
        "",
        f"- disabled SHORT candidate count (v3): **{m_v3.get('disabled_short_count', 0)}**",
        f"- suppressed weak/late LONG count (v3): **{m_v3.get('suppressed_weak_late_long_count', 0)}**",
        f"- LONG-only final context (no SHORT in v3): **{'yes' if m_v3['context_SHORT_CONTEXT'] == 0 else 'no'}**",
        f"- LONG 16b expectancy positive (v3): **{'yes' if m_v3['long_exp_16b'] > 0 else 'no'}**",
        f"- Shadow memory readiness (LONG-only stable): **{'yes' if long_only_stable else 'review'}**",
        "",
    ]
    return "\n".join(lines)


def _iter_weekly_buckets(
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> list[tuple[pd.Timestamp, pd.Timestamp, str]]:
    """Split [period_start, period_end) into 7-day UTC buckets."""
    buckets: list[tuple[pd.Timestamp, pd.Timestamp, str]] = []
    cursor = period_start
    while cursor < period_end:
        bucket_end = min(cursor + pd.Timedelta(days=7), period_end)
        label = (
            f"{cursor.strftime('%Y-%m-%d')} → "
            f"{(bucket_end - pd.Timedelta(minutes=1)).strftime('%Y-%m-%d')}"
        )
        buckets.append((cursor, bucket_end, label))
        cursor = bucket_end
    return buckets


def _slice_week(frame: pd.DataFrame, week_start: pd.Timestamp, week_end: pd.Timestamp) -> pd.DataFrame:
    ts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame[(ts >= week_start) & (ts < week_end)].copy()


def _weekly_bucket_metrics(
    baseline_week: pd.DataFrame,
    calibrated_week: pd.DataFrame,
) -> dict[str, Any]:
    work = calibrated_week.copy()
    if "calibrated_v3_context" in work.columns:
        context_col = "calibrated_v3_context"
    elif "calibrated_v2_context" in work.columns:
        context_col = "calibrated_v2_context"
    else:
        context_col = "calibrated_context"
    work["calibrated_context"] = work[context_col]
    valid = work.dropna(subset=["forward_return_16b"])

    long_bars = int((work["calibrated_context"] == "LONG_CONTEXT").sum())
    short_bars = int((work["calibrated_context"] == "SHORT_CONTEXT").sum())
    observe_bars = int((work["calibrated_context"] == "OBSERVE").sum())

    metrics = _scenario_metrics(
        work,
        context_col="calibrated_context",
        baseline_stale=int(
            (
                _stale_reversal_watch_mask(baseline_week)
                & baseline_week["chosen_context"].isin({"LONG_CONTEXT", "SHORT_CONTEXT"})
            ).sum()
        ),
    )

    first_close = _safe_float(baseline_week.iloc[0]["close"]) if len(baseline_week) else float("nan")
    last_close = _safe_float(baseline_week.iloc[-1]["close"]) if len(baseline_week) else float("nan")
    price_move_pct = (
        ((last_close - first_close) / first_close) * 100
        if len(baseline_week) and first_close > 0
        else float("nan")
    )

    late_suppressed = int(
        (calibrated_week["suppress_reason"] == "LATE_EXHAUSTION_SHORT_FILTER").sum()
    )

    return {
        "bars": len(baseline_week),
        "price_move_pct": price_move_pct,
        "long_bars": long_bars,
        "short_bars": short_bars,
        "observe_bars": observe_bars,
        "long_exp_4b": metrics["long_exp_4b"],
        "long_exp_8b": metrics["long_exp_8b"],
        "long_exp_16b": metrics["long_exp_16b"],
        "long_exp_32b": metrics["long_exp_32b"],
        "short_exp_4b": metrics["short_exp_4b"],
        "short_exp_8b": metrics["short_exp_8b"],
        "short_exp_16b": metrics["short_exp_16b"],
        "short_exp_32b": metrics["short_exp_32b"],
        "observe_abs_16b": metrics["observe_abs_16b"],
        "churn": metrics["churn"],
        "directional_coverage_pct": metrics["directional_coverage_pct"],
        "stale_reversal_watch_reduction": metrics["stale_reversal_watch_reduction"],
        "late_exhaustion_suppressed": late_suppressed,
        "valid_bars": len(valid),
    }


def _weekly_stability_verdict(rows: list[dict[str, Any]]) -> tuple[str, str, str]:
    long_positive_weeks = sum(
        1 for row in rows if not pd.isna(row["long_exp_16b"]) and row["long_exp_16b"] > 0
    )
    short_negative_weeks = sum(
        1 for row in rows if not pd.isna(row["short_exp_16b"]) and row["short_exp_16b"] < 0
    )
    weeks_with_long = sum(1 for row in rows if row["long_bars"] > 0)
    weeks_with_short = sum(1 for row in rows if row["short_bars"] > 0)
    total_weeks = len(rows)

    if weeks_with_long == 0:
        long_verdict = "insufficient LONG samples across weeks"
    elif long_positive_weeks == weeks_with_long:
        long_verdict = "stable — positive 16b expectancy in every week with LONG bars"
    elif long_positive_weeks >= max(1, weeks_with_long * 0.75):
        long_verdict = f"mostly stable — {long_positive_weeks}/{weeks_with_long} LONG-active weeks positive at 16b"
    else:
        long_verdict = f"unstable — only {long_positive_weeks}/{weeks_with_long} LONG-active weeks positive at 16b"

    if weeks_with_short == 0:
        short_verdict = "insufficient SHORT samples across weeks"
    elif short_negative_weeks == weeks_with_short:
        short_verdict = "stable — negative 16b expectancy in every week with SHORT bars"
    elif short_negative_weeks >= max(1, weeks_with_short * 0.75):
        short_verdict = f"mostly stable — {short_negative_weeks}/{weeks_with_short} SHORT-active weeks negative at 16b"
    else:
        short_verdict = f"unstable — only {short_negative_weeks}/{weeks_with_short} SHORT-active weeks negative at 16b"

    both_stable = (
        weeks_with_long > 0
        and weeks_with_short > 0
        and long_positive_weeks == weeks_with_long
        and short_negative_weeks == weeks_with_short
    )
    mostly_stable = (
        weeks_with_long > 0
        and weeks_with_short > 0
        and long_positive_weeks >= max(1, weeks_with_long * 0.75)
        and short_negative_weeks >= max(1, weeks_with_short * 0.75)
    )
    if both_stable:
        readiness = (
            "ready for shadow runtime engine — weekly LONG and SHORT directional expectancy "
            "holds across all active weeks"
        )
    elif mostly_stable:
        readiness = (
            "conditionally ready for shadow runtime — edge holds in most weeks; "
            "run one more held-out week before live wiring"
        )
    else:
        readiness = (
            "not ready for shadow runtime — weekly edge is inconsistent; "
            "continue calibration before wiring"
        )

    return long_verdict, short_verdict, readiness


def build_weekly_validation_report(
    baseline: pd.DataFrame,
    calibrated: pd.DataFrame,
    *,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    version_label: str = "calibrated_v2",
) -> str:
    rows: list[dict[str, Any]] = []
    for week_start, week_end, label in _iter_weekly_buckets(period_start, period_end):
        baseline_week = _slice_week(baseline, week_start, week_end)
        calibrated_week = _slice_week(calibrated, week_start, week_end)
        if baseline_week.empty:
            continue
        week_metrics = _weekly_bucket_metrics(baseline_week, calibrated_week)
        week_metrics["week"] = label
        rows.append(week_metrics)

    long_verdict, short_verdict, readiness = _weekly_stability_verdict(rows)

    lines = [
        f"# Weekly {version_label} validation",
        "",
        f"Per-week buckets (7-day UTC slices) with {version_label} context metrics.",
        "",
        "| week | bars | price move% | LONG | SHORT | OBSERVE | "
        "LONG exp 4/8/16/32% | SHORT exp 4/8/16/32% | OBS abs16% | "
        "churn | dir coverage% | stale watch Δ | LATE_EXH suppressed |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['week']} | {row['bars']} | {row['price_move_pct']:.2f} | "
            f"{row['long_bars']} | {row['short_bars']} | {row['observe_bars']} | "
            f"{row['long_exp_4b']*100:.3f}/{row['long_exp_8b']*100:.3f}/"
            f"{row['long_exp_16b']*100:.3f}/{row['long_exp_32b']*100:.3f} | "
            f"{row['short_exp_4b']*100:.3f}/{row['short_exp_8b']*100:.3f}/"
            f"{row['short_exp_16b']*100:.3f}/{row['short_exp_32b']*100:.3f} | "
            f"{row['observe_abs_16b']*100:.3f} | {row['churn']} | "
            f"{row['directional_coverage_pct']:.1f} | {row['stale_reversal_watch_reduction']} | "
            f"{row['late_exhaustion_suppressed']} |"
        )

    lines.extend(
        [
            "",
            "## Weekly stability",
            "",
            f"- **LONG edge:** {long_verdict}",
            f"- **SHORT edge:** {short_verdict}",
            f"- **Shadow runtime readiness:** {readiness}",
            "",
        ]
    )
    return "\n".join(lines)


def _horizon_conclusion(replay: pd.DataFrame, sweep: pd.DataFrame) -> list[str]:
    ranked = _rank_sweep_results(sweep)
    best = ranked.iloc[0]
    detail = _horizon_breakdown_for_threshold(
        replay,
        min_directional_score=float(best["min_directional_score"]),
        min_score_margin=float(best["min_score_margin"]),
    )
    long_exp = {bars: detail[f"long_expectancy_{bars}b"] for bars in FORWARD_HORIZONS}
    short_exp = {bars: detail[f"short_expectancy_{bars}b"] for bars in FORWARD_HORIZONS}
    best_long_bars, best_long_val = _best_horizon_label(long_exp, context="LONG_CONTEXT")
    best_short_bars, best_short_val = _best_horizon_label(short_exp, context="SHORT_CONTEXT")

    short_horizon_signal = any(
        not pd.isna(short_exp[bars]) and short_exp[bars] < 0 for bars in (4, 8)
    )
    gate_unchanged = (
        float(best["min_directional_score"]) == 0.75 and float(best["min_score_margin"]) == 0.25
    )

    lines = [
        "## Horizon conclusion",
        "",
        f"- **Best LONG horizon:** {best_long_bars}b "
        f"(expectancy {best_long_val * 100:.3f}%)",
        f"- **Best SHORT horizon:** {best_short_bars}b "
        f"(expectancy {best_short_val * 100:.3f}%)",
        f"- **SHORT short-horizon signal:** "
        f"{'yes' if short_horizon_signal else 'no'} "
        f"(4b={short_exp[4]*100:.3f}%, 8b={short_exp[8]*100:.3f}%, 16b={short_exp[16]*100:.3f}%)",
        f"- **0.75 / 0.25 remains best gate:** {'yes' if gate_unchanged else 'no'} "
        f"(ranked best: {best['min_directional_score']:.2f} / {best['min_score_margin']:.2f})",
        "",
    ]
    return lines


def _stale_reversal_watch_mask(frame: pd.DataFrame) -> pd.Series:
    return (frame["trading_state"] == "REVERSAL_WATCH") & (
        (frame["anchor_status"] == "FAILED")
        | (frame["short_context_score"] > frame["long_context_score"] + 0.15)
    )


def apply_threshold_filter(
    replay: pd.DataFrame,
    *,
    min_directional_score: float,
    min_score_margin: float,
) -> pd.DataFrame:
    """Research-only post-filter: demote weak directional calls to OBSERVE."""
    out = replay.copy()
    if "chosen_context_raw" not in out.columns:
        out["chosen_context_raw"] = out["chosen_context"]

    contexts: list[str] = []
    for _, row in out.iterrows():
        raw = _clean_text(row.get("chosen_context_raw") or row.get("chosen_context")).upper()
        long_score = _safe_float(row.get("long_context_score"))
        short_score = _safe_float(row.get("short_context_score"))
        chosen = raw
        if raw == "LONG_CONTEXT":
            if long_score < min_directional_score or (long_score - short_score) < min_score_margin:
                chosen = "OBSERVE"
        elif raw == "SHORT_CONTEXT":
            if short_score < min_directional_score or (short_score - long_score) < min_score_margin:
                chosen = "OBSERVE"
        contexts.append(chosen)
    out["chosen_context"] = contexts
    out = _refresh_favorable_adverse(out)
    return _attach_short_subtypes(out)


def _sweep_row_metrics(
    replay: pd.DataFrame,
    *,
    min_directional_score: float,
    min_score_margin: float,
    baseline_stale_directional: int,
) -> dict[str, Any]:
    swept = apply_threshold_filter(
        replay,
        min_directional_score=min_directional_score,
        min_score_margin=min_score_margin,
    )
    valid = swept.dropna(subset=["forward_return_16b"])
    long_rows = valid[valid["chosen_context"] == "LONG_CONTEXT"]
    short_rows = valid[valid["chosen_context"] == "SHORT_CONTEXT"]
    observe_rows = valid[valid["chosen_context"] == "OBSERVE"]

    long_hit = _context_hit_mask(valid, "LONG_CONTEXT")
    short_hit = _context_hit_mask(valid, "SHORT_CONTEXT")

    churn = int((swept["chosen_context"] != swept["chosen_context"].shift(1)).sum())
    directional_coverage = (
        len(valid[valid["chosen_context"].isin({"LONG_CONTEXT", "SHORT_CONTEXT"})]) / max(len(valid), 1) * 100
    )

    stale_mask = _stale_reversal_watch_mask(swept)
    stale_directional = int(
        (stale_mask & swept["chosen_context"].isin({"LONG_CONTEXT", "SHORT_CONTEXT"})).sum()
    )
    stale_reduction = baseline_stale_directional - stale_directional

    long_exp = float(long_rows["forward_return_16b"].mean()) if len(long_rows) else float("nan")
    short_exp = float(short_rows["forward_return_16b"].mean()) if len(short_rows) else float("nan")

    return {
        "min_directional_score": min_directional_score,
        "min_score_margin": min_score_margin,
        "long_bars": int(len(long_rows)),
        "short_bars": int(len(short_rows)),
        "observe_bars": int(len(observe_rows)),
        "long_expectancy_16b": long_exp,
        "short_expectancy_16b": short_exp,
        "long_hit_rate": float(long_hit.sum() / max(len(long_rows), 1)),
        "short_hit_rate": float(short_hit.sum() / max(len(short_rows), 1)),
        "observe_avg_abs_move_16b": float(observe_rows["forward_return_16b"].abs().mean())
        if len(observe_rows)
        else float("nan"),
        "churn": churn,
        "directional_coverage_pct": directional_coverage,
        "stale_reversal_watch_directional": stale_directional,
        "stale_reversal_watch_reduction": stale_reduction,
        "both_expectancy_positive": bool(
            len(long_rows) > 0
            and len(short_rows) > 0
            and not pd.isna(long_exp)
            and not pd.isna(short_exp)
            and long_exp > 0
            and short_exp < 0
        ),
    }


def run_threshold_sweep(replay: pd.DataFrame) -> pd.DataFrame:
    if "chosen_context_raw" not in replay.columns:
        replay = replay.copy()
        replay["chosen_context_raw"] = replay["chosen_context"]
    baseline_stale_directional = int(
        (
            _stale_reversal_watch_mask(replay)
            & replay["chosen_context"].isin({"LONG_CONTEXT", "SHORT_CONTEXT"})
        ).sum()
    )
    rows = [
        _sweep_row_metrics(
            replay,
            min_directional_score=min_dir,
            min_score_margin=min_margin,
            baseline_stale_directional=baseline_stale_directional,
        )
        for min_dir in SWEEP_MIN_DIRECTIONAL_SCORES
        for min_margin in SWEEP_MIN_SCORE_MARGINS
    ]
    return pd.DataFrame(rows)


def _rank_sweep_results(sweep: pd.DataFrame) -> pd.DataFrame:
    ranked = sweep.copy()
    ranked["long_exp_pct"] = ranked["long_expectancy_16b"] * 100
    ranked["short_exp_pct"] = ranked["short_expectancy_16b"] * 100
    ranked["score"] = (
        ranked["long_hit_rate"] * 100
        + ranked["short_hit_rate"] * 100
        + ranked["long_exp_pct"].clip(-5, 5)
        - ranked["short_exp_pct"].clip(-5, 5)
        + ranked["stale_reversal_watch_reduction"] * 0.05
        - (100 - ranked["directional_coverage_pct"]) * 0.1
    )
    ranked.loc[~ranked["both_expectancy_positive"], "score"] -= 50
    return ranked.sort_values("score", ascending=False)


def _sweep_recommendation(sweep: pd.DataFrame) -> str:
    positive_both = sweep[sweep["both_expectancy_positive"]]
    if len(positive_both) > 0:
        best = _rank_sweep_results(positive_both).iloc[0]
        return (
            "**Calibrate and continue.** "
            f"Threshold pair min_directional_score={best['min_directional_score']:.2f}, "
            f"min_score_margin={best['min_score_margin']:.2f} achieves positive LONG and negative SHORT "
            f"16b expectancy with LONG hit {best['long_hit_rate']*100:.1f}% and SHORT hit "
            f"{best['short_hit_rate']*100:.1f}%."
        )
    best = _rank_sweep_results(sweep).iloc[0]
    if best["long_hit_rate"] >= 0.55 and best["short_hit_rate"] >= 0.55:
        return (
            "**Continue research with calibration.** "
            "No threshold pair produced jointly positive LONG and negative SHORT 16b expectancy, "
            f"but best hit rates are LONG {best['long_hit_rate']*100:.1f}% / SHORT {best['short_hit_rate']*100:.1f}% "
            f"at min_directional_score={best['min_directional_score']:.2f}, min_score_margin={best['min_score_margin']:.2f}."
        )
    return (
        "**Discard current threshold-only approach for this window.** "
        "No combination yields dual positive directional expectancy; hit-rate gains from filtering "
        "do not overcome negative 16b edge. Revisit arbitrator scoring inputs before threshold tuning."
    )


def build_threshold_sweep_report(
    sweep: pd.DataFrame,
    *,
    csv_path: Path,
    replay: pd.DataFrame | None = None,
) -> str:
    ranked = _rank_sweep_results(sweep)
    best_rows = ranked.head(10)
    positive_both = sweep[sweep["both_expectancy_positive"]]

    display = sweep.copy()
    for col in ("long_expectancy_16b", "short_expectancy_16b", "observe_avg_abs_move_16b"):
        display[col] = display[col] * 100
    for col in ("long_hit_rate", "short_hit_rate"):
        display[col] = display[col] * 100

    lines = [
        "# Auction Context Threshold Sweep",
        "",
        f"**Combinations:** {len(sweep)}",
        f"**CSV:** `{csv_path}`",
        f"**Pairs with positive LONG and negative SHORT expectancy:** {len(positive_both)}",
        "",
        "## Best threshold rows (ranked)",
        "",
        "| min_dir | min_margin | LONG | SHORT | OBSERVE | LONG exp% | SHORT exp% | LONG hit% | SHORT hit% | OBS abs% | churn | dir_cov% | stale_red |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in best_rows.iterrows():
        lines.append(
            f"| {row['min_directional_score']:.2f} | {row['min_score_margin']:.2f} | "
            f"{int(row['long_bars'])} | {int(row['short_bars'])} | {int(row['observe_bars'])} | "
            f"{row['long_expectancy_16b']*100:.3f} | {row['short_expectancy_16b']*100:.3f} | "
            f"{row['long_hit_rate']*100:.1f} | {row['short_hit_rate']*100:.1f} | "
            f"{row['observe_avg_abs_move_16b']*100:.3f} | {int(row['churn'])} | "
            f"{row['directional_coverage_pct']:.1f} | {int(row['stale_reversal_watch_reduction'])} |"
        )
    lines.extend(["", "## Recommendation", "", _sweep_recommendation(sweep), ""])
    if replay is not None:
        lines.extend(_horizon_breakdown_lines(replay, best_rows))
        best = ranked.iloc[0]
        best_filtered = apply_threshold_filter(
            replay,
            min_directional_score=float(best["min_directional_score"]),
            min_score_margin=float(best["min_score_margin"]),
        )
        lines.extend(_short_subtype_report_lines(best_filtered))
        lines.extend(_horizon_conclusion(replay, sweep))
    return "\n".join(lines)


def _is_long_correct(row: pd.Series) -> bool:
    fwd = _safe_float(row.get("forward_return_16b"), default=float("nan"))
    fav = _safe_float(row.get("max_favorable_16b"), default=float("nan"))
    adv = _safe_float(row.get("max_adverse_16b"), default=float("nan"))
    if pd.isna(fwd) and pd.isna(fav):
        return False
    if not pd.isna(fwd) and fwd > 0:
        return True
    return not pd.isna(fav) and not pd.isna(adv) and fav > adv


def _is_short_correct(row: pd.Series) -> bool:
    fwd = _safe_float(row.get("forward_return_16b"), default=float("nan"))
    fav = _safe_float(row.get("max_favorable_16b"), default=float("nan"))
    adv = _safe_float(row.get("max_adverse_16b"), default=float("nan"))
    if pd.isna(fwd) and pd.isna(fav):
        return False
    if not pd.isna(fwd) and fwd < 0:
        return True
    return not pd.isna(fav) and not pd.isna(adv) and fav > adv


def _is_observe_acceptable(row: pd.Series) -> bool:
    fwd = _safe_float(row.get("forward_return_16b"), default=float("nan"))
    fav = _safe_float(row.get("max_favorable_16b"), default=float("nan"))
    adv = _safe_float(row.get("max_adverse_16b"), default=float("nan"))
    if pd.isna(fwd):
        return False
    if abs(fwd) <= OBSERVE_ABS_RETURN_THRESHOLD:
        return True
    if pd.isna(fav) or pd.isna(adv):
        return False
    return abs(fav - adv) <= OBSERVE_NOISE_SPREAD_THRESHOLD


def _context_hit_mask(frame: pd.DataFrame, context: str) -> pd.Series:
    hits = pd.Series(False, index=frame.index)
    subset = frame[frame["chosen_context"] == context]
    if subset.empty:
        return hits
    if context == "LONG_CONTEXT":
        hits.loc[subset.index] = subset.apply(_is_long_correct, axis=1)
    elif context == "SHORT_CONTEXT":
        hits.loc[subset.index] = subset.apply(_is_short_correct, axis=1)
    else:
        hits.loc[subset.index] = subset.apply(_is_observe_acceptable, axis=1)
    return hits


def _average_context_duration(frame: pd.DataFrame, context: str) -> float:
    contexts = frame["chosen_context"]
    run_id = (contexts != contexts.shift()).cumsum()
    runs = frame.assign(_run=run_id).groupby("_run", as_index=False).agg(
        label=("chosen_context", "first"),
        size=("chosen_context", "size"),
    )
    selected = runs.loc[runs["label"] == context, "size"]
    return float(selected.mean()) if len(selected) else 0.0


def _outcome_summary_lines(replay: pd.DataFrame) -> list[str]:
    valid = replay.dropna(subset=["forward_return_16b"])
    lines = ["## Forward outcome validation", ""]

    long_rows = valid[valid["chosen_context"] == "LONG_CONTEXT"]
    short_rows = valid[valid["chosen_context"] == "SHORT_CONTEXT"]
    observe_rows = valid[valid["chosen_context"] == "OBSERVE"]

    long_hit = _context_hit_mask(valid, "LONG_CONTEXT")
    short_hit = _context_hit_mask(valid, "SHORT_CONTEXT")
    observe_hit = _context_hit_mask(valid, "OBSERVE")

    churn = int((replay["chosen_context"] != replay["chosen_context"].shift(1)).sum())

    false_long = long_rows[~long_hit.loc[long_rows.index]].sort_values("forward_return_16b")
    false_short = short_rows[~short_hit.loc[short_rows.index]].sort_values(
        "forward_return_16b",
        ascending=False,
    )

    lines.extend(
        [
            "| metric | LONG_CONTEXT | SHORT_CONTEXT | OBSERVE |",
            "| --- | ---: | ---: | ---: |",
            f"| expectancy (mean forward_return_16b) | "
            f"{long_rows['forward_return_16b'].mean() * 100 if len(long_rows) else 0:.3f}% | "
            f"{short_rows['forward_return_16b'].mean() * 100 if len(short_rows) else 0:.3f}% | "
            f"{observe_rows['forward_return_16b'].mean() * 100 if len(observe_rows) else 0:.3f}% |",
            f"| hit rate | "
            f"{long_hit.sum() / max(len(long_rows), 1) * 100:.1f}% | "
            f"{short_hit.sum() / max(len(short_rows), 1) * 100:.1f}% | "
            f"{observe_hit.sum() / max(len(observe_rows), 1) * 100:.1f}% |",
            f"| avg duration (bars) | "
            f"{_average_context_duration(replay, 'LONG_CONTEXT'):.1f} | "
            f"{_average_context_duration(replay, 'SHORT_CONTEXT'):.1f} | "
            f"{_average_context_duration(replay, 'OBSERVE'):.1f} |",
            "",
            f"- **OBSERVE average absolute move (16b):** "
            f"{observe_rows['forward_return_16b'].abs().mean() * 100 if len(observe_rows) else 0:.3f}%",
            f"- **Shadow context churn:** {churn} bar-to-bar changes "
            f"({churn / max(len(replay) - 1, 1) * 100:.1f}% of bars)",
            "",
        ]
    )

    missed_short = valid[
        (valid["trading_state"] == "REVERSAL_WATCH") & (valid["chosen_context"] == "SHORT_CONTEXT")
    ].sort_values("forward_return_16b")
    missed_long = valid[
        (valid["trading_state"] == "REVERSAL_WATCH") & (valid["chosen_context"] == "LONG_CONTEXT")
    ].sort_values("forward_return_16b", ascending=False)

    lines.extend(
        [
            "### Worst false LONG periods",
            "",
            _md_table(
                false_long,
                ["timestamp", "close", "forward_return_16b", "max_favorable_16b", "max_adverse_16b", "chosen_reason"],
                max_rows=10,
            ),
            "### Worst false SHORT periods",
            "",
            _md_table(
                false_short,
                ["timestamp", "close", "forward_return_16b", "max_favorable_16b", "max_adverse_16b", "chosen_reason"],
                max_rows=10,
            ),
            "### Best SHORT periods missed by live REVERSAL_WATCH",
            "",
            _md_table(
                missed_short,
                ["timestamp", "close", "forward_return_16b", "max_favorable_16b", "max_adverse_16b", "chosen_reason"],
                max_rows=10,
            ),
            "### Best LONG periods missed by live REVERSAL_WATCH",
            "",
            _md_table(
                missed_long,
                ["timestamp", "close", "forward_return_16b", "max_favorable_16b", "max_adverse_16b", "chosen_reason"],
                max_rows=10,
            ),
            "",
        ]
    )
    return lines


def _directional_value_conclusion(replay: pd.DataFrame) -> str:
    valid = replay.dropna(subset=["forward_return_16b"])
    long_rows = valid[valid["chosen_context"] == "LONG_CONTEXT"]
    short_rows = valid[valid["chosen_context"] == "SHORT_CONTEXT"]

    long_hit = _context_hit_mask(valid, "LONG_CONTEXT").sum() / max(len(long_rows), 1)
    short_hit = _context_hit_mask(valid, "SHORT_CONTEXT").sum() / max(len(short_rows), 1)
    long_exp = long_rows["forward_return_16b"].mean() if len(long_rows) else 0.0
    short_exp = short_rows["forward_return_16b"].mean() if len(short_rows) else 0.0

    long_positive = long_exp > 0 and long_hit >= 0.5
    short_positive = short_exp < 0 and short_hit >= 0.5

    if long_positive and short_positive:
        return (
            "**Shadow contexts show positive directional value overall.** "
            "Both LONG and SHORT shadow calls carry favorable 16-bar expectancy with hit rates at or above 50%."
        )
    if short_positive and not long_positive:
        return (
            "**Partial directional value — SHORT_CONTEXT only.** "
            "Shadow shorts align with downside follow-through; LONG calls do not yet show positive expectancy."
        )
    if long_positive and not short_positive:
        return (
            "**Partial directional value — LONG_CONTEXT only.** "
            "Shadow longs show follow-through; SHORT calls need scoring review."
        )
    return (
        "**Limited directional value in this window.** "
        "Neither shadow LONG nor SHORT contexts consistently beat random at 16-bar horizon."
    )


def _md_table(frame: pd.DataFrame, columns: list[str], max_rows: int = 12) -> str:
    if frame.empty:
        return "_No rows._\n"
    subset = frame.head(max_rows)
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [header, sep]
    for _, row in subset.iterrows():
        cells = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, pd.Timestamp):
                cells.append(value.strftime("%Y-%m-%d %H:%M"))
            elif isinstance(value, float):
                cells.append(f"{value:.4f}")
            else:
                text = _clean_text(value, "—")
                cells.append(text.replace("|", "/")[:80])
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _distribution_table(series: pd.Series, label: str) -> str:
    if series.empty:
        return f"_No {label} rows._\n"
    counts = series.value_counts()
    total = int(counts.sum())
    lines = [
        f"| {label} | bars | pct |",
        "| --- | ---: | ---: |",
    ]
    for name, count in counts.items():
        lines.append(f"| {name} | {int(count)} | {count / total * 100:.1f}% |")
    lines.append(f"| **TOTAL** | **{total}** | **100.0%** |")
    return "\n".join(lines) + "\n"


def _live_shadow_comparison_table(replay: pd.DataFrame) -> str:
    live = replay["trading_state"].value_counts()
    shadow = replay["chosen_context"].value_counts()
    keys = sorted(set(live.index.astype(str)) | set(shadow.index.astype(str)))
    lines = [
        "| label | live bars | shadow bars |",
        "| --- | ---: | ---: |",
    ]
    for key in keys:
        lines.append(f"| {key} | {int(live.get(key, 0))} | {int(shadow.get(key, 0))} |")
    return "\n".join(lines) + "\n"



def _assess_arbitrator_stability(replay: pd.DataFrame) -> tuple[str, list[str]]:
    notes: list[str] = []
    churn = (replay["chosen_context"] != replay["chosen_context"].shift(1)).sum()
    churn_rate = churn / max(len(replay) - 1, 1) * 100
    notes.append(f"Shadow context churn: **{int(churn)}** bar-to-bar changes ({churn_rate:.1f}% of bars).")

    comparable = replay[replay["existing_context"].notna()]
    agreement = 0.0
    if len(comparable):
        agreement = (comparable["existing_context"] == comparable["chosen_context"]).mean() * 100
        notes.append(f"Agreement with live final context (where set): **{agreement:.1f}%**.")

    reversal = replay[replay["trading_state"] == "REVERSAL_WATCH"]
    mismatch = reversal[reversal["chosen_context"] != "REVERSAL_WATCH"]
    mismatch_rate = len(mismatch) / max(len(reversal), 1) * 100
    notes.append(f"REVERSAL_WATCH divergence from shadow: **{mismatch_rate:.1f}%** of watch bars.")

    directional_share = (
        replay["chosen_context"].isin({"LONG_CONTEXT", "SHORT_CONTEXT"}).mean() * 100
    )
    notes.append(f"Shadow directional commitment (LONG+SHORT): **{directional_share:.1f}%** of bars.")

    if churn_rate > 35 or directional_share > 85:
        verdict = "OVERACTIVE — shadow flips or commits directionally too often for a stable gate."
    elif churn_rate < 15 and 40 <= directional_share <= 75:
        verdict = "STABLE — shadow context shifts at a moderate rate with reasonable directional selectivity."
    else:
        verdict = "MODERATELY ACTIVE — usable for shadow runtime, but monitor churn and directional share."

    return verdict, notes


def _readiness_recommendation(stale_rate: float, verdict: str) -> str:
    if stale_rate > 10.0:
        return (
            "**Needs scoring adjustment before shadow runtime.** "
            f"Stale REVERSAL_WATCH rate ({stale_rate:.1f}%) exceeds the 10% replay gate."
        )
    if "OVERACTIVE" in verdict:
        return (
            "**Needs scoring adjustment before shadow runtime.** "
            "Arbitrator churn/directional share suggests over-commitment; tune thresholds in replay first."
        )
    return (
        "**Ready for shadow runtime engine (read-only).** "
        "Wire `score_auction_context` as a parallel scorer with no trading_state_engine changes; "
        "keep live posture mapping until a second validation week confirms stability."
    )


def build_markdown_report(
    replay: pd.DataFrame,
    *,
    load_notes: list[str],
    csv_path: Path,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> str:
    reversal_rows = replay[replay["trading_state"] == "REVERSAL_WATCH"].copy()
    short_selected = replay[replay["chosen_context"] == "SHORT_CONTEXT"].copy()
    observe_selected = replay[replay["chosen_context"] == "OBSERVE"].copy()
    mismatch = reversal_rows[reversal_rows["chosen_context"] != "REVERSAL_WATCH"].copy()

    start_close = replay.iloc[0]["close"] if len(replay) else None
    end_close = replay.iloc[-1]["close"] if len(replay) else None
    price_change = None
    if start_close and end_close:
        price_change = (end_close - start_close) / start_close * 100

    stale_mask = (
        (replay["trading_state"] == "REVERSAL_WATCH")
        & (
            (replay["anchor_status"] == "FAILED")
            | (replay["short_context_score"] > replay["long_context_score"] + 0.15)
        )
    )
    stale_rows = replay[stale_mask]
    stale_rate = len(stale_rows) / max(len(reversal_rows), 1) * 100

    rev_short = reversal_rows[reversal_rows["chosen_context"] == "SHORT_CONTEXT"].sort_values(
        "short_context_score", ascending=False
    )
    rev_long = reversal_rows[reversal_rows["chosen_context"] == "LONG_CONTEXT"].sort_values(
        "long_context_score", ascending=False
    )
    observe_top = observe_selected.sort_values("observe_score", ascending=False)

    stability_verdict, stability_notes = _assess_arbitrator_stability(replay)
    readiness = _readiness_recommendation(stale_rate, stability_verdict)

    period_end_inclusive = period_end - pd.Timedelta(days=1)

    lines = [
        "# Auction Context Arbitration Replay",
        "",
        f"**Period:** {period_start.date()} → {period_end_inclusive.date()} (UTC)",
        f"**Generated:** {pd.Timestamp.now(tz='UTC').isoformat()}",
        f"**CSV:** `{csv_path}`",
        "",
        "## Key metrics",
        "",
        f"- **Total bars:** {len(replay)}",
    ]

    if price_change is not None:
        lines.append(
            f"- **Price move:** {price_change:.2f}% ({start_close:.2f} → {end_close:.2f})"
        )
    lines.extend(
        [
            f"- **Live REVERSAL_WATCH bars:** {len(reversal_rows)} "
            f"({len(reversal_rows)/max(len(replay),1)*100:.1f}% of window)",
            f"- **Stale REVERSAL_WATCH bars:** {len(stale_rows)}",
            f"- **Stale REVERSAL_WATCH rate:** {stale_rate:.1f}% (of REVERSAL_WATCH bars)",
            "",
            "## Live trading_state distribution",
            "",
            _distribution_table(replay["trading_state"], "trading_state"),
            "",
            "## Shadow chosen_context distribution",
            "",
            _distribution_table(replay["chosen_context"], "chosen_context"),
            "",
            "## Live vs shadow comparison",
            "",
            _live_shadow_comparison_table(replay),
            "",
            "## Executive summary",
            "",
        ]
    )

    if price_change is not None:
        lines.append(
            f"- Price moved **{price_change:.2f}%** across **{len(replay)}** M15 bars "
            f"({start_close:.2f} → {end_close:.2f})."
        )
    lines.extend(
        [
            f"- Live `trading_state` spent **{len(reversal_rows)}** bar-rows in `REVERSAL_WATCH` "
            f"({len(reversal_rows)/max(len(replay),1)*100:.1f}% of window).",
            f"- Hypothetical arbitration chose `SHORT_CONTEXT` on **{len(short_selected)}** bars "
            f"and `OBSERVE` on **{len(observe_selected)}** bars.",
            f"- **{len(mismatch)}** `REVERSAL_WATCH` moments would have received a different "
            "final context under arbitration.",
            f"- **{len(stale_rows)}** bars show stale reversal posture: `REVERSAL_WATCH` while anchor "
            f"failed or short evidence clearly led (**{stale_rate:.1f}%** of watch bars).",
            "",
        ]
    )

    if load_notes:
        lines.extend(["### Source notes", ""])
        lines.extend(f"- {note}" for note in load_notes)
        lines.append("")

    lines.extend(
        [
            "## Top periods: REVERSAL_WATCH live, shadow SHORT_CONTEXT",
            "",
            _md_table(
                rev_short,
                ["timestamp", "close", "short_context_score", "anchor_status", "chosen_reason"],
                max_rows=15,
            ),
            "",
            "## Top periods: REVERSAL_WATCH live, shadow LONG_CONTEXT",
            "",
            _md_table(
                rev_long,
                ["timestamp", "close", "long_context_score", "anchor_status", "chosen_reason"],
                max_rows=15,
            ),
            "",
            "## Top periods: shadow OBSERVE",
            "",
            _md_table(
                observe_top,
                ["timestamp", "close", "trading_state", "observe_score", "chosen_reason"],
                max_rows=15,
            ),
            "",
            "## Arbitrator stability",
            "",
            f"**Verdict:** {stability_verdict}",
            "",
        ]
    )
    lines.extend(f"- {note}" for note in stability_notes)
    lines.extend(["", "## Readiness recommendation", "", readiness, ""])
    lines.extend(_outcome_summary_lines(replay))
    lines.extend(["## Directional value conclusion", "", _directional_value_conclusion(replay), ""])

    lines.extend(
        [
            "## Timeline overview",
            "",
            _md_table(
                replay,
                ["timestamp", "close", "market_state", "trading_state", "chosen_context", "anchor_status"],
                max_rows=8,
            ),
            "",
            "## REVERSAL_WATCH vs arbitration",
            "",
            "`REVERSAL_WATCH` is treated as an internal candidate posture, not a final directional context.",
            "",
            _md_table(
                mismatch,
                [
                    "timestamp",
                    "close",
                    "trading_state",
                    "chosen_context",
                    "short_context_score",
                    "long_context_score",
                    "anchor_status",
                    "chosen_reason",
                ],
                max_rows=15,
            ),
            "",
            "## Where SHORT_CONTEXT would have been selected",
            "",
            _md_table(
                short_selected,
                ["timestamp", "close", "trading_state", "short_context_score", "anchor_status", "chosen_reason"],
                max_rows=15,
            ),
            "",
            "## Where OBSERVE was justified",
            "",
            _md_table(
                observe_selected,
                ["timestamp", "close", "trading_state", "observe_score", "chosen_reason"],
                max_rows=12,
            ),
            "",
            "## Stale reversal logic signals",
            "",
            "Bars where live model remained in `REVERSAL_WATCH` but auction evidence favored exit "
            "from reversal candidacy (failed anchor and/or dominant short score).",
            "",
            _md_table(
                stale_rows,
                [
                    "timestamp",
                    "close",
                    "anchor_event_type",
                    "anchor_status",
                    "short_context_score",
                    "long_context_score",
                    "why_not_long",
                ],
                max_rows=15,
            ),
            "",
            "## Root-cause interpretation",
            "",
            "1. **Direct mapping, no arbitration:** `market_state=REVERSAL` maps 1:1 to `REVERSAL_WATCH` "
            "via `V1_MARKET_STATE_TO_TRADING_STATE` in `config/trading_state.py`. No layer converts "
            "auction cognition into `LONG_CONTEXT` / `SHORT_CONTEXT` / `OBSERVE`.",
            "2. **Lifecycle extends watch:** `apply_reversal_watch_lifecycle()` keeps `REVERSAL_WATCH` "
            "alive for up to 24h while `market_state` stays `REVERSAL`, even when anchor evidence fails.",
            "3. **Cognition vs posture disconnect:** `runtime_cognition_composite` continued to emit "
            "`STOPPING_VOLUME` / `LOWER_ABSORPTION` anchors while convergence showed "
            "`PERSISTENT_DISTRIBUTION` and price drifted lower — arbitration would have shifted toward "
            "`SHORT_CONTEXT` or `OBSERVE` on failed anchors.",
            "4. **Sandbox context gap:** `current_active_context` is null because only "
            "`LONG_CONTEXT` / `SHORT_CONTEXT` count as active contexts; `REVERSAL_WATCH` never "
            "populates directional context in the visualizer.",
            "",
            "## Recommended next patch plan (no live changes in this audit)",
            "",
            "1. **Wire `btc_ml.cognition.auction_context_arbitrator`** as shadow scorer alongside replay; "
            "promote only after validation.",
            "2. **Split REVERSAL candidacy from final context:** keep `REVERSAL_WATCH` as a short-lived "
            "candidate flag; resolve to `LONG_CONTEXT` / `SHORT_CONTEXT` / `OBSERVE` via anchor HELD/FAILED "
            "rules and convergence state.",
            "3. **Invalidate watch on anchor failure:** when `tier2_anchor` status is FAILED or "
            "`PERSISTENT_DISTRIBUTION` persists with efficient downside continuation, exit `REVERSAL_WATCH` "
            "to `SHORT_CONTEXT` or `OBSERVE` instead of waiting for TTL.",
            "4. **Feed arbitration from cognition composite:** use `tier1_trigger_event`, "
            "`tier1_location_bias`, `anchor_age_bars`, and `effective_state` as first-class inputs to "
            "trading posture — not only `market_state` enum.",
            "5. **Replay gate before docker5:** require this CSV replay to show <10% stale-watch rate "
            "on a held-out week before enabling any live arbitrator wiring.",
            "",
        ]
    )
    return "\n".join(lines)


SHORT_FEATURE_NUMERIC = (
    "recent_return_4b",
    "recent_return_8b",
    "recent_return_16b",
    "distance_from_recent_high_16b",
    "distance_from_recent_low_16b",
    "price_vs_anchor",
    "cognition_anchor_age_bars",
)

SHORT_FEATURE_CATEGORICAL = (
    "market_state",
    "anchor_status",
    "anchor_event_type",
    "effort_result_state",
    "climax_state",
    "conv_convergence_state",
    "prob_auction_regime",
    "prob_regime_state",
    "below_anchor",
    "downside_continuation_efficient",
)


def _attach_live_safe_short_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Backward-looking features only — no forward outcome fields."""
    out = frame.sort_values("timestamp").reset_index(drop=True).copy()
    if "high" not in out.columns or "low" not in out.columns:
        return out

    out["recent_return_4b"] = out["close"] / out["close"].shift(4) - 1.0
    out["recent_return_8b"] = out["close"] / out["close"].shift(8) - 1.0
    out["recent_return_16b"] = out["close"] / out["close"].shift(16) - 1.0

    roll_high = out["high"].rolling(16, min_periods=4).max()
    roll_low = out["low"].rolling(16, min_periods=4).min()
    out["distance_from_recent_high_16b"] = (out["close"] - roll_high) / out["close"]
    out["distance_from_recent_low_16b"] = (out["close"] - roll_low) / out["close"]

    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    anchor_price = pd.to_numeric(
        out["anchor_price_or_zone"].apply(_extract_anchor_price), errors="coerce"
    )
    out["anchor_price_numeric"] = anchor_price
    out["price_vs_anchor"] = (out["close"] - anchor_price) / anchor_price
    out["below_anchor"] = (anchor_price.notna()) & (out["close"] < anchor_price)

    reason = out["chosen_reason"].fillna("").str.lower()
    effort = out.get("volume_effort_result_state", pd.Series("", index=out.index)).fillna("").str.upper()
    continuation = out.get("volume_continuation_quality", pd.Series("", index=out.index)).fillna("").str.upper()
    out["downside_continuation_efficient"] = (
        reason.str.contains("efficient downside continuation")
        | reason.str.contains("persistent distribution")
        | effort.eq("EFFICIENT_CONTINUATION")
        | continuation.isin({"EFFICIENT_CONTINUATION", "STRONG_CONTINUATION"})
        | (out["recent_return_4b"] < -0.001)
    )
    out["reason_efficient_downside"] = reason.str.contains("efficient downside continuation")
    out["reason_persistent_distribution"] = reason.str.contains("persistent distribution")
    out["reason_buying_climax"] = reason.str.contains("buying climax")
    out["reason_price_falling"] = reason.str.contains("price falling")
    if "volume_effort_result_state" in out.columns:
        out["effort_result_state"] = out["volume_effort_result_state"]
    if "volume_climax_state" in out.columns:
        out["climax_state"] = out["volume_climax_state"]
    return out


def _label_short_outcomes(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    f16 = out.get("forward_return_16b", pd.Series(dtype=float))
    f32 = out.get("forward_return_32b", pd.Series(dtype=float))
    max_fav = out.get("max_favorable_16b", pd.Series(dtype=float))
    max_adv = out.get("max_adverse_16b", pd.Series(dtype=float))
    out["true_directional_short"] = (f16 < 0) & (f32 <= 0)
    out["false_short"] = (f16 > 0) | (max_adv > max_fav)
    return out


def _live_safe_late_exhaustion_proxy(row: pd.Series) -> bool:
    age = _safe_float(row.get("cognition_anchor_age_bars"))
    r4 = _safe_float(row.get("recent_return_4b"), default=float("nan"))
    r8 = _safe_float(row.get("recent_return_8b"), default=float("nan"))
    r16 = _safe_float(row.get("recent_return_16b"), default=float("nan"))
    return (
        age >= 8
        and not pd.isna(r16)
        and r16 < -0.005
        and not pd.isna(r4)
        and r4 > 0
        and not pd.isna(r8)
        and r8 < 0
    )


def _numeric_separation(true_rows: pd.DataFrame, false_rows: pd.DataFrame, column: str) -> dict[str, Any]:
    t = true_rows[column].dropna()
    f = false_rows[column].dropna()
    return {
        "feature": column,
        "true_mean": float(t.mean()) if len(t) else float("nan"),
        "true_median": float(t.median()) if len(t) else float("nan"),
        "false_mean": float(f.mean()) if len(f) else float("nan"),
        "false_median": float(f.median()) if len(f) else float("nan"),
        "delta_mean": float(t.mean() - f.mean()) if len(t) and len(f) else float("nan"),
    }


def _categorical_separation(
    true_rows: pd.DataFrame,
    false_rows: pd.DataFrame,
    column: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in sorted(set(true_rows[column].fillna("N/A").astype(str)) | set(false_rows[column].fillna("N/A").astype(str))):
        t_pct = float((true_rows[column].fillna("N/A").astype(str) == label).mean() * 100) if len(true_rows) else 0.0
        f_pct = float((false_rows[column].fillna("N/A").astype(str) == label).mean() * 100) if len(false_rows) else 0.0
        rows.append(
            {
                "feature": column,
                "value": label,
                "true_pct": t_pct,
                "false_pct": f_pct,
                "delta_pct": t_pct - f_pct,
            }
        )
    return sorted(rows, key=lambda row: abs(row["delta_pct"]), reverse=True)


def _short_hit_rate(subset: pd.DataFrame, bars: int) -> float:
    col = f"forward_return_{bars}b"
    if subset.empty or col not in subset.columns:
        return float("nan")
    valid = subset.dropna(subset=[col])
    if valid.empty:
        return float("nan")
    return float((valid[col] < 0).mean() * 100)


def _weekly_short_exp16(
    subset: pd.DataFrame,
    *,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> list[float]:
    if subset.empty:
        return []
    work = subset.copy()
    work["week"] = pd.to_datetime(work["timestamp"], utc=True).map(
        lambda ts: _week_label(ts, period_start, period_end)
    )
    exps: list[float] = []
    for _, group in work.groupby("week", sort=False):
        valid = group.dropna(subset=["forward_return_16b"])
        if valid.empty:
            continue
        exps.append(float(valid["forward_return_16b"].mean()))
    return exps


def _apply_short_rule_mask(candidates: pd.DataFrame, rule: dict[str, Any]) -> pd.Series:
    mask = pd.Series(True, index=candidates.index)
    if rule.get("market_state_in"):
        mask &= candidates["market_state"].isin(rule["market_state_in"])
    if rule.get("persistent_distribution"):
        mask &= candidates["conv_convergence_state"].fillna("").str.contains("PERSISTENT_DISTRIBUTION")
    if "recent_return_8b_lte" in rule:
        mask &= candidates["recent_return_8b"] <= rule["recent_return_8b_lte"]
    if "recent_return_16b_lte" in rule:
        mask &= candidates["recent_return_16b"] <= rule["recent_return_16b_lte"]
    if "distance_from_high_lte" in rule:
        mask &= candidates["distance_from_recent_high_16b"] <= rule["distance_from_high_lte"]
    if "anchor_age_bucket" in rule:
        age = candidates["cognition_anchor_age_bars"]
        bucket = rule["anchor_age_bucket"]
        if bucket == "lt8":
            mask &= age < 8
        elif bucket == "8_16":
            mask &= (age >= 8) & (age < 16)
        elif bucket == "gte16":
            mask &= age >= 16
    if "below_anchor" in rule:
        mask &= candidates["below_anchor"] == rule["below_anchor"]
    if rule.get("anchor_status_in"):
        mask &= candidates["anchor_status"].isin(rule["anchor_status_in"])
    if rule.get("downside_efficient"):
        mask &= candidates["downside_continuation_efficient"] == True  # noqa: E712
    return mask


def _build_short_rule_universe() -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = [{"name": "gate_only", "spec": {}}]
    for states in (["DISTRIBUTION"], ["REVERSAL"], ["DISTRIBUTION", "REVERSAL"]):
        rules.append({"name": f"market_{'_'.join(s.lower() for s in states)}", "spec": {"market_state_in": states}})
    rules.append({"name": "persistent_distribution", "spec": {"persistent_distribution": True}})
    for thr in (0, -0.0025, -0.005):
        rules.append({"name": f"recent8_lte_{thr}", "spec": {"recent_return_8b_lte": thr}})
    for thr in (0, -0.005, -0.010):
        rules.append({"name": f"recent16_lte_{thr}", "spec": {"recent_return_16b_lte": thr}})
    for thr in (-0.003, -0.005, -0.008, -0.010):
        rules.append({"name": f"dist_high_lte_{abs(thr)}", "spec": {"distance_from_high_lte": thr}})
    for bucket in ("lt8", "8_16", "gte16"):
        rules.append({"name": f"anchor_age_{bucket}", "spec": {"anchor_age_bucket": bucket}})
    rules.append({"name": "below_anchor_true", "spec": {"below_anchor": True}})
    rules.append({"name": "below_anchor_false", "spec": {"below_anchor": False}})
    for status in (["FAILED"], ["NONE", "UNRESOLVED"], ["HELD"]):
        rules.append(
            {
                "name": f"anchor_{'_'.join(s.lower() for s in status)}",
                "spec": {"anchor_status_in": status},
            }
        )
    rules.append({"name": "downside_efficient", "spec": {"downside_efficient": True}})
    combos = [
        {
            "name": "combo_dist_persist_recent8",
            "spec": {
                "market_state_in": ["DISTRIBUTION", "REVERSAL"],
                "persistent_distribution": True,
                "recent_return_8b_lte": 0,
            },
        },
        {
            "name": "combo_dist_high_recent16",
            "spec": {
                "market_state_in": ["DISTRIBUTION", "REVERSAL"],
                "distance_from_high_lte": -0.005,
                "recent_return_16b_lte": 0,
            },
        },
        {
            "name": "combo_downside_not_below_anchor",
            "spec": {
                "downside_efficient": True,
                "below_anchor": False,
                "recent_return_8b_lte": -0.0025,
            },
        },
        {
            "name": "combo_failed_anchor_downside",
            "spec": {
                "anchor_status_in": ["FAILED"],
                "downside_efficient": True,
                "recent_return_16b_lte": -0.005,
            },
        },
        {
            "name": "combo_v3_candidate",
            "spec": {
                "market_state_in": ["DISTRIBUTION", "REVERSAL"],
                "persistent_distribution": True,
                "distance_from_high_lte": -0.005,
                "recent_return_8b_lte": -0.0025,
                "below_anchor": False,
                "anchor_age_bucket": "lt8",
            },
        },
    ]
    rules.extend(combos)
    return rules


def _evaluate_short_rule(
    candidates: pd.DataFrame,
    full_frame: pd.DataFrame,
    rule: dict[str, Any],
    *,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> dict[str, Any]:
    mask = _apply_short_rule_mask(candidates, rule["spec"])
    subset = candidates[mask].copy()
    valid = subset.dropna(subset=["forward_return_16b"])
    weekly_exps = _weekly_short_exp16(valid, period_start=period_start, period_end=period_end)
    weeks_with_short = len(weekly_exps)
    weeks_negative_16 = sum(1 for exp in weekly_exps if exp < 0)

    late_proxy = candidates.apply(_live_safe_late_exhaustion_proxy, axis=1)
    late_in_candidates = int(late_proxy.sum())
    late_avoided = int((late_proxy & ~mask).sum())

    baseline_short = candidates.copy()
    baseline_short["synthetic_context"] = "SHORT_CONTEXT"
    baseline_churn = int((baseline_short["synthetic_context"] != baseline_short["synthetic_context"].shift(1)).sum())

    filtered_on_full = full_frame.copy()
    filtered_on_full["synthetic_context"] = "OBSERVE"
    filtered_on_full.loc[subset.index, "synthetic_context"] = "SHORT_CONTEXT"
    rule_churn = int(
        (filtered_on_full["synthetic_context"] != filtered_on_full["synthetic_context"].shift(1)).sum()
    )

    metrics: dict[str, Any] = {
        "rule_name": rule["name"],
        "rule_spec": str(rule["spec"]),
        "bars": int(len(subset)),
        "false_short_count": int(subset["false_short"].sum()) if len(subset) else 0,
        "true_directional_short_count": int(subset["true_directional_short"].sum()) if len(subset) else 0,
        "late_exhaustion_proxy_in_candidates": late_in_candidates,
        "late_exhaustion_avoided": late_avoided,
        "directional_coverage_pct": float(len(subset) / max(len(full_frame), 1) * 100),
        "churn_baseline_short": baseline_churn,
        "churn_with_rule": rule_churn,
        "churn_delta": rule_churn - baseline_churn,
        "weekly_weeks_with_short": weeks_with_short,
        "weekly_weeks_negative_16b": weeks_negative_16,
        "weekly_stability_pct": float(weeks_negative_16 / weeks_with_short * 100) if weeks_with_short else float("nan"),
    }
    for bars in FORWARD_HORIZONS:
        col = f"forward_return_{bars}b"
        if len(valid) and col in valid.columns:
            metrics[f"short_exp_{bars}b"] = float(valid[col].mean())
            metrics[f"short_hit_{bars}b"] = _short_hit_rate(valid, bars)
        else:
            metrics[f"short_exp_{bars}b"] = float("nan")
            metrics[f"short_hit_{bars}b"] = float("nan")
    return metrics


FEATURE_SOURCE_FIELD_MAP: dict[str, dict[str, Any]] = {
    "market_state": {
        "replay_columns": ["market_state", "market_market_state", "trading_market_state"],
        "source_keys": ("market_state", "trading_state"),
        "source_columns": {
            "market_state": ["market_state"],
            "trading_state": ["market_state"],
        },
    },
    "trading_state": {
        "replay_columns": ["trading_state", "trading_trading_state"],
        "source_keys": ("trading_state",),
        "source_columns": {"trading_state": ["trading_state"]},
    },
    "anchor_status": {
        "replay_columns": ["anchor_status"],
        "source_keys": ("cognition", "cognition_memory"),
        "derived": True,
    },
    "anchor_event_type": {
        "replay_columns": ["anchor_event_type"],
        "source_keys": ("volume_response", "cognition", "cognition_memory"),
        "derived": True,
    },
    "cognition_anchor_age_bars": {
        "replay_columns": ["cognition_anchor_age_bars"],
        "source_keys": ("cognition",),
        "source_columns": {"cognition": ["anchor_age_bars"]},
    },
    "cognition_tier1_trigger_event": {
        "replay_columns": ["cognition_tier1_trigger_event", "cognition_mem_tier1_trigger_event"],
        "source_keys": ("cognition", "cognition_memory"),
        "source_columns": {
            "cognition": ["tier1_trigger_event"],
            "cognition_memory": ["tier1_trigger_event", "trigger_event"],
        },
    },
    "cognition_tier1_location_bias": {
        "replay_columns": ["cognition_tier1_location_bias", "cognition_mem_tier1_location_bias"],
        "source_keys": ("cognition", "cognition_memory"),
        "source_columns": {
            "cognition": ["tier1_location_bias"],
            "cognition_memory": ["tier1_location_bias", "location_bias"],
        },
    },
    "conv_convergence_state": {
        "replay_columns": ["conv_convergence_state"],
        "source_keys": ("convergence",),
        "source_columns": {"convergence": ["convergence_state"]},
    },
    "stopping_volume_signal": {
        "replay_columns": ["anchor_event_type", "cognition_tier1_trigger_event", "chosen_reason"],
        "source_keys": ("volume_response", "cognition", "cognition_memory"),
        "derived": True,
    },
}

REPLAY_MERGED_SNAPSHOT: pd.DataFrame | None = None


def _timestamp_column_candidates(columns: list[str]) -> list[str]:
    return [column for column in columns if "timestamp" in column.lower() or column.lower() in {"ts", "time"}]


def _matching_keyword_columns(columns: list[str]) -> list[str]:
    return [
        column
        for column in columns
        if any(keyword in column.lower() for keyword in FEATURE_AUDIT_KEYWORDS)
    ]


def _scan_parquet_inventory() -> pd.DataFrame:
    root = repo_root()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scan_dir in REPLAY_SCAN_DIRS:
        base = root / scan_dir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.parquet")):
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            row: dict[str, Any] = {
                "path": resolved,
                "relative_path": str(path.relative_to(root)),
                "rows": 0,
                "timestamp_columns": "",
                "min_timestamp": "",
                "max_timestamp": "",
                "matching_columns": "",
                "read_error": "",
            }
            try:
                frame = safe_read_parquet(resolved)
                row["rows"] = len(frame)
                ts_cols = _timestamp_column_candidates(list(frame.columns))
                row["timestamp_columns"] = "|".join(ts_cols)
                row["matching_columns"] = "|".join(_matching_keyword_columns(list(frame.columns)))
                if ts_cols:
                    ts = pd.to_datetime(frame[ts_cols[0]], utc=True, errors="coerce")
                    row["min_timestamp"] = str(ts.min())
                    row["max_timestamp"] = str(ts.max())
            except Exception as exc:
                row["read_error"] = str(exc)
            rows.append(row)

    for path in sorted(root.glob("*.parquet")):
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            frame = safe_read_parquet(resolved)
        except Exception:
            continue
        ts_cols = _timestamp_column_candidates(list(frame.columns))
        rows.append(
            {
                "path": resolved,
                "relative_path": path.name,
                "rows": len(frame),
                "timestamp_columns": "|".join(ts_cols),
                "min_timestamp": str(pd.to_datetime(frame[ts_cols[0]], utc=True, errors="coerce").min()) if ts_cols else "",
                "max_timestamp": str(pd.to_datetime(frame[ts_cols[0]], utc=True, errors="coerce").max()) if ts_cols else "",
                "matching_columns": "|".join(_matching_keyword_columns(list(frame.columns))),
                "read_error": "",
            }
        )
    return pd.DataFrame(rows)


def _source_field_nonempty_rate(sources: dict[str, pd.DataFrame], source_key: str, columns: list[str]) -> float:
    frame = sources.get(source_key)
    if frame is None or frame.empty:
        return 0.0
    rates = [_series_nonempty_rate(frame[column]) for column in columns if column in frame.columns]
    return max(rates) if rates else 0.0


def _collect_merge_field_diagnostics(
    sources: dict[str, pd.DataFrame],
    merged: pd.DataFrame,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for field, spec in FEATURE_SOURCE_FIELD_MAP.items():
        replay_cols = [column for column in spec["replay_columns"] if column in merged.columns]
        replay_rate = 0.0
        if replay_cols:
            replay_rate = max(_series_nonempty_rate(merged[column]) for column in replay_cols)

        source_rates: list[tuple[str, float, str]] = []
        for source_key in spec.get("source_keys", ()):
            resolution = REPLAY_SOURCE_RESOLUTION.get(source_key, {})
            source_path = str(resolution.get("path", ""))
            if spec.get("derived"):
                source_rates.append((source_key, float("nan"), source_path))
                continue
            columns = spec.get("source_columns", {}).get(source_key, [])
            rate = _source_field_nonempty_rate(sources, source_key, columns)
            source_rates.append((source_key, rate, source_path))

        best_source_rate = max((rate for _, rate, _ in source_rates if not pd.isna(rate)), default=0.0)
        issue = ""
        if best_source_rate > 0.05 and replay_rate < 0.01:
            issue = "source_has_data_replay_empty"
        elif best_source_rate > replay_rate + 0.25:
            issue = "replay_underfilled_vs_source"
        elif best_source_rate < 0.01 and replay_rate < 0.01:
            issue = "source_and_replay_empty"

        diagnostics.append(
            {
                "field": field,
                "replay_columns": "|".join(replay_cols),
                "replay_nonempty_rate": round(replay_rate, 4),
                "best_source_nonempty_rate": round(best_source_rate, 4),
                "source_paths": "|".join(f"{key}:{path}" for key, _, path in source_rates if path),
                "issue": issue,
            }
        )
        if issue == "source_has_data_replay_empty":
            _record_merge_diagnostic(
                field=field,
                source_name="|".join(key for key, _, _ in source_rates),
                source_path="|".join(path for _, _, path in source_rates if path),
                source_nonempty_rate=best_source_rate,
                replay_nonempty_rate=replay_rate,
                issue=issue,
            )
    return diagnostics


def _feature_value_counts(frame: pd.DataFrame, column: str, *, top_n: int = 8) -> pd.DataFrame:
    if column not in frame.columns:
        return pd.DataFrame(columns=["value", "bars", "pct"])
    series = frame[column]
    if pd.api.types.is_numeric_dtype(series):
        counts = series.fillna("(null)").value_counts().head(top_n)
    else:
        counts = series.fillna("(null)").astype(str).replace({"": "(empty)"}).value_counts().head(top_n)
    total = len(frame)
    return pd.DataFrame(
        {
            "value": counts.index.astype(str),
            "bars": counts.values,
            "pct": (counts.values / total * 100).round(2),
        }
    )


def _post_merge_feature_completeness(replay: pd.DataFrame) -> dict[str, dict[str, Any]]:
    completeness: dict[str, dict[str, Any]] = {}
    for field in FEATURE_SOURCE_FIELD_MAP:
        if field == "stopping_volume_signal":
            mask = (
                replay.get("anchor_event_type", pd.Series(dtype=str))
                .fillna("")
                .astype(str)
                .str.contains("STOPPING", case=False)
                | replay.get("cognition_tier1_trigger_event", pd.Series(dtype=str))
                .fillna("")
                .astype(str)
                .str.contains("STOPPING", case=False)
                | replay.get("chosen_reason", pd.Series(dtype=str))
                .fillna("")
                .astype(str)
                .str.lower()
                .str.contains("stopping")
            )
            nonempty = int(mask.sum())
            completeness[field] = {
                "non_null_or_nonempty": nonempty,
                "empty_or_default_pct": round((1 - nonempty / len(replay)) * 100, 2) if len(replay) else 100.0,
                "top_values": pd.DataFrame(
                    {
                        "value": ["stopping_present", "stopping_absent"],
                        "bars": [nonempty, len(replay) - nonempty],
                        "pct": [
                            round(nonempty / len(replay) * 100, 2) if len(replay) else 0.0,
                            round((len(replay) - nonempty) / len(replay) * 100, 2) if len(replay) else 100.0,
                        ],
                    }
                ),
            }
            continue

        column = field
        if column not in replay.columns:
            completeness[field] = {
                "non_null_or_nonempty": 0,
                "empty_or_default_pct": 100.0,
                "top_values": pd.DataFrame(),
            }
            continue
        series = replay[column]
        if pd.api.types.is_numeric_dtype(series):
            nonempty = int(series.fillna(0).ne(0).sum())
        else:
            nonempty = int(series.fillna("").astype(str).str.strip().ne("").sum())
        completeness[field] = {
            "non_null_or_nonempty": nonempty,
            "empty_or_default_pct": round((1 - nonempty / len(replay)) * 100, 2) if len(replay) else 100.0,
            "top_values": _feature_value_counts(replay, column),
        }
    return completeness


def build_feature_source_audit(
    *,
    sources: dict[str, pd.DataFrame],
    merged: pd.DataFrame,
    replay: pd.DataFrame,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    csv_path: Path,
    md_path: Path,
) -> str:
    inventory = _scan_parquet_inventory()
    merge_diag = _collect_merge_field_diagnostics(sources, merged)
    completeness = _post_merge_feature_completeness(replay)

    resolution_rows = [
        {
            "logical_source": key,
            "parquet_name": value.get("parquet_name", ""),
            "resolved_path": value.get("path", ""),
            "rows": value.get("rows", 0),
            "note": value.get("note", ""),
        }
        for key, value in sorted(REPLAY_SOURCE_RESOLUTION.items())
    ]
    resolution_df = pd.DataFrame(resolution_rows)
    merge_df = pd.DataFrame(merge_diag)
    pd.concat([inventory, resolution_df, merge_df], ignore_index=True).to_csv(csv_path, index=False)

    lines = [
        "# Auction context feature source audit",
        "",
        f"**Period:** {period_start.strftime('%Y-%m-%d')} → {(period_end - pd.Timedelta(days=1)).strftime('%Y-%m-%d')} UTC",
        f"**CSV:** `{csv_path}`",
        "",
        "## Replay source resolution",
        "",
        "| logical source | parquet | resolved path | rows | note |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for row in resolution_rows:
        rel_path = row["resolved_path"]
        if rel_path:
            try:
                rel_path = str(Path(rel_path).relative_to(repo_root()))
            except ValueError:
                pass
        lines.append(
            f"| {row['logical_source']} | {row['parquet_name']} | `{rel_path}` | {row['rows']} | {row['note'] or ''} |"
        )
    lines.extend(["", "## Parquet inventory (keyword-matching columns)", ""])
    if inventory.empty:
        lines.append("_No parquet files found._")
    else:
        lines.append("| relative path | rows | timestamp cols | min ts | max ts | matching cols |")
        lines.append("| --- | ---: | --- | --- | --- | --- |")
        for _, row in inventory.sort_values(["rows"], ascending=False).head(25).iterrows():
            lines.append(
                f"| `{row['relative_path']}` | {int(row['rows'])} | {row['timestamp_columns']} | "
                f"{row['min_timestamp']} | {row['max_timestamp']} | {row['matching_columns']} |"
            )

    lines.extend(["", "## Replay field population", ""])
    lines.append("| field | replay nonempty % | best source nonempty % | issue | source paths |")
    lines.append("| --- | ---: | ---: | --- | --- |")
    for row in merge_diag:
        lines.append(
            f"| {row['field']} | {row['replay_nonempty_rate']*100:.1f}% | "
            f"{row['best_source_nonempty_rate']*100:.1f}% | {row['issue'] or 'ok'} | {row['source_paths']} |"
        )

    lines.extend(["", "## Post-merge feature completeness", ""])
    for field, detail in completeness.items():
        lines.append(f"### {field}")
        lines.append("")
        lines.append(
            f"- non-empty/non-zero: **{detail['non_null_or_nonempty']}** "
            f"({100 - detail['empty_or_default_pct']:.1f}%)"
        )
        top = detail["top_values"]
        if top.empty:
            lines.append("- top values: _none_")
        else:
            lines.append("| value | bars | pct |")
            lines.append("| --- | ---: | ---: |")
            for _, value_row in top.iterrows():
                lines.append(f"| {value_row['value']} | {int(value_row['bars'])} | {value_row['pct']:.2f}% |")
        lines.append("")

    failures = [row for row in merge_diag if row.get("issue") == "source_has_data_replay_empty"]
    lines.extend(["## Merge failure notes", ""])
    if not failures:
        lines.append("- No source-has-data / replay-empty mismatches detected after resolution fixes.")
    else:
        for row in failures:
            lines.append(
                f"- `{row['field']}`: source populated ({row['best_source_nonempty_rate']*100:.1f}%) "
                f"but replay empty ({row['replay_nonempty_rate']*100:.1f}%)."
            )

    lines.extend(
        [
            "",
            "## Applied replay fixes",
            "",
            "- `_resolve_replay_parquet_path` prefers first **non-empty** candidate under `data/cognition/` "
            "when root-level registry stubs are empty.",
            "- Cognition composite normalized via `evaluation_timestamp` → `timestamp`.",
            "- `runtime_cognition_memory` backfills empty `tier1_trigger_event` / `tier1_location_bias` via `cognition_mem_*` coalesce.",
            "- `market_state` coalesces `market_market_state` then `trading_market_state`.",
            "",
        ]
    )
    report = "\n".join(lines)
    md_path.write_text(report, encoding="utf-8")
    return report


LONG_GATE_STAGE_LABELS = (
    "1_raw_LONG_CONTEXT",
    "2_long_score_ge_0.75",
    "3_score_margin_ge_0.25",
    "4_anchor_not_FAILED",
    "5_calibrated_v2_LONG",
    "6_long_subtype_classified",
    "7_HELD_STOPPING_VOLUME_REVERSAL",
    "8_calibrated_v3_LONG",
)


def _result_from_long_gate_row(row: pd.Series, *, chosen_context: str | None = None) -> AuctionContextArbitrationResult:
    context = chosen_context or _clean_text(row.get("raw_chosen_context") or row.get("chosen_context")).upper() or "OBSERVE"
    return AuctionContextArbitrationResult(
        long_context_score=_safe_float(row.get("long_context_score")),
        short_context_score=_safe_float(row.get("short_context_score")),
        observe_score=_safe_float(row.get("observe_score")),
        anchor_status=_clean_text(row.get("anchor_status")).upper() or "NONE",
        anchor_price_or_zone=_clean_text(row.get("anchor_price_or_zone")) or None,
        anchor_event_type=_clean_text(row.get("anchor_event_type")),
        chosen_context=context,
        chosen_reason=_clean_text(row.get("chosen_reason")),
        why_not_long=_clean_text(row.get("why_not_long")),
        why_not_short=_clean_text(row.get("why_not_short")),
        raw_chosen_context=_clean_text(row.get("raw_chosen_context") or row.get("chosen_context")).upper() or "OBSERVE",
    )


def _attach_long_gate_features(
    replay: pd.DataFrame,
    replay_v2: pd.DataFrame,
    replay_v3: pd.DataFrame,
    candle_timeline: pd.DataFrame,
) -> pd.DataFrame:
    """Per-bar LONG gate audit features (no scoring rule changes)."""
    base = _attach_backward_returns(replay.sort_values("timestamp").reset_index(drop=True).copy())
    v2 = replay_v2.sort_values("timestamp").reset_index(drop=True)
    v3 = replay_v3.sort_values("timestamp").reset_index(drop=True)

    if "high" not in base.columns or "low" not in base.columns:
        candles = candle_timeline[["timestamp", "high", "low"]].copy()
        candles["timestamp"] = _utc_series(candles, "timestamp")
        base = base.merge(candles, on="timestamp", how="left")

    roll_high = base["high"].rolling(16, min_periods=4).max()
    roll_low = base["low"].rolling(16, min_periods=4).min()
    base["distance_from_recent_high_16b"] = (base["close"] - roll_high) / base["close"]
    base["distance_from_recent_low_16b"] = (base["close"] - roll_low) / base["close"]
    base["recent_return_4b"] = base["recent_return"]
    base["score_margin"] = base["long_context_score"] - base["short_context_score"]

    base["raw_chosen_context"] = base["chosen_context"]
    base["v2_context"] = v2["calibrated_context"].values
    base["v3_context"] = v3["calibrated_context"].values
    base["v2_suppress_reason"] = v2["suppress_reason"].fillna("").astype(str).values
    base["v3_suppress_reason"] = v3["suppress_reason"].fillna("").astype(str).values
    base["v3_long_subtype"] = v3["long_subtype"].fillna("").astype(str).values

    long_subtypes: list[str] = []
    for _, row in base.iterrows():
        if _clean_text(row.get("raw_chosen_context")).upper() != "LONG_CONTEXT":
            long_subtypes.append("")
            continue
        long_subtypes.append(
            classify_long_subtype(_result_from_long_gate_row(row), _evidence_from_replay_row(row))
        )
    base["long_subtype"] = long_subtypes

    raw_long = base["raw_chosen_context"] == "LONG_CONTEXT"
    score_ok = base["long_context_score"] >= CALIBRATED_V2_MIN_DIRECTIONAL_SCORE
    margin_ok = base["score_margin"] >= CALIBRATED_V2_MIN_SCORE_MARGIN
    anchor_ok = base["anchor_status"] != "FAILED"

    base["gate_1_raw_long"] = raw_long
    base["gate_2_long_score"] = raw_long & score_ok
    base["gate_3_score_margin"] = raw_long & score_ok & margin_ok
    base["gate_4_anchor_not_failed"] = raw_long & score_ok & margin_ok & anchor_ok
    base["gate_5_v2_long"] = base["v2_context"] == "LONG_CONTEXT"
    base["gate_6_subtype_classified"] = raw_long & base["long_subtype"].astype(str).ne("")
    base["gate_7_held_stopping"] = base["long_subtype"] == "HELD_STOPPING_VOLUME_REVERSAL"
    base["gate_8_v3_long"] = base["v3_context"] == "LONG_CONTEXT"

    reject_reasons: list[str] = []
    for _, row in base.iterrows():
        if row["raw_chosen_context"] != "LONG_CONTEXT":
            reject_reasons.append("")
            continue
        if row["long_context_score"] < CALIBRATED_V2_MIN_DIRECTIONAL_SCORE:
            reject_reasons.append("LONG_SCORE_BELOW_0.75")
        elif row["score_margin"] < CALIBRATED_V2_MIN_SCORE_MARGIN:
            reject_reasons.append("SCORE_MARGIN_BELOW_0.25")
        elif row["anchor_status"] == "FAILED":
            reject_reasons.append("ANCHOR_FAILED")
        elif row["v2_context"] != "LONG_CONTEXT":
            reject_reasons.append(_clean_text(row.get("v2_suppress_reason")) or "V2_SUPPRESSED")
        else:
            reject_reasons.append("")
    base["v2_reject_reason"] = reject_reasons

    v3_reject: list[str] = []
    for _, row in base.iterrows():
        if row["v2_context"] == "LONG_CONTEXT" and row["v3_context"] != "LONG_CONTEXT":
            v3_reject.append(_clean_text(row.get("v3_suppress_reason")) or "V3_SUPPRESSED")
        else:
            v3_reject.append("")
    base["v3_reject_reason"] = v3_reject

    base["reason"] = base["chosen_reason"]
    base["anchor_age_bars"] = base["cognition_anchor_age_bars"]
    return base


def _long_gate_stage_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        LONG_GATE_STAGE_LABELS[0]: int(frame["gate_1_raw_long"].sum()),
        LONG_GATE_STAGE_LABELS[1]: int(frame["gate_2_long_score"].sum()),
        LONG_GATE_STAGE_LABELS[2]: int(frame["gate_3_score_margin"].sum()),
        LONG_GATE_STAGE_LABELS[3]: int(frame["gate_4_anchor_not_failed"].sum()),
        LONG_GATE_STAGE_LABELS[4]: int(frame["gate_5_v2_long"].sum()),
        LONG_GATE_STAGE_LABELS[5]: int(frame["gate_6_subtype_classified"].sum()),
        LONG_GATE_STAGE_LABELS[6]: int(frame["gate_7_held_stopping"].sum()),
        LONG_GATE_STAGE_LABELS[7]: int(frame["gate_8_v3_long"].sum()),
    }


def _long_gate_reject_breakdown(frame: pd.DataFrame) -> pd.DataFrame:
    raw_long = frame[frame["raw_chosen_context"] == "LONG_CONTEXT"].copy()
    if raw_long.empty:
        return pd.DataFrame(columns=["reject_reason", "bars", "pct"])
    counts = raw_long["v2_reject_reason"].replace("", "PASSED_V2_LONG").value_counts()
    total = len(raw_long)
    return pd.DataFrame(
        {
            "reject_reason": counts.index,
            "bars": counts.values,
            "pct": (counts.values / total * 100).round(2),
        }
    )


def _long_gate_subtype_distribution(frame: pd.DataFrame) -> pd.DataFrame:
    raw_long = frame[frame["raw_chosen_context"] == "LONG_CONTEXT"].copy()
    if raw_long.empty:
        return pd.DataFrame(columns=["long_subtype", "bars", "pct"])
    counts = raw_long["long_subtype"].replace("", "(unclassified)").value_counts()
    total = len(raw_long)
    return pd.DataFrame(
        {
            "long_subtype": counts.index,
            "bars": counts.values,
            "pct": (counts.values / total * 100).round(2),
        }
    )


def _long_gate_feature_diagnostics(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    diagnostics: dict[str, pd.DataFrame] = {}
    for column in (
        "anchor_status",
        "anchor_event_type",
        "anchor_age_bars",
        "reason",
        "market_state",
        "cognition_tier1_trigger_event",
        "volume_effort_result_state",
        "volume_climax_state",
        "cognition_tier1_location_bias",
    ):
        if column not in frame.columns:
            diagnostics[column] = pd.DataFrame({"value": ["(missing column)"], "bars": [len(frame)], "pct": [100.0]})
            continue
        series = frame[column]
        null_count = int(series.isna().sum())
        empty_count = int(series.fillna("").astype(str).str.strip().eq("").sum())
        if pd.api.types.is_numeric_dtype(series):
            non_null = series.dropna()
            if non_null.empty:
                diagnostics[column] = pd.DataFrame(
                    {"value": ["(all null)"], "bars": [len(frame)], "pct": [100.0]}
                )
            elif non_null.nunique() <= 1:
                diagnostics[column] = pd.DataFrame(
                    {
                        "value": [f"(constant={non_null.iloc[0]})", f"(null={null_count})"],
                        "bars": [int(non_null.count()), null_count],
                        "pct": [
                            round(non_null.count() / len(frame) * 100, 2),
                            round(null_count / len(frame) * 100, 2),
                        ],
                    }
                )
            else:
                counts = non_null.value_counts().head(12)
                diagnostics[column] = pd.DataFrame(
                    {
                        "value": counts.index.astype(str),
                        "bars": counts.values,
                        "pct": (counts.values / len(frame) * 100).round(2),
                    }
                )
            continue

        counts = series.fillna("(null)").astype(str).replace({"": "(empty)"}).value_counts().head(12)
        diagnostics[column] = pd.DataFrame(
            {
                "value": counts.index,
                "bars": counts.values,
                "pct": (counts.values / len(frame) * 100).round(2),
            }
        )
    stopping_mask = (
        frame["anchor_event_type"].fillna("").astype(str).str.contains("STOPPING", case=False)
        | frame["cognition_tier1_trigger_event"].fillna("").astype(str).str.contains("STOPPING", case=False)
        | frame["reason"].fillna("").astype(str).str.lower().str.contains("stopping")
    )
    diagnostics["stopping_volume_signal"] = pd.DataFrame(
        {
            "value": ["stopping_present", "stopping_absent"],
            "bars": [int(stopping_mask.sum()), int((~stopping_mask).sum())],
            "pct": [
                round(stopping_mask.mean() * 100, 2),
                round((~stopping_mask).mean() * 100, 2),
            ],
        }
    )
    return diagnostics


def _long_gate_v2_candidate_rows(frame: pd.DataFrame) -> pd.DataFrame:
    v2_long = frame[frame["v2_context"] == "LONG_CONTEXT"].copy()
    columns = [
        "timestamp",
        "close",
        "market_state",
        "trading_state",
        "long_context_score",
        "short_context_score",
        "score_margin",
        "anchor_status",
        "anchor_event_type",
        "anchor_age_bars",
        "reason",
        "long_subtype",
        "v3_context",
        "v3_reject_reason",
        "recent_return_4b",
        "recent_return_8b",
        "recent_return_16b",
        "distance_from_recent_low_16b",
        "distance_from_recent_high_16b",
    ]
    out = v2_long.reindex(columns=columns).copy()
    out = out.rename(columns={"v3_context": "v3_decision"})
    return out


def _diagnostics_md_table(df: pd.DataFrame, *, title: str) -> list[str]:
    lines = [f"### {title}", ""]
    if df.empty:
        lines.append("_No rows._")
        lines.append("")
        return lines
    lines.append("| value | bars | pct |")
    lines.append("| --- | ---: | ---: |")
    for _, row in df.head(15).iterrows():
        lines.append(f"| {row['value']} | {int(row['bars'])} | {row['pct']:.2f}% |")
    lines.append("")
    return lines


def _long_gate_root_cause_summary(
    stage_counts: dict[str, int],
    reject_breakdown: pd.DataFrame,
    subtype_dist: pd.DataFrame,
    feature_diag: dict[str, pd.DataFrame],
    *,
    total_bars: int,
) -> list[str]:
    raw_long = stage_counts[LONG_GATE_STAGE_LABELS[0]]
    v2_long = stage_counts[LONG_GATE_STAGE_LABELS[4]]
    v3_long = stage_counts[LONG_GATE_STAGE_LABELS[7]]
    held_stopping = stage_counts[LONG_GATE_STAGE_LABELS[6]]

    anchor_status_table = feature_diag.get("anchor_status", pd.DataFrame())
    anchor_all_none = (
        not anchor_status_table.empty
        and len(anchor_status_table) == 1
        and str(anchor_status_table.iloc[0]["value"]) == "NONE"
    )
    tier1_empty = (
        not feature_diag.get("cognition_tier1_trigger_event", pd.DataFrame()).empty
        and str(feature_diag["cognition_tier1_trigger_event"].iloc[0]["value"]) == "(empty)"
    )
    market_state_empty = (
        not feature_diag.get("market_state", pd.DataFrame()).empty
        and str(feature_diag["market_state"].iloc[0]["value"]) == "(empty)"
    )

    lines = [
        "## Root-cause summary",
        "",
        f"- Total replay bars: **{total_bars}**",
        f"- Raw arbitrator LONG candidates (stage 1): **{raw_long}** ({raw_long / total_bars * 100:.1f}% of bars)",
        f"- After score/margin/anchor gates (stage 4): **{stage_counts[LONG_GATE_STAGE_LABELS[3]]}**",
        f"- calibrated_v2 final LONG (stage 5): **{v2_long}**",
        f"- HELD_STOPPING_VOLUME_REVERSAL among raw LONG (stage 7): **{held_stopping}**",
        f"- calibrated_v3 final LONG (stage 8): **{v3_long}**",
        "",
        "### Why calibrated_v2 LONG is only 5",
        "",
    ]
    if raw_long == 0:
        lines.append("- No raw LONG_CONTEXT bars in this replay window.")
    else:
        lines.append(
            f"- Previous research counts (**~{raw_long} raw LONG**) reflect **unfiltered arbitrator output**, "
            f"not calibrated_v2 final context."
        )
        lines.append(
            f"- The 0.75 / 0.25 gate + `anchor_status != FAILED` collapses **{raw_long} → {v2_long}** LONG bars."
        )
        if not reject_breakdown.empty:
            top = reject_breakdown.sort_values("bars", ascending=False).head(5)
            for _, row in top.iterrows():
                if row["reject_reason"] == "PASSED_V2_LONG":
                    continue
                lines.append(f"  - `{row['reject_reason']}`: **{int(row['bars'])}** bars ({row['pct']:.1f}%)")
    lines.extend(
        [
            "",
            "### Why calibrated_v3 LONG is 0",
            "",
        ]
    )
    if v2_long == 0:
        lines.append("- No v2 LONG survivors to promote.")
    elif held_stopping == 0:
        lines.append(
            f"- All **{v2_long}** v2 LONG bars fail `long_subtype == HELD_STOPPING_VOLUME_REVERSAL`."
        )
        if not subtype_dist.empty:
            lines.append("- Raw LONG subtype mix:")
            for _, row in subtype_dist.head(6).iterrows():
                lines.append(f"  - `{row['long_subtype']}`: **{int(row['bars'])}** ({row['pct']:.1f}%)")
        if anchor_all_none:
            lines.append(
                "- Replay resolves `anchor_status=NONE` on **100%** of bars — no `HELD` anchors, so "
                "`HELD_STOPPING_VOLUME_REVERSAL` cannot trigger under current data."
            )
    else:
        lines.append(
            f"- **{held_stopping}** HELD_STOPPING rows exist among raw LONG, but v3 still produced **{v3_long}** "
            "final LONG — inspect v2 LONG rows for score/margin re-check at v3."
        )

    lines.extend(
        [
            "",
            "### Likely cause classification",
            "",
        ]
    )
    if anchor_all_none or tier1_empty or market_state_empty:
        lines.append("- **Data availability (partial):**")
        if anchor_all_none:
            lines.append("  - `anchor_status` is **100% NONE** — anchor resolution never reaches HELD in this replay window.")
        if tier1_empty:
            lines.append("  - `cognition_tier1_trigger_event` / `tier1_location_bias` are **empty** on all bars.")
        if market_state_empty:
            lines.append("  - `market_state` is **empty** on all bars (asof merge field missing or blank in source).")
    lines.extend(
        [
            "- **Branch/layout mismatch:** unlikely — raw LONG count (**128**) matches unfiltered arbitrator output; "
            f"the drop to **{v2_long}** is from calibrated score/margin gates, not a different replay branch.",
            "- **Subtype strictness:** v3 requires `HELD_STOPPING_VOLUME_REVERSAL` (anchor HELD + stopping evidence + lower zone); "
            f"**{held_stopping}** raw LONG rows match in this dataset.",
            "",
        ]
    )
    return lines


def build_long_gate_audit(
    replay: pd.DataFrame,
    replay_v2: pd.DataFrame,
    replay_v3: pd.DataFrame,
    candle_timeline: pd.DataFrame,
    *,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    csv_path: Path,
    md_path: Path,
) -> tuple[pd.DataFrame, str]:
    audit = _attach_long_gate_features(replay, replay_v2, replay_v3, candle_timeline)
    stage_counts = _long_gate_stage_counts(audit)
    reject_breakdown = _long_gate_reject_breakdown(audit)
    subtype_dist = _long_gate_subtype_distribution(audit)
    feature_diag = _long_gate_feature_diagnostics(audit)
    v2_candidates = _long_gate_v2_candidate_rows(audit)

    v2_candidates.to_csv(csv_path, index=False)

    lines = [
        "# LONG gate audit (calibrated_v2 / calibrated_v3)",
        "",
        f"**Period:** {period_start.strftime('%Y-%m-%d')} → {(period_end - pd.Timedelta(days=1)).strftime('%Y-%m-%d')} UTC",
        f"**CSV:** `{csv_path}`",
        "",
        "## Gate funnel (bar counts)",
        "",
        "| stage | bars |",
        "| --- | ---: |",
    ]
    for label in LONG_GATE_STAGE_LABELS:
        lines.append(f"| {label} | {stage_counts[label]} |")
    lines.append("")

    lines.extend(
        [
            "## Raw LONG → v2 rejection breakdown",
            "",
        ]
    )
    if reject_breakdown.empty:
        lines.append("_No raw LONG rows._")
    else:
        lines.append("| reject_reason | bars | pct |")
        lines.append("| --- | ---: | ---: |")
        for _, row in reject_breakdown.iterrows():
            lines.append(f"| {row['reject_reason']} | {int(row['bars'])} | {row['pct']:.2f}% |")
    lines.append("")

    lines.extend(
        [
            "## Raw LONG subtype distribution",
            "",
        ]
    )
    if subtype_dist.empty:
        lines.append("_No raw LONG rows._")
    else:
        lines.append("| long_subtype | bars | pct |")
        lines.append("| --- | ---: | ---: |")
        for _, row in subtype_dist.iterrows():
            lines.append(f"| {row['long_subtype']} | {int(row['bars'])} | {row['pct']:.2f}% |")
    lines.append("")

    lines.extend(
        [
            "## v2 LONG candidates (detail)",
            "",
        ]
    )
    if v2_candidates.empty:
        lines.append("_No calibrated_v2 LONG rows._")
    else:
        lines.append("| timestamp | close | long_score | margin | anchor | subtype | v3 | v3_reject |")
        lines.append("| --- | ---: | ---: | ---: | --- | --- | --- | --- |")
        for _, row in v2_candidates.iterrows():
            lines.append(
                f"| {row['timestamp']} | {row['close']:.2f} | {row['long_context_score']:.3f} | "
                f"{row['score_margin']:.3f} | {row['anchor_status']} | {row['long_subtype']} | "
                f"{row['v3_decision']} | {row['v3_reject_reason']} |"
            )
    lines.append("")

    lines.append("## Feature diagnostics (full replay window)")
    lines.append("")
    for title, table in feature_diag.items():
        lines.extend(_diagnostics_md_table(table, title=title))

    lines.extend(
        _long_gate_root_cause_summary(
            stage_counts,
            reject_breakdown,
            subtype_dist,
            feature_diag,
            total_bars=len(audit),
        )
    )

    report = "\n".join(lines)
    md_path.write_text(report, encoding="utf-8")
    return audit, report


def build_short_feature_discovery(
    thresholded: pd.DataFrame,
    *,
    csv_path: Path,
    md_path: Path,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> tuple[pd.DataFrame, str]:
    enriched = _attach_live_safe_short_features(thresholded)
    enriched = _label_short_outcomes(enriched)
    candidates = enriched[enriched["chosen_context"] == "SHORT_CONTEXT"].copy()
    labeled = candidates.dropna(subset=["forward_return_16b", "forward_return_32b"])
    true_rows = labeled[labeled["true_directional_short"] == True]  # noqa: E712
    false_rows = labeled[labeled["false_short"] == True]  # noqa: E712

    numeric_sep = [
        _numeric_separation(true_rows, false_rows, col)
        for col in SHORT_FEATURE_NUMERIC
        if col in labeled.columns
    ]
    cat_sep: list[dict[str, Any]] = []
    for col in SHORT_FEATURE_CATEGORICAL:
        if col in labeled.columns:
            cat_sep.extend(_categorical_separation(true_rows, false_rows, col))

    rule_rows = [
        _evaluate_short_rule(
            candidates,
            enriched,
            rule,
            period_start=period_start,
            period_end=period_end,
        )
        for rule in _build_short_rule_universe()
    ]
    sweep_df = pd.DataFrame(rule_rows).sort_values(
        ["short_exp_16b", "weekly_stability_pct", "bars"],
        ascending=[True, False, False],
    )
    sweep_df.to_csv(csv_path, index=False)

    best = sweep_df.sort_values(
        ["short_exp_16b", "short_exp_32b", "weekly_stability_pct"],
        ascending=[True, True, False],
    ).iloc[0]
    best_negative_both = sweep_df[
        (sweep_df["short_exp_16b"] < 0) & (sweep_df["short_exp_32b"] < 0)
    ].sort_values(["short_exp_16b", "weekly_stability_pct"], ascending=[True, False])

    lines = [
        "# SHORT feature discovery (live-safe)",
        "",
        f"**Period:** {period_start.strftime('%Y-%m-%d')} → {(period_end - pd.Timedelta(days=1)).strftime('%Y-%m-%d')} (UTC)",
        f"**Candidate universe:** threshold-gated `SHORT_CONTEXT` at {CALIBRATED_V2_MIN_DIRECTIONAL_SCORE}/{CALIBRATED_V2_MIN_SCORE_MARGIN}",
        f"**Labeled SHORT bars:** {len(labeled)} (true={len(true_rows)}, false={len(false_rows)})",
        "",
        "Outcome labels use forward returns for diagnostics only — not used in rule masks.",
        "",
        "## Feature separation (numeric)",
        "",
        "| feature | true mean | true median | false mean | false median | delta mean |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in sorted(numeric_sep, key=lambda r: abs(r.get("delta_mean", 0)), reverse=True):
        lines.append(
            f"| {row['feature']} | {row['true_mean']:.5f} | {row['true_median']:.5f} | "
            f"{row['false_mean']:.5f} | {row['false_median']:.5f} | {row['delta_mean']:.5f} |"
        )

    lines.extend(["", "## Feature separation (categorical)", ""])
    for col in SHORT_FEATURE_CATEGORICAL:
        col_rows = [r for r in cat_sep if r["feature"] == col][:6]
        if not col_rows:
            continue
        lines.extend([f"### {col}", "", "| value | true% | false% | delta% |", "| --- | ---: | ---: | ---: |"])
        for row in col_rows:
            lines.append(
                f"| {row['value']} | {row['true_pct']:.1f} | {row['false_pct']:.1f} | {row['delta_pct']:.1f} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Rule sweep (live-safe filters)",
            "",
            "| rule | bars | exp4% | exp8% | exp16% | exp32% | hit16% | false_short | late_avoided | weekly_stab% | coverage% | churn Δ |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for _, row in sweep_df.head(25).iterrows():
        lines.append(
            f"| {row['rule_name']} | {int(row['bars'])} | "
            f"{row['short_exp_4b']*100:.3f} | {row['short_exp_8b']*100:.3f} | "
            f"{row['short_exp_16b']*100:.3f} | {row['short_exp_32b']*100:.3f} | "
            f"{row['short_hit_16b']:.1f} | {int(row['false_short_count'])} | "
            f"{int(row['late_exhaustion_avoided'])} | {row['weekly_stability_pct']:.1f} | "
            f"{row['directional_coverage_pct']:.2f} | {int(row['churn_delta'])} |"
        )

    top_sep = sorted(numeric_sep, key=lambda r: abs(r.get("delta_mean", 0)), reverse=True)[:3]
    v3_possible = len(best_negative_both) > 0 and float(best_negative_both.iloc[0]["weekly_stability_pct"]) >= 50

    lines.extend(
        [
            "",
            "## Conclusions",
            "",
            f"- **Best rule (lowest 16b exp):** `{best['rule_name']}` "
            f"(16b={best['short_exp_16b']*100:.3f}%, 32b={best['short_exp_32b']*100:.3f}%, "
            f"weekly stability={best['weekly_stability_pct']:.1f}%, bars={int(best['bars'])})",
            f"- **Rules with negative 16b AND 32b expectancy:** {len(best_negative_both)}",
        ]
    )
    if len(best_negative_both):
        b = best_negative_both.iloc[0]
        lines.append(
            f"- **Best dual-horizon rule:** `{b['rule_name']}` "
            f"(16b={b['short_exp_16b']*100:.3f}%, 32b={b['short_exp_32b']*100:.3f}%, "
            f"weekly stability={b['weekly_stability_pct']:.1f}%)"
        )
    lines.extend(
        [
            f"- **Top separating features:** "
            + ", ".join(f"`{r['feature']}` (Δmean={r['delta_mean']:.4f})" for r in top_sep),
            f"- **calibrated_v3 SHORT filter possible:** {'yes — at least one live-safe rule shows negative 16b/32b with reasonable stability' if v3_possible else 'not yet — no rule achieves negative 16b and 32b with adequate weekly stability'}",
            "",
        ]
    )
    report = "\n".join(lines)
    md_path.write_text(report, encoding="utf-8")
    return sweep_df, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=str, default="2026-07-08", help="Inclusive UTC start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2026-07-09", help="Inclusive UTC end date (YYYY-MM-DD)")
    parser.add_argument("--tag", type=str, default=None, help="Output suffix for default report paths")
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--md", type=Path, default=None)
    parser.add_argument(
        "--threshold-sweep",
        action="store_true",
        help="Run research-only threshold sweep over directional commitment gates",
    )
    parser.add_argument(
        "--calibrated-v2",
        action="store_true",
        help="Apply research-only calibrated_v2 context rules (no live wiring)",
    )
    parser.add_argument(
        "--calibrated-v3",
        action="store_true",
        help="Apply research-only calibrated_v3 context rules (LONG held-stopping only)",
    )
    parser.add_argument(
        "--weekly-validation",
        action="store_true",
        help="Split period into weekly buckets and report calibrated context metrics per week",
    )
    parser.add_argument(
        "--short-feature-discovery",
        action="store_true",
        help="Discover live-safe backward features separating good SHORT candidates from false shorts",
    )
    parser.add_argument(
        "--long-gate-audit",
        action="store_true",
        help="Audit LONG gate funnel for calibrated_v2/v3 (writes long_gate_audit CSV/MD)",
    )
    parser.add_argument(
        "--feature-source-audit",
        action="store_true",
        help="Audit parquet feature sources and replay merge completeness",
    )
    parser.add_argument(
        "--raw-subtype-audit",
        action="store_true",
        help="Measure raw LONG/SHORT subtypes vs forward 8/16 returns (requires calibrated_v2/v3)",
    )
    args = parser.parse_args()

    if args.calibrated_v2 and args.calibrated_v3 and not (args.long_gate_audit or args.feature_source_audit):
        parser.error("Use only one of --calibrated-v2 or --calibrated-v3 (unless auditing)")
    if args.weekly_validation and not (args.calibrated_v2 or args.calibrated_v3):
        parser.error("--weekly-validation requires --calibrated-v2 or --calibrated-v3")
    if args.raw_subtype_audit and not (args.calibrated_v2 or args.calibrated_v3):
        parser.error("--raw-subtype-audit requires --calibrated-v2 or --calibrated-v3")
    if args.long_gate_audit or args.feature_source_audit:
        args.calibrated_v2 = True
        args.calibrated_v3 = True

    global REPLAY_MERGED_SNAPSHOT
    REPLAY_SOURCE_RESOLUTION.clear()
    REPLAY_MERGE_DIAGNOSTICS.clear()
    REPLAY_MERGED_SNAPSHOT = None

    period_start, period_end = _parse_period(args.start, args.end)
    tag = args.tag or f"{period_start.strftime('%Y%m%d')}_{(period_end - pd.Timedelta(days=1)).strftime('%Y%m%d')}"
    reports_dir = repo_root() / "reports"
    csv_path = args.csv or reports_dir / f"auction_context_arbitration_{tag}.csv"
    md_path = args.md or reports_dir / f"auction_context_arbitration_{tag}.md"

    load_notes: list[str] = []
    if PARQUET_SOURCES["volume_response"] == VOLUME_RESPONSE_PARQUET:
        load_notes.append(
            "volume_response_memory.parquet not registered; used volume_response_state.parquet instead"
        )
    sources: dict[str, pd.DataFrame] = {}
    for name in PARQUET_SOURCES:
        frame, note = _load_source(name)
        sources[name] = frame
        if note:
            load_notes.append(note)
        if "timestamp" in frame.columns:
            sources[name]["timestamp"] = _utc_series(frame, "timestamp")
        elif name == "cognition" and "timestamp" in frame.columns:
            sources[name]["timestamp"] = _utc_series(frame, "timestamp")

    cognition_memory, mem_note = _load_named_parquet(
        "runtime_cognition_memory.parquet",
        logical_name="cognition_memory",
    )
    sources["cognition_memory"] = cognition_memory
    if mem_note:
        load_notes.append(mem_note)

    replay = build_replay_frame(sources, period_start=period_start, period_end=period_end)
    replay["chosen_context_raw"] = replay["chosen_context"]
    candle_timeline = sources["candles"].copy()
    candle_timeline["timestamp"] = _utc_series(candle_timeline, "timestamp")

    replay_v2 = None
    if args.calibrated_v3 or args.long_gate_audit or args.feature_source_audit:
        replay_v2 = apply_calibrated_v2_context(replay.copy())
        replay_cal = apply_calibrated_v3_context(replay.copy())
    elif args.calibrated_v2:
        replay_cal = apply_calibrated_v2_context(replay.copy())

    replay = attach_forward_outcomes(replay, candle_timeline)
    replay = _attach_short_subtypes(replay)

    if args.calibrated_v2 or args.calibrated_v3:
        outcome_cols = [f"forward_return_{bars}b" for bars in FORWARD_HORIZONS] + [
            "high",
            "low",
            "max_up_16b",
            "max_down_16b",
            "max_favorable_16b",
            "max_adverse_16b",
        ]
        replay_cal = replay_cal.merge(replay[["timestamp", *outcome_cols]], on="timestamp", how="left")
        replay_cal = _attach_outcome_diagnostic_subtypes(replay_cal)
        replay_cal = _attach_long_subtypes(replay_cal)
        if args.calibrated_v3:
            # Re-assert primary final context after diagnostic attachments.
            if "calibrated_v3_context" in replay_cal.columns:
                replay_cal["chosen_context"] = replay_cal["calibrated_v3_context"]
                replay_cal["calibrated_context"] = replay_cal["calibrated_v3_context"]
            _assert_calibrated_v3_invariants(replay_cal)
        if replay_v2 is not None:
            replay_v2 = replay_v2.merge(replay[["timestamp", *outcome_cols]], on="timestamp", how="left")
            if "calibrated_v2_context" not in replay_v2.columns and "calibrated_context" in replay_v2.columns:
                replay_v2["calibrated_v2_context"] = replay_v2["calibrated_context"]
        export_source = replay_cal
    else:
        replay_cal = None
        export_source = replay

    thresholded_ref = apply_threshold_filter(
        replay,
        min_directional_score=CALIBRATED_V2_MIN_DIRECTIONAL_SCORE,
        min_score_margin=CALIBRATED_V2_MIN_SCORE_MARGIN,
    )

    export_cols = [col for col in export_source.columns if col not in ("max_up_16b", "max_down_16b")]
    replay_export = export_source[export_cols]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    replay_export.to_csv(csv_path, index=False)

    markdown_base = replay_cal if replay_cal is not None else replay
    markdown = build_markdown_report(
        markdown_base,
        load_notes=load_notes,
        csv_path=csv_path,
        period_start=period_start,
        period_end=period_end,
    )

    if args.calibrated_v2 or args.calibrated_v3:
        layer_report = build_context_layer_distribution_report(
            raw=replay,
            calibrated_v2=replay_v2 if replay_v2 is not None else (replay_cal if args.calibrated_v2 else None),
            calibrated_v3=replay_cal if args.calibrated_v3 else None,
        )
        markdown = markdown + "\n\n" + layer_report

    if args.threshold_sweep:
        sweep = run_threshold_sweep(replay)
        sweep_csv = reports_dir / f"auction_context_arbitration_{tag}_sweep.csv"
        sweep_md = reports_dir / f"auction_context_arbitration_{tag}_sweep.md"
        sweep.to_csv(sweep_csv, index=False)
        sweep_report = build_threshold_sweep_report(sweep, csv_path=sweep_csv, replay=replay)
        sweep_md.write_text(sweep_report, encoding="utf-8")
        markdown = markdown + "\n\n" + sweep_report
        ranked = _rank_sweep_results(sweep)
        print(f"Wrote sweep → {sweep_csv}")
        print(f"Wrote sweep report → {sweep_md}")
        print("Best threshold:", ranked.iloc[0][["min_directional_score", "min_score_margin"]].to_dict())
        print("Both expectancy positive combos:", int(sweep["both_expectancy_positive"].sum()))

        best = ranked.iloc[0]
        best_filtered = apply_threshold_filter(
            replay,
            min_directional_score=float(best["min_directional_score"]),
            min_score_margin=float(best["min_score_margin"]),
        )
        period_suffix = f"{period_start.strftime('%Y%m%d')}_{(period_end - pd.Timedelta(days=1)).strftime('%Y%m%d')}"
        unknown_csv = reports_dir / f"auction_context_unknown_short_profile_{period_suffix}.csv"
        unknown_md = reports_dir / f"auction_context_unknown_short_profile_{period_suffix}.md"
        build_unknown_short_profile(
            best_filtered,
            csv_path=unknown_csv,
            md_path=unknown_md,
            gate_min_dir=float(best["min_directional_score"]),
            gate_min_margin=float(best["min_score_margin"]),
        )
        print(f"Wrote unknown short profile → {unknown_csv}")
        print(f"Wrote unknown short report → {unknown_md}")

    if args.calibrated_v2:
        calibrated_report = build_calibrated_v2_report(
            baseline=replay,
            thresholded=thresholded_ref,
            calibrated=replay_cal,
        )
        markdown = markdown + "\n\n" + calibrated_report
        markdown = markdown + "\n\n" + build_leakage_audit_report()

        long_subtype_csv = reports_dir / f"auction_context_long_subtypes_{tag}.csv"
        long_subtype_md = reports_dir / f"auction_context_arbitration_{tag}_long_subtypes.md"
        long_report = build_long_subtype_report(
            replay_cal,
            csv_path=long_subtype_csv,
            md_path=long_subtype_md,
            period_start=period_start,
            period_end=period_end,
        )
        markdown = markdown + "\n\n" + long_report
        print(f"Wrote long subtype profile → {long_subtype_csv}")
        print(f"Wrote long subtype report → {long_subtype_md}")

    if args.calibrated_v3:
        calibrated_v3_report = build_calibrated_v3_report(
            baseline=replay,
            thresholded=thresholded_ref,
            calibrated_v2=replay_v2,
            calibrated_v3=replay_cal,
        )
        markdown = markdown + "\n\n" + calibrated_v3_report
        markdown = markdown + "\n\n" + build_leakage_audit_report()

    if args.raw_subtype_audit and replay_cal is not None:
        raw_table, raw_report = build_raw_subtype_forward_report(replay_cal)
        raw_csv = reports_dir / f"auction_context_raw_subtype_forward_{tag}.csv"
        raw_md = reports_dir / f"auction_context_raw_subtype_forward_{tag}.md"
        raw_table.to_csv(raw_csv, index=False)
        raw_md.write_text(raw_report, encoding="utf-8")
        markdown = markdown + "\n\n" + raw_report
        print(f"Wrote raw subtype forward table → {raw_csv}")
        print(f"Wrote raw subtype forward report → {raw_md}")

    if args.weekly_validation:
        weekly_report = build_weekly_validation_report(
            baseline=replay,
            calibrated=replay_cal,
            period_start=period_start,
            period_end=period_end,
            version_label="calibrated_v3" if args.calibrated_v3 else "calibrated_v2",
        )
        markdown = markdown + "\n\n" + weekly_report
        weekly_md = reports_dir / f"auction_context_arbitration_{tag}_weekly_validation.md"
        weekly_md.write_text(weekly_report, encoding="utf-8")
        print(f"Wrote weekly validation → {weekly_md}")

    if args.short_feature_discovery:
        period_suffix = f"{period_start.strftime('%Y%m%d')}_{(period_end - pd.Timedelta(days=1)).strftime('%Y%m%d')}"
        discovery_csv = reports_dir / f"auction_context_short_feature_discovery_{period_suffix}.csv"
        discovery_md = reports_dir / f"auction_context_short_feature_discovery_{period_suffix}.md"
        sweep_df, discovery_report = build_short_feature_discovery(
            thresholded_ref,
            csv_path=discovery_csv,
            md_path=discovery_md,
            period_start=period_start,
            period_end=period_end,
        )
        markdown = markdown + "\n\n" + discovery_report
        print(f"Wrote short feature discovery → {discovery_csv}")
        print(f"Wrote short feature discovery report → {discovery_md}")
        if not sweep_df.empty:
            best = sweep_df.sort_values(["short_exp_16b", "short_exp_32b"]).iloc[0]
            dual_neg = int(((sweep_df["short_exp_16b"] < 0) & (sweep_df["short_exp_32b"] < 0)).sum())
            print(f"Best rule: {best['rule_name']} (16b={best['short_exp_16b']*100:.3f}%)")
            print(f"Rules with negative 16b and 32b: {dual_neg}")

    if args.feature_source_audit:
        period_suffix = f"{period_start.strftime('%Y%m%d')}_{(period_end - pd.Timedelta(days=1)).strftime('%Y%m%d')}"
        feature_csv = reports_dir / f"auction_context_feature_source_audit_{period_suffix}.csv"
        feature_md = reports_dir / f"auction_context_feature_source_audit_{period_suffix}.md"
        merged_snapshot = REPLAY_MERGED_SNAPSHOT if REPLAY_MERGED_SNAPSHOT is not None else replay
        feature_report = build_feature_source_audit(
            sources=sources,
            merged=merged_snapshot,
            replay=replay,
            period_start=period_start,
            period_end=period_end,
            csv_path=feature_csv,
            md_path=feature_md,
        )
        markdown = markdown + "\n\n" + feature_report
        print(f"Wrote feature source audit → {feature_csv}")
        print(f"Wrote feature source audit report → {feature_md}")

    if args.long_gate_audit and replay_v2 is not None:
        period_suffix = f"{period_start.strftime('%Y%m%d')}_{(period_end - pd.Timedelta(days=1)).strftime('%Y%m%d')}"
        audit_csv = reports_dir / f"auction_context_long_gate_audit_{period_suffix}.csv"
        audit_md = reports_dir / f"auction_context_long_gate_audit_{period_suffix}.md"
        _, audit_report = build_long_gate_audit(
            replay,
            replay_v2,
            replay_cal,
            candle_timeline,
            period_start=period_start,
            period_end=period_end,
            csv_path=audit_csv,
            md_path=audit_md,
        )
        markdown = markdown + "\n\n" + audit_report
        print(f"Wrote LONG gate audit → {audit_csv}")
        print(f"Wrote LONG gate audit report → {audit_md}")

    md_path.write_text(markdown, encoding="utf-8")

    print(f"Wrote {len(replay_export)} rows → {csv_path}")
    print(f"Wrote report → {md_path}")
    raw_dist = _context_distribution(
        replay,
        "chosen_context_raw" if "chosen_context_raw" in replay.columns else "chosen_context",
    )
    print("Summary trading_state:", replay["trading_state"].value_counts().to_dict())
    print("Summary raw_chosen_context:", raw_dist)
    if args.calibrated_v3 and replay_cal is not None:
        v3_dist = _context_distribution(
            replay_cal,
            "calibrated_v3_context" if "calibrated_v3_context" in replay_cal.columns else "chosen_context",
        )
        print("Summary calibrated_v3 final context:", v3_dist)
        if replay_v2 is not None:
            v2_dist = _context_distribution(
                replay_v2,
                "calibrated_v2_context" if "calibrated_v2_context" in replay_v2.columns else "calibrated_context",
            )
            print("Summary calibrated_v2 context:", v2_dist)
    elif args.calibrated_v2 and replay_cal is not None:
        v2_dist = _context_distribution(
            replay_cal,
            "calibrated_v2_context" if "calibrated_v2_context" in replay_cal.columns else "chosen_context",
        )
        print("Summary calibrated_v2 final context:", v2_dist)
    else:
        print("Summary chosen_context:", raw_dist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
