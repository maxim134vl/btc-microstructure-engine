"""Volume zone extraction methods (parallel, deterministic)."""

from __future__ import annotations

from typing import Any


def extract_zones(profile: dict[str, Any], *, methods: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    methods = methods or ("POC_BIN", "POC_CONTIGUOUS_50", "POC_VALUE_AREA_70")
    bins = list(profile.get("bins") or [])
    if not bins or not profile.get("ok"):
        return []
    total = float(profile.get("total_base_volume") or 0.0)
    poc_price = profile.get("poc_price")
    if poc_price is None:
        return []
    by_price = {float(b["price"]): b for b in bins}
    prices = sorted(by_price.keys())
    poc_vol = float(by_price[float(poc_price)]["base_volume"])
    out: list[dict[str, Any]] = []

    for method in methods:
        if method == "POC_BIN":
            b = by_price[float(poc_price)]
            out.append(_zone(method, b["price"], b["price"], float(poc_price), b, total))
            continue

        if method == "POC_CONTIGUOUS_50":
            threshold = 0.5 * poc_vol
            idx = prices.index(float(poc_price))
            lo = hi = idx
            # expand while neighbor >= 50% POC
            while lo > 0 and float(by_price[prices[lo - 1]]["base_volume"]) >= threshold - 1e-15:
                lo -= 1
            while hi < len(prices) - 1 and float(by_price[prices[hi + 1]]["base_volume"]) >= threshold - 1e-15:
                hi += 1
            region = [by_price[prices[i]] for i in range(lo, hi + 1)]
            out.append(
                _zone(
                    method,
                    prices[lo],
                    prices[hi],
                    float(poc_price),
                    _agg(region),
                    total,
                )
            )
            continue

        if method == "POC_VALUE_AREA_70":
            target = 0.7 * total
            idx = prices.index(float(poc_price))
            lo = hi = idx
            covered = float(by_price[prices[idx]]["base_volume"])
            while covered + 1e-15 < target and (lo > 0 or hi < len(prices) - 1):
                left = float(by_price[prices[lo - 1]]["base_volume"]) if lo > 0 else -1.0
                right = float(by_price[prices[hi + 1]]["base_volume"]) if hi < len(prices) - 1 else -1.0
                if right > left:
                    hi += 1
                    covered += float(by_price[prices[hi]]["base_volume"])
                elif left > right:
                    lo -= 1
                    covered += float(by_price[prices[lo]]["base_volume"])
                else:
                    # tie: expand both sides deterministically lower-first then higher
                    if lo > 0:
                        lo -= 1
                        covered += float(by_price[prices[lo]]["base_volume"])
                    if covered + 1e-15 < target and hi < len(prices) - 1:
                        hi += 1
                        covered += float(by_price[prices[hi]]["base_volume"])
            region = [by_price[prices[i]] for i in range(lo, hi + 1)]
            out.append(
                _zone(
                    method,
                    prices[lo],
                    prices[hi],
                    float(poc_price),
                    _agg(region),
                    total,
                )
            )
    return out


def _agg(region: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "base_volume": sum(float(b["base_volume"]) for b in region),
        "quote_volume": sum(float(b["quote_volume"]) for b in region),
        "buy_aggressor_volume": sum(float(b.get("buy_aggressor_volume") or 0.0) for b in region),
        "sell_aggressor_volume": sum(float(b.get("sell_aggressor_volume") or 0.0) for b in region),
    }


def _zone(method: str, lower: float, upper: float, peak: float, agg: dict[str, Any], total: float) -> dict[str, Any]:
    base = float(agg["base_volume"])
    return {
        "zone_method": method,
        "lower_boundary": float(lower),
        "upper_boundary": float(upper),
        "peak_volume_price": float(peak),
        "base_volume": base,
        "quote_volume": float(agg["quote_volume"]),
        "share_of_candle_volume": (base / total) if total else 0.0,
        "buy_aggressor_volume": float(agg.get("buy_aggressor_volume") or 0.0),
        "sell_aggressor_volume": float(agg.get("sell_aggressor_volume") or 0.0),
    }
