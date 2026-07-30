"""Exact per-timeframe bar reconstruction from aggTrade events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import pandas as pd

from . import TF_SECONDS, TIMEFRAMES
from .timeutil import iso


def build_bars_from_trades(
    trades: pd.DataFrame,
    *,
    timeframe: str,
    causal_cutoff: datetime,
    start: datetime | None = None,
) -> list[dict[str, Any]]:
    """Aggregate exact trades into closed/partial bars for one timeframe.

    Only events with timestamp <= causal_cutoff are used. A bar whose open is
    at/after causal_cutoff is never emitted. The in-progress bar at cutoff is
    emitted with close_timestamp = causal_cutoff and incomplete=True.
    """
    tf = str(timeframe).upper()
    tf_s = TF_SECONDS[tf]
    if trades is None or trades.empty:
        return []
    df = trades.copy()
    if "_ts" not in df.columns:
        raise ValueError("trades require _ts")
    df["_ts"] = pd.to_datetime(df["_ts"], utc=True)
    cutoff = pd.Timestamp(causal_cutoff)
    df = df[df["_ts"] <= cutoff]
    if start is not None:
        df = df[df["_ts"] >= pd.Timestamp(start)]
    if df.empty:
        return []
    if "aggregate_trade_id" in df.columns:
        df = df.drop_duplicates(subset=["aggregate_trade_id"], keep="first")
    df = df.sort_values(["_ts", "aggregate_trade_id"] if "aggregate_trade_id" in df.columns else ["_ts"])

    # Unix-second bar opens via Timestamp.timestamp() (tz-safe; avoids pandas int cast quirks).
    opens_sec = pd.to_datetime(df["_ts"], utc=True).map(lambda x: int(x.timestamp())).to_numpy(dtype="int64")
    bar_open_epoch = (opens_sec // int(tf_s)) * int(tf_s)
    df = df.assign(_bar_open_epoch=bar_open_epoch)

    bars: list[dict[str, Any]] = []
    for bar_epoch, g in df.groupby("_bar_open_epoch", sort=True):
        open_dt = datetime.fromtimestamp(int(bar_epoch), tz=timezone.utc)
        natural_close = open_dt + timedelta(seconds=tf_s)
        incomplete = cutoff < pd.Timestamp(natural_close)
        close_dt = (
            min(causal_cutoff, natural_close - timedelta(microseconds=1))
            if incomplete
            else natural_close - timedelta(microseconds=1)
        )
        if pd.Timestamp(open_dt) > cutoff:
            continue
        prices = g["price"].astype(float)
        qty = g["quantity"].astype(float)
        qq = g["quote_quantity"].astype(float) if "quote_quantity" in g.columns else prices * qty
        buy = 0.0
        sell = 0.0
        if "buyer_is_market_maker" in g.columns:
            mm = g["buyer_is_market_maker"].astype(bool)
            sell = float(qty[mm].sum())
            buy = float(qty[~mm].sum())
        first_id = int(g["aggregate_trade_id"].iloc[0]) if "aggregate_trade_id" in g.columns else None
        last_id = int(g["aggregate_trade_id"].iloc[-1]) if "aggregate_trade_id" in g.columns else None
        o = float(prices.iloc[0])
        h = float(prices.max())
        l = float(prices.min())
        c = float(prices.iloc[-1])
        rng = h - l
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        close_loc = 0.5 if rng <= 0 else (c - l) / rng
        directional_eff = 0.0 if rng <= 0 else abs(c - o) / rng
        imbalance = 0.0
        if (buy + sell) > 0:
            imbalance = (buy - sell) / (buy + sell)
        bars.append(
            {
                "timeframe": tf,
                "candle_id": f"{tf}|{iso(open_dt)}",
                "open_timestamp": iso(open_dt),
                "close_timestamp": iso(close_dt if incomplete else natural_close - timedelta(microseconds=1)),
                "natural_close_timestamp": iso(natural_close),
                "incomplete": bool(incomplete),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "base_volume": float(qty.sum()),
                "quote_volume": float(qq.sum()),
                "buy_aggressor_volume": buy,
                "sell_aggressor_volume": sell,
                "trade_count": int(len(g)),
                "first_trade_id": first_id,
                "last_trade_id": last_id,
                "range": rng,
                "body": body,
                "upper_wick": upper_wick,
                "lower_wick": lower_wick,
                "close_location": close_loc,
                "directional_efficiency": directional_eff,
                "aggressor_imbalance": imbalance,
                "effort_result": (body / float(qty.sum())) if float(qty.sum()) > 0 else 0.0,
            }
        )
    return bars


def build_all_timeframe_bars(
    trades: pd.DataFrame,
    *,
    causal_cutoff: datetime,
    start: datetime | None = None,
    timeframes: Iterable[str] = TIMEFRAMES,
) -> dict[str, list[dict[str, Any]]]:
    return {
        str(tf).upper(): build_bars_from_trades(
            trades, timeframe=str(tf).upper(), causal_cutoff=causal_cutoff, start=start
        )
        for tf in timeframes
    }


def assert_trade_membership_unique(
    trades: pd.DataFrame,
    bars_by_tf: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Each trade belongs to exactly one bar per timeframe; no duplicate trade ids."""
    if trades is None or trades.empty:
        return {"ok": True, "duplicate_trade_ids": 0, "membership_violations": 0}
    df = trades.copy()
    if "aggregate_trade_id" in df.columns:
        dup = int(df["aggregate_trade_id"].duplicated().sum())
    else:
        dup = 0
    violations = 0
    for tf, bars in bars_by_tf.items():
        bar_vol = sum(float(b["base_volume"]) for b in bars)
        src_vol = float(df["quantity"].sum())
        if abs(bar_vol - src_vol) > max(1e-9, src_vol * 1e-12):
            violations += 1
    return {"ok": dup == 0 and violations == 0, "duplicate_trade_ids": dup, "membership_violations": violations}


def closed_bars_before(
    bars: list[dict[str, Any]],
    *,
    decision_ts: datetime,
) -> list[dict[str, Any]]:
    """Bars fully closed before decision (incomplete excluded)."""
    out = []
    for b in bars:
        if b.get("incomplete"):
            continue
        close_ts = pd.Timestamp(b["natural_close_timestamp"])
        if close_ts <= pd.Timestamp(decision_ts):
            out.append(b)
    return out
