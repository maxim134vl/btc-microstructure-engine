"""Exact candle volume-by-price profile builder (trade-event based only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from . import DEFAULT_TICK_SIZE
from .timeutil import iso


BINNING_CONTRACT = {
    "mode": "EXCHANGE_TICK",
    "tick_size": DEFAULT_TICK_SIZE,
    "merge_ticks": 1,
    "approximation_forbidden": True,
}


def build_exact_candle_volume_profile(
    trades: pd.DataFrame,
    *,
    candle_start: datetime,
    causal_cutoff: datetime,
    tick_size: float = DEFAULT_TICK_SIZE,
    binning_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate exact trade volume into price bins; conserve total volume."""
    contract = dict(BINNING_CONTRACT)
    if binning_contract:
        contract.update(binning_contract)
    tick = float(contract.get("tick_size") or tick_size)
    merge = max(1, int(contract.get("merge_ticks") or 1))
    bin_size = tick * merge

    if trades is None or trades.empty:
        return {
            "ok": False,
            "reason": "NO_TRADES",
            "bins": [],
            "total_base_volume": 0.0,
            "total_quote_volume": 0.0,
            "conservation_ok": True,
            "binning_contract": contract,
            "candle_start": iso(candle_start),
            "causal_cutoff": iso(causal_cutoff),
        }

    df = trades.copy()
    if "_ts" not in df.columns:
        raise ValueError("trades require _ts column")
    df = df[(df["_ts"] >= pd.Timestamp(candle_start)) & (df["_ts"] <= pd.Timestamp(causal_cutoff))]
    if df.empty:
        return {
            "ok": False,
            "reason": "NO_TRADES_IN_WINDOW",
            "bins": [],
            "total_base_volume": 0.0,
            "total_quote_volume": 0.0,
            "conservation_ok": True,
            "binning_contract": contract,
            "candle_start": iso(candle_start),
            "causal_cutoff": iso(causal_cutoff),
        }

    # Dedup already expected upstream; re-assert.
    if "aggregate_trade_id" in df.columns:
        df = df.drop_duplicates(subset=["aggregate_trade_id"], keep="first")

    src_base = float(df["quantity"].sum())
    src_quote = float(df["quote_quantity"].sum()) if "quote_quantity" in df.columns else float((df["price"] * df["quantity"]).sum())

    bins: dict[float, dict[str, float]] = {}
    prices = df["price"].astype(float).to_numpy()
    qtys = df["quantity"].astype(float).to_numpy()
    if "quote_quantity" in df.columns:
        qqs = df["quote_quantity"].astype(float).to_numpy()
    else:
        qqs = prices * qtys
    if "buyer_is_market_maker" in df.columns:
        mm = df["buyer_is_market_maker"].astype(bool).to_numpy()
    else:
        mm = None
    for i, px in enumerate(prices):
        qty = float(qtys[i])
        qq = float(qqs[i])
        bin_px = (int(px / bin_size)) * bin_size
        bin_px = round(bin_px / tick) * tick
        slot = bins.setdefault(
            bin_px,
            {"price": bin_px, "base_volume": 0.0, "quote_volume": 0.0, "buy_aggressor_volume": 0.0, "sell_aggressor_volume": 0.0},
        )
        slot["base_volume"] += qty
        slot["quote_volume"] += qq
        if mm is not None:
            if bool(mm[i]):
                slot["sell_aggressor_volume"] += qty
            else:
                slot["buy_aggressor_volume"] += qty

    bin_list = sorted(bins.values(), key=lambda b: b["price"])
    sum_base = sum(b["base_volume"] for b in bin_list)
    sum_quote = sum(b["quote_volume"] for b in bin_list)
    conservation_ok = abs(sum_base - src_base) <= max(1e-12, abs(src_base) * 1e-12)

    # POC: max base volume; ties → lowest price (deterministic)
    poc = None
    if bin_list:
        max_vol = max(b["base_volume"] for b in bin_list)
        candidates = [b for b in bin_list if abs(b["base_volume"] - max_vol) <= 1e-15]
        poc = min(candidates, key=lambda b: b["price"])

    return {
        "ok": True,
        "reason": None,
        "bins": bin_list,
        "poc_price": None if poc is None else poc["price"],
        "poc_base_volume": None if poc is None else poc["base_volume"],
        "total_base_volume": sum_base,
        "total_quote_volume": sum_quote,
        "source_base_volume": src_base,
        "source_quote_volume": src_quote,
        "conservation_ok": conservation_ok,
        "trade_count": int(len(df)),
        "binning_contract": contract,
        "candle_start": iso(candle_start),
        "causal_cutoff": iso(causal_cutoff),
        "open_at_cutoff": float(df.iloc[0]["price"]),
        "high_at_cutoff": float(df["price"].max()),
        "low_at_cutoff": float(df["price"].min()),
        "close_at_cutoff": float(df.iloc[-1]["price"]),
        "max_trade_timestamp": iso(df["_ts"].max().to_pydatetime()),
        "profile_kind": "EXACT_TRADE_EVENTS",
    }
