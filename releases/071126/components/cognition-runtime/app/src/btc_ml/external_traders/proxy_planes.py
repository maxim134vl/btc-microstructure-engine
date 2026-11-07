"""OHLCV proxy planes so historical auction chain gets directional events.

These approximate live volume_response / cognition triggers from candle_structure
rules (same thresholds as volume_classification_engine_v1 where applicable).
Not tip-pipeline fidelity — labeled HISTORICAL_PROXY.
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

    # Climax → explicit climax volume events
    buy_climax = (vclass == "climax") & (ctype == "bullish")
    sell_climax = (vclass == "climax") & (ctype == "bearish")
    volume_event = np.where(buy_climax | sell_climax, "EXHAUSTION_VOLUME", volume_event)
    climax_state = np.where(buy_climax | sell_climax, "CLIMAX_EXHAUSTION", climax_state)

    # Stopping volume (bearish wick reclaim)
    stopping = vclass == "stopping"
    volume_event = np.where(stopping, "STOPPING_VOLUME", volume_event)
    climax_state = np.where(stopping, "NO_CLIMAX", climax_state)
    effort_result_state = np.where(stopping, "ABSORPTION_RESPONSE", effort_result_state)

    # Absorption: high volume, small body, large opposing wick
    absorb_up = (vz > 1.0) & (body > 0) & (upper > body) & (cp < 0.45) & (ctype == "bullish")
    absorb_dn = (vz > 1.0) & (body > 0) & (lower > body) & (cp > 0.55) & (ctype == "bearish")
    volume_event = np.where(absorb_up | absorb_dn, "ABSORPTION_VOLUME", volume_event)
    effort_result_state = np.where(absorb_up | absorb_dn, "ABSORPTION_RESPONSE", effort_result_state)

    # Continuation: high volume + close near extreme in direction of candle
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
            "proxy_source": "HISTORICAL_OHLCV_PROXY",
        }
    )
