"""OHLCV(+taker) volume planes for historical auction chain.

Approximates live volume_response / cognition triggers from candle_structure
and Binance native volume/delta (same classification thresholds as
volume_classification_engine_v1 where applicable).

Fidelity labels:
- HISTORICAL_OHLCV_PROXY — legacy thin proxy (no AES scores)
- HISTORICAL_NATIVE_VOLUME_V2 — AES-compatible scores from real bar volume +
  taker delta; NOT tip-pipeline / footprint fidelity
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_volume_classification(candle: pd.DataFrame) -> pd.DataFrame:
    df = candle.copy()
    df["volume_class"] = "high_average"
    vz = pd.to_numeric(df.get("volume_zscore"), errors="coerce")
    sz = pd.to_numeric(df.get("spread_zscore"), errors="coerce")
    body = pd.to_numeric(df.get("body"), errors="coerce")
    lower = pd.to_numeric(df.get("lower_wick"), errors="coerce")
    upper = pd.to_numeric(df.get("upper_wick"), errors="coerce")
    cp = pd.to_numeric(df.get("close_position"), errors="coerce")
    ctype = df.get("candle_type", pd.Series(index=df.index, dtype=object)).astype(str)

    df.loc[vz < -0.7, "volume_class"] = "low_small"
    buying_climax = (ctype == "bullish") & (sz > 1.5) & (vz > 1.5)
    selling_climax = (ctype == "bearish") & (sz > 1.5) & (vz > 1.5)
    df.loc[buying_climax | selling_climax, "volume_class"] = "climax"
    stopping = (ctype == "bearish") & (vz > 0.7) & (lower > body) & (cp > 0.5)
    df.loc[stopping, "volume_class"] = "stopping"
    return df


def synthesize_volume_response(candle: pd.DataFrame) -> pd.DataFrame:
    """Legacy thin proxy (kept for A/B compare). Prefer synthesize_volume_response_v2."""
    classified = build_volume_classification(candle)
    vz = pd.to_numeric(classified["volume_zscore"], errors="coerce").fillna(0.0)
    vol = pd.to_numeric(classified["volume"], errors="coerce")
    vol_mean = pd.to_numeric(classified.get("volume_mean_20"), errors="coerce")
    relative = (vol / (vol_mean.replace(0, np.nan))).fillna(1.0).clip(0.05, 20.0)
    ctype = classified["candle_type"].astype(str)
    vclass = classified["volume_class"].astype(str)
    body = pd.to_numeric(classified["body"], errors="coerce").fillna(0.0)
    upper = pd.to_numeric(classified["upper_wick"], errors="coerce").fillna(0.0)
    lower = pd.to_numeric(classified["lower_wick"], errors="coerce").fillna(0.0)
    cp = pd.to_numeric(classified["close_position"], errors="coerce").fillna(0.5)
    delta = pd.to_numeric(classified.get("delta"), errors="coerce").fillna(0.0)

    volume_event = np.full(len(classified), "NEUTRAL_VOLUME", dtype=object)
    climax_state = np.full(len(classified), "NO_CLIMAX", dtype=object)
    effort_result_state = np.full(len(classified), "BALANCED_RESPONSE", dtype=object)
    localized = np.full(len(classified), "UNKNOWN", dtype=object)

    buy_climax = (vclass == "climax") & (ctype == "bullish")
    sell_climax = (vclass == "climax") & (ctype == "bearish")
    volume_event = np.where(buy_climax | sell_climax, "EXHAUSTION_VOLUME", volume_event)
    climax_state = np.where(buy_climax | sell_climax, "CLIMAX_EXHAUSTION", climax_state)

    stopping = vclass == "stopping"
    volume_event = np.where(stopping, "STOPPING_VOLUME", volume_event)
    climax_state = np.where(stopping, "NO_CLIMAX", climax_state)
    effort_result_state = np.where(stopping, "ABSORPTION_RESPONSE", effort_result_state)

    absorb_up = (vz > 1.0) & (body > 0) & (upper > body) & (cp < 0.45) & (ctype == "bullish")
    absorb_dn = (vz > 1.0) & (body > 0) & (lower > body) & (cp > 0.55) & (ctype == "bearish")
    volume_event = np.where(absorb_up | absorb_dn, "ABSORPTION_VOLUME", volume_event)
    effort_result_state = np.where(absorb_up | absorb_dn, "ABSORPTION_RESPONSE", effort_result_state)

    cont_up = (vz > 0.8) & (ctype == "bullish") & (cp >= 0.7) & (vclass != "climax")
    cont_dn = (vz > 0.8) & (ctype == "bearish") & (cp <= 0.3) & (vclass != "climax")
    volume_event = np.where(cont_up | cont_dn, "CONTINUATION_VOLUME", volume_event)
    effort_result_state = np.where(cont_up | cont_dn, "EFFICIENT_CONTINUATION", effort_result_state)

    localized = np.where(cp >= 0.75, "localized_distribution", localized)
    localized = np.where(cp <= 0.25, "localized_absorption", localized)

    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(classified["timestamp"], utc=True),
            "volume_event": volume_event,
            "climax_state": climax_state,
            "effort_result_state": effort_result_state,
            "volume_class": vclass,
            "relative_volume": relative,
            "localized_behavior": localized,
            "delta": delta,
            "proxy_source": "HISTORICAL_OHLCV_PROXY",
        }
    )


def synthesize_volume_response_v2(candle: pd.DataFrame) -> pd.DataFrame:
    """AES-compatible volume_response from native bar volume + taker delta.

    Mirrors closed-bar scoring intent of volume_response_evaluate.py without
    tip localization. Still NOT live tip / footprint fidelity.
    """
    classified = build_volume_classification(candle)
    n = len(classified)
    vz = pd.to_numeric(classified.get("volume_zscore"), errors="coerce").fillna(0.0).to_numpy()
    sz = pd.to_numeric(classified.get("spread_zscore"), errors="coerce").fillna(0.0).to_numpy()
    vol = pd.to_numeric(classified.get("volume"), errors="coerce").fillna(0.0).to_numpy()
    vol_mean = pd.to_numeric(classified.get("volume_mean_20"), errors="coerce").to_numpy()
    spread = pd.to_numeric(classified.get("spread"), errors="coerce").fillna(0.0).to_numpy()
    spread_mean = pd.to_numeric(classified.get("spread_mean_20"), errors="coerce").to_numpy()
    body = pd.to_numeric(classified.get("body"), errors="coerce").fillna(0.0).to_numpy()
    upper = pd.to_numeric(classified.get("upper_wick"), errors="coerce").fillna(0.0).to_numpy()
    lower = pd.to_numeric(classified.get("lower_wick"), errors="coerce").fillna(0.0).to_numpy()
    cp = pd.to_numeric(classified.get("close_position"), errors="coerce").fillna(0.5).to_numpy()
    delta = pd.to_numeric(classified.get("delta"), errors="coerce").fillna(0.0).to_numpy()
    ctype = classified["candle_type"].astype(str).to_numpy()
    vclass = classified["volume_class"].astype(str).to_numpy()

    with np.errstate(divide="ignore", invalid="ignore"):
        relative_volume = np.where(
            (vol_mean == vol_mean) & (vol_mean > 0),
            np.clip(vol / vol_mean, 0.05, 20.0),
            1.0,
        )
        relative_spread = np.where(
            (spread_mean == spread_mean) & (spread_mean > 0),
            np.clip(spread / spread_mean, 0.05, 20.0),
            np.clip((sz + 2.0) / 2.0, 0.05, 20.0),
        )
        delta_efficiency = np.where(vol > 0, np.abs(delta) / vol, 0.0)

    upper_rejection = (upper > body) & (cp < 0.45) & (spread > 0)
    lower_rejection = (lower > body) & (cp > 0.55) & (spread > 0)

    close_acceptance = np.abs(cp - 0.5) * 2.0
    rejection_penalty = upper_rejection.astype(float) * 0.4 + lower_rejection.astype(float) * 0.4
    effort_score = (relative_volume + delta_efficiency + relative_spread) / 3.0
    result_score = close_acceptance + relative_spread * close_acceptance - rejection_penalty
    effort_result_ratio = result_score / (effort_score + 0.001)
    normalized_result = effort_result_ratio * (1.0 / (1.0 + rejection_penalty))

    participation_state = np.full(n, "NORMAL_PARTICIPATION", dtype=object)
    climax_state = np.full(n, "NO_CLIMAX", dtype=object)
    is_climax = np.array(["climax" in str(x).lower() for x in vclass])
    participation_state = np.where(is_climax, "CLIMACTIC_PARTICIPATION", participation_state)
    extreme_z = vz >= 1.5
    participation_state = np.where(
        (~is_climax) & extreme_z, "ELEVATED_PARTICIPATION", participation_state
    )
    effort_score = np.where(is_climax, effort_score + 0.5, effort_score)

    climax_state = np.where(is_climax & (normalized_result < 0), "CLIMAX_EXHAUSTION", climax_state)
    climax_state = np.where(
        is_climax & (normalized_result >= 0) & (normalized_result > 0.5),
        "CLIMAX_CONTINUATION",
        climax_state,
    )
    climax_state = np.where(
        is_climax & (normalized_result >= 0) & (normalized_result <= 0.5),
        "CLIMAX_ABSORPTION",
        climax_state,
    )

    volume_event = np.full(n, "NEUTRAL_VOLUME", dtype=object)
    volume_event = np.where(
        (relative_volume > 1.8) & (delta_efficiency < 0.3) & (upper_rejection | lower_rejection),
        "STOPPING_VOLUME",
        volume_event,
    )
    volume_event = np.where(
        (cp <= 0.25) & (delta_efficiency < 0.3),
        "ABSORPTION_VOLUME",
        volume_event,
    )
    volume_event = np.where(
        (body > (spread * 0.7)) & (delta_efficiency > 0.35) & (relative_spread > 1.2),
        "CONTINUATION_VOLUME",
        volume_event,
    )
    volume_event = np.where(
        (relative_volume > 2.0) & (delta_efficiency < 0.2),
        "EXHAUSTION_VOLUME",
        volume_event,
    )
    volume_event = np.where(
        (vclass == "climax") & (ctype == "bullish"), "EXHAUSTION_VOLUME", volume_event
    )
    volume_event = np.where(
        (vclass == "climax") & (ctype == "bearish"), "EXHAUSTION_VOLUME", volume_event
    )
    volume_event = np.where(vclass == "stopping", "STOPPING_VOLUME", volume_event)

    effort_result_state = np.full(n, "BALANCED_RESPONSE", dtype=object)
    effort_result_state = np.where(
        (effort_score > 1.2) & (normalized_result < 0.6),
        "ABSORPTION_RESPONSE",
        effort_result_state,
    )
    effort_result_state = np.where(
        (effort_score > 1.2) & (normalized_result > 1.0),
        "EFFICIENT_CONTINUATION",
        effort_result_state,
    )
    effort_result_state = np.where(
        (relative_volume > 2.0) & (normalized_result < 0.4),
        "EXHAUSTION_RESPONSE",
        effort_result_state,
    )
    effort_result_state = np.where(vclass == "stopping", "ABSORPTION_RESPONSE", effort_result_state)

    localized = np.full(n, "UNKNOWN", dtype=object)
    localized = np.where(cp >= 0.75, "localized_distribution", localized)
    localized = np.where(cp <= 0.25, "localized_absorption", localized)

    unfinished = (
        ((effort_score > 1.0) & (normalized_result < 0.3))
        | ((localized == "localized_distribution") & (relative_spread < 1.0))
        | ((upper_rejection | lower_rejection) & (np.abs(normalized_result) < 0.2))
    )
    unfinished_reason = np.full(n, "NONE", dtype=object)
    unfinished_reason = np.where(
        (effort_score > 1.0) & (normalized_result < 0.3), "INEFFICIENT_AUCTION", unfinished_reason
    )
    unfinished_reason = np.where(
        (localized == "localized_distribution") & (relative_spread < 1.0),
        "DISTRIBUTION_NOT_RESOLVED",
        unfinished_reason,
    )
    unfinished_reason = np.where(
        (upper_rejection | lower_rejection) & (np.abs(normalized_result) < 0.2),
        "REJECTION_WITHOUT_RESOLUTION",
        unfinished_reason,
    )

    continuation_quality = np.full(n, "NEUTRAL", dtype=object)
    continuation_quality = np.where(
        (volume_event == "CONTINUATION_VOLUME") & (cp > 0.8),
        "STRONG_ACCEPTANCE",
        continuation_quality,
    )
    continuation_quality = np.where(
        (volume_event == "CONTINUATION_VOLUME") & (cp < 0.5),
        "FAILED_CONTINUATION",
        continuation_quality,
    )
    continuation_quality = np.where(
        volume_event == "STOPPING_VOLUME", "AUCTION_STALLED", continuation_quality
    )
    continuation_quality = np.where(
        volume_event == "ABSORPTION_VOLUME", "PASSIVE_DEFENSE", continuation_quality
    )

    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(classified["timestamp"], utc=True),
            "volume_event": volume_event,
            "continuation_quality": continuation_quality,
            "climax_state": climax_state,
            "effort_result_state": effort_result_state,
            "volume_class": vclass,
            "relative_volume": relative_volume,
            "relative_spread": relative_spread,
            "delta_efficiency": delta_efficiency,
            "localized_behavior": localized,
            "delta": delta,
            "effort_score": effort_score,
            "result_score": result_score,
            "normalized_result": normalized_result,
            "effort_result_ratio": effort_result_ratio,
            "participation_state": participation_state,
            "unfinished_auction": unfinished,
            "unfinished_reason": unfinished_reason,
            "upper_rejection": upper_rejection,
            "lower_rejection": lower_rejection,
            "volume_zscore": vz,
            "proxy_source": "HISTORICAL_NATIVE_VOLUME_V2",
            "evaluation_mode": "CLOSED_BAR_NATIVE_VOLUME",
            "fidelity_note": "bar_volume+taker_delta; not tip/footprint",
        }
    )


def synthesize_cognition_triggers(candle: pd.DataFrame) -> pd.DataFrame:
    """Proxy cognition triggers so auction classify_bar_event sees climaxes."""
    classified = build_volume_classification(candle)
    ctype = classified["candle_type"].astype(str)
    vclass = classified["volume_class"].astype(str)
    cp = pd.to_numeric(classified["close_position"], errors="coerce").fillna(0.5)

    trigger = np.full(len(classified), "UNKNOWN", dtype=object)
    trigger = np.where((vclass == "climax") & (ctype == "bullish"), "BUYING_CLIMAX", trigger)
    trigger = np.where((vclass == "climax") & (ctype == "bearish"), "SELLING_CLIMAX", trigger)
    trigger = np.where(vclass == "stopping", "STOPPING_VOLUME", trigger)

    location = np.full(len(classified), "MIDDLE", dtype=object)
    location = np.where(cp >= 0.75, "UPPER_AREA", location)
    location = np.where(cp <= 0.25, "LOWER_AREA", location)

    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(classified["timestamp"], utc=True),
            "trigger_event": trigger,
            "location_bias": location,
            "proxy_source": "HISTORICAL_NATIVE_VOLUME_V2",
        }
    )
