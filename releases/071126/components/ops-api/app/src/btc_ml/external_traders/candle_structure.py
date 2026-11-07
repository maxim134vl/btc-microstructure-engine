"""Build candle_structure plane from OHLCV (same rules as candle_structure_engine_v1)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_candle_structure(feed: pd.DataFrame) -> pd.DataFrame:
    if feed is None or len(feed) == 0:
        return pd.DataFrame()
    ohlc = feed.copy()
    ohlc["timestamp"] = pd.to_datetime(ohlc["timestamp"], utc=True, errors="coerce")
    ohlc = ohlc.dropna(subset=["timestamp"]).sort_values("timestamp")
    ohlc = ohlc.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

    if "taker_buy_volume" in ohlc.columns:
        ohlc["buy_volume"] = ohlc["taker_buy_volume"].fillna(0)
        ohlc["sell_volume"] = (ohlc["volume"] - ohlc["buy_volume"]).clip(lower=0)
    else:
        body_share = (
            (ohlc["close"] - ohlc["open"]).abs() / (ohlc["high"] - ohlc["low"] + 0.000001)
        ).clip(0, 1)
        bullish = ohlc["close"] >= ohlc["open"]
        ohlc["buy_volume"] = np.where(
            bullish,
            ohlc["volume"] * (0.5 + 0.5 * body_share),
            ohlc["volume"] * (0.5 - 0.5 * body_share),
        )
        ohlc["sell_volume"] = ohlc["volume"] - ohlc["buy_volume"]

    ohlc["delta"] = ohlc["buy_volume"] - ohlc["sell_volume"]
    ohlc["candle_type"] = np.where(ohlc["close"] >= ohlc["open"], "bullish", "bearish")
    ohlc["body"] = (ohlc["close"] - ohlc["open"]).abs()
    ohlc["spread"] = ohlc["high"] - ohlc["low"]
    ohlc["upper_wick"] = ohlc["high"] - ohlc[["open", "close"]].max(axis=1)
    ohlc["lower_wick"] = ohlc[["open", "close"]].min(axis=1) - ohlc["low"]
    ohlc["close_position"] = (ohlc["close"] - ohlc["low"]) / (ohlc["spread"] + 0.000001)
    ohlc["spread_mean_20"] = ohlc["spread"].rolling(20).mean()
    ohlc["spread_std_20"] = ohlc["spread"].rolling(20).std()
    ohlc["volume_mean_20"] = ohlc["volume"].rolling(10).mean()
    ohlc["volume_std_20"] = ohlc["volume"].rolling(10).std()
    ohlc["spread_zscore"] = (ohlc["spread"] - ohlc["spread_mean_20"]) / (
        ohlc["spread_std_20"] + 0.000001
    )
    ohlc["volume_zscore"] = (ohlc["volume"] - ohlc["volume_mean_20"]) / (
        ohlc["volume_std_20"] + 0.000001
    )
    return ohlc
