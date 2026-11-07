"""Shadow-only calibrated_v3 auction context arbitration engine.

Observes live cognition memories and appends calibrated_v3 context rows.
Does not modify trading_state, emit trade signals, or drive execution.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.cognition.auction_context_arbitrator import (  # noqa: E402
    AuctionContextEvidence,
    compute_recent_return,
    resolve_anchor_price,
    resolve_anchor_status,
    score_auction_context,
)
from parquet_utils import append_state_row, safe_read_parquet  # noqa: E402

MEMORY_FILE = "auction_context_arbitration_memory.parquet"
MODE = "calibrated_v3"
ENGINE_NAME = "auction_context_arbitration_engine_v1.py"

# Unregistered live memories often live under data/cognition/ while root stubs are empty.
_FALLBACK_PATHS: dict[str, tuple[str, ...]] = {
    "runtime_cognition_composite.parquet": (
        "data/cognition/runtime_cognition_composite.parquet",
    ),
    "runtime_cognition_memory.parquet": (
        "data/cognition/runtime_cognition_memory.parquet",
    ),
    "trading_state_memory.parquet": (
        "data/cognition/trading_state_memory.parquet",
    ),
    "market_state_memory.parquet": (
        "data/cognition/market_state_memory.parquet",
    ),
    "candle_structure_memory.parquet": (
        "data/cognition/candle_structure_memory.parquet",
    ),
}


def _clean_text(value: Any, default: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    return text if text and text.lower() != "nan" else default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_memory(name: str) -> pd.DataFrame:
    frame = safe_read_parquet(name)
    if len(frame):
        return frame
    for fallback in _FALLBACK_PATHS.get(name, ()):
        path = ROOT / fallback if not os.path.isabs(fallback) else Path(fallback)
        frame = safe_read_parquet(str(path))
        if len(frame):
            return frame
    return pd.DataFrame()


def _latest_row(frame: pd.DataFrame) -> pd.Series | None:
    if frame is None or len(frame) == 0:
        return None
    work = frame.copy()
    ts_col = None
    for candidate in ("timestamp", "evaluation_timestamp"):
        if candidate in work.columns:
            ts_col = candidate
            break
    if ts_col is not None:
        work[ts_col] = pd.to_datetime(work[ts_col], utc=True, errors="coerce")
        work = work.dropna(subset=[ts_col]).sort_values(ts_col)
        if len(work) == 0:
            return None
    return work.iloc[-1]


def _asof_value(frame: pd.DataFrame, ts: pd.Timestamp, column: str, default: Any = "") -> Any:
    if frame is None or len(frame) == 0 or column not in frame.columns:
        return default
    work = frame.copy()
    ts_col = "timestamp" if "timestamp" in work.columns else (
        "evaluation_timestamp" if "evaluation_timestamp" in work.columns else None
    )
    if ts_col is None:
        return work.iloc[-1].get(column, default)
    work[ts_col] = pd.to_datetime(work[ts_col], utc=True, errors="coerce")
    work = work.dropna(subset=[ts_col]).sort_values(ts_col)
    prior = work[work[ts_col] <= ts]
    if len(prior) == 0:
        return default
    value = prior.iloc[-1].get(column, default)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return value


def _cycle_id() -> Any:
    raw = os.environ.get("BTC_ML_CYCLE_ID") or os.environ.get("PIPELINE_CYCLE_ID")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def _observe_row(
    *,
    timestamp: Any,
    close: float,
    reason: str,
    market_state: str = "",
    trading_state: str = "",
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "cycle_id": _cycle_id(),
        "close": close,
        "raw_chosen_context": "OBSERVE",
        "calibrated_context": "OBSERVE",
        "long_score": 0.0,
        "short_score": 0.0,
        "score_margin": 0.0,
        "long_subtype": "",
        "short_subtype": "",
        "short_candidate": False,
        "tactical_long_candidate": False,
        "tactical_short_candidate": False,
        "suppress_reason": reason,
        "anchor_status": "NONE",
        "anchor_event_type": "",
        "anchor_age_bars": 0.0,
        "cognition_tier1_trigger_event": "",
        "cognition_tier1_location_bias": "",
        "market_state": market_state,
        "trading_state": trading_state,
        "mode": MODE,
        "shadow_only": True,
        "engine": ENGINE_NAME,
    }


def _build_evidence_and_score() -> dict[str, Any]:
    candles = _read_memory("candle_structure_memory.parquet")
    volume = _read_memory("volume_response_state.parquet")
    convergence = _read_memory("auction_convergence_memory.parquet")
    cognition = _read_memory("runtime_cognition_composite.parquet")
    cognition_mem = _read_memory("runtime_cognition_memory.parquet")
    probabilistic = _read_memory("probabilistic_auction_memory.parquet")
    trading = _read_memory("trading_state_memory.parquet")
    market = _read_memory("market_state_memory.parquet")

    candle_row = _latest_row(candles)
    if candle_row is None:
        now = pd.Timestamp.now(tz="UTC")
        return _observe_row(
            timestamp=now,
            close=0.0,
            reason="MISSING_CANDLE_INPUT",
        )

    timestamp = pd.to_datetime(candle_row.get("timestamp"), utc=True, errors="coerce")
    if pd.isna(timestamp):
        timestamp = pd.Timestamp.now(tz="UTC")
    close = _safe_float(candle_row.get("close"))

    # Cognition composite uses evaluation_timestamp; normalize for asof lookups.
    if len(cognition) and "evaluation_timestamp" in cognition.columns and "timestamp" not in cognition.columns:
        cognition = cognition.copy()
        cognition["timestamp"] = pd.to_datetime(cognition["evaluation_timestamp"], utc=True, errors="coerce")

    tier1_trigger = _clean_text(_asof_value(cognition, timestamp, "tier1_trigger_event"))
    if not tier1_trigger:
        tier1_trigger = _clean_text(_asof_value(cognition_mem, timestamp, "trigger_event"))
    tier1_location = _clean_text(_asof_value(cognition, timestamp, "tier1_location_bias"))
    if not tier1_location:
        tier1_location = _clean_text(_asof_value(cognition_mem, timestamp, "location_bias"))

    anchor_age = _safe_float(_asof_value(cognition, timestamp, "anchor_age_bars", 0.0))
    anchor_ts_raw = _asof_value(cognition, timestamp, "tier2_anchor_timestamp", None)
    anchor_ts = pd.to_datetime(anchor_ts_raw, utc=True, errors="coerce") if anchor_ts_raw is not None else pd.NaT
    if pd.isna(anchor_ts):
        anchor_ts = None

    market_state = _clean_text(_asof_value(market, timestamp, "market_state"))
    if not market_state:
        market_state = _clean_text(_asof_value(trading, timestamp, "market_state"))
    market_bias = _clean_text(_asof_value(market, timestamp, "market_bias"), "NEUTRAL")
    trading_state = _clean_text(_asof_value(trading, timestamp, "trading_state"))

    volume_event = _clean_text(_asof_value(volume, timestamp, "volume_event"))
    climax_state = _clean_text(_asof_value(volume, timestamp, "climax_state"))
    effort_result_state = _clean_text(_asof_value(volume, timestamp, "effort_result_state"))
    continuation_quality = _clean_text(_asof_value(volume, timestamp, "continuation_quality"))
    localized_behavior = _clean_text(_asof_value(volume, timestamp, "localized_behavior"))
    if not localized_behavior:
        localized_behavior = _clean_text(_asof_value(convergence, timestamp, "localized_behavior"))
    convergence_state = _clean_text(_asof_value(convergence, timestamp, "convergence_state"))

    auction_regime = _clean_text(_asof_value(probabilistic, timestamp, "auction_regime"))
    absorption_probability = _safe_float(_asof_value(probabilistic, timestamp, "absorption_probability", 0.0))
    distribution_probability = _safe_float(_asof_value(probabilistic, timestamp, "distribution_probability", 0.0))
    absorption_behavior_share = _safe_float(_asof_value(probabilistic, timestamp, "absorption_behavior_share", 0.0))
    supply_behavior_share = _safe_float(_asof_value(probabilistic, timestamp, "supply_behavior_share", 0.0))
    effective_state = _clean_text(_asof_value(cognition, timestamp, "effective_state"))
    if not effective_state:
        effective_state = _clean_text(_asof_value(cognition_mem, timestamp, "synthesis_state"))

    candle_history = candles.copy()
    if "timestamp" in candle_history.columns:
        candle_history["timestamp"] = pd.to_datetime(candle_history["timestamp"], utc=True, errors="coerce")

    anchor_price = resolve_anchor_price(candle_history, anchor_ts, tier1_location)
    anchor_status = resolve_anchor_status(
        anchor_price=anchor_price,
        location_bias=tier1_location,
        close=close,
        anchor_age_bars=anchor_age,
        continuation_quality=continuation_quality,
        convergence_state=convergence_state,
    )
    recent_return = compute_recent_return(candle_history, timestamp, bars=4)
    recent_return_8b = compute_recent_return(candle_history, timestamp, bars=8)
    recent_return_16b = compute_recent_return(candle_history, timestamp, bars=16)

    evidence = AuctionContextEvidence(
        timestamp=timestamp,
        close=close,
        market_state=market_state,
        market_bias=market_bias,
        trading_state=trading_state,
        volume_event=volume_event,
        climax_state=climax_state,
        effort_result_state=effort_result_state,
        continuation_quality=continuation_quality,
        localized_behavior=localized_behavior,
        convergence_state=convergence_state,
        auction_regime=auction_regime,
        effective_state=effective_state,
        tier1_trigger_event=tier1_trigger,
        tier1_location_bias=tier1_location,
        anchor_timestamp=anchor_ts,
        anchor_age_bars=anchor_age,
        absorption_probability=absorption_probability,
        distribution_probability=distribution_probability,
        absorption_behavior_share=absorption_behavior_share,
        supply_behavior_share=supply_behavior_share,
        anchor_price=anchor_price,
        anchor_status=anchor_status,
        recent_return=recent_return,
        recent_return_8b=recent_return_8b,
        recent_return_16b=recent_return_16b,
        candle_history=candle_history,
    )
    result = score_auction_context(evidence, mode=MODE)

    calibrated_context = result.chosen_context
    suppress_reason = result.suppress_reason
    short_candidate = bool(result.short_candidate)

    return {
        "timestamp": timestamp,
        "cycle_id": _cycle_id(),
        "close": close,
        "raw_chosen_context": result.raw_chosen_context or result.chosen_context,
        "calibrated_context": calibrated_context,
        "long_score": float(result.long_context_score),
        "short_score": float(result.short_context_score),
        "score_margin": float(result.long_context_score - result.short_context_score),
        "long_subtype": result.long_subtype,
        "short_subtype": result.short_subtype,
        "short_candidate": short_candidate,
        "tactical_long_candidate": bool(result.tactical_long_candidate),
        "tactical_short_candidate": bool(result.tactical_short_candidate),
        "suppress_reason": suppress_reason,
        "anchor_status": result.anchor_status,
        "anchor_event_type": result.anchor_event_type,
        "anchor_age_bars": anchor_age,
        "cognition_tier1_trigger_event": tier1_trigger,
        "cognition_tier1_location_bias": tier1_location,
        "market_state": market_state,
        "trading_state": trading_state,
        "mode": MODE,
        "shadow_only": True,
        "engine": ENGINE_NAME,
    }


def run() -> int:
    print()
    print("AUCTION CONTEXT ARBITRATION ENGINE (shadow calibrated_v3)")
    print()
    try:
        row = _build_evidence_and_score()

        payload = pd.DataFrame([row])
        dedup_cols = ["timestamp"]
        if row.get("cycle_id") is not None:
            dedup_cols = ["timestamp", "cycle_id"]
        append_state_row(MEMORY_FILE, payload, dedup_columns=dedup_cols)

        print(
            f"shadow context={row.get('calibrated_context')} "
            f"raw={row.get('raw_chosen_context')} "
            f"long_subtype={row.get('long_subtype')} "
            f"suppress={row.get('suppress_reason')}"
        )
        print("SUCCESS")
        return 0
    except Exception as exc:
        # Fail open: never crash runtime; attempt OBSERVE shadow row.
        print(f"SHADOW FAIL-OPEN: {exc}")
        try:
            fallback = _observe_row(
                timestamp=pd.Timestamp.now(tz="UTC"),
                close=0.0,
                reason=f"ENGINE_FAIL_OPEN:{type(exc).__name__}",
            )
            append_state_row(
                MEMORY_FILE,
                pd.DataFrame([fallback]),
                dedup_columns=["timestamp"],
            )
        except Exception as write_exc:
            print(f"SHADOW WRITE FAILED: {write_exc}")
        print("SUCCESS (fail-open OBSERVE)")
        return 0


if __name__ == "__main__":
    raise SystemExit(run())
