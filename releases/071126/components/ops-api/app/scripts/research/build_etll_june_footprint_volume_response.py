#!/usr/bin/env python3
"""June: exact M15 footprint from aggTrade → AES volume_response (our logic).

Writes only under MaksTiger. Does NOT implement classical VSA eight.
Fidelity: PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1 / TIP_FOOTPRINT_M15_V1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.shadow_structural_protection.profile import (  # noqa: E402
    build_exact_candle_volume_profile,
)
from btc_ml.trading.shadow_structural_protection.trades import load_agg_trades  # noqa: E402

DEFAULT_TICK_REPO = Path("/Volumes/MaksTiger/btc-ml/research/etll_tip/tick_pack_202606/repo")
DEFAULT_OUT = Path("/Volumes/MaksTiger/btc-ml/research/etll_tip/footprint_202606")
DEFAULT_CANDLE = (
    ROOT
    / "data/research/external_traders/market_pack_btc_m15/context/candle_structure_memory.parquet"
)
DEFAULT_AUDIT = ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_june_footprint"
REQUIRE_VOLUME = Path("/Volumes/MaksTiger")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _assert_tiger(out_dir: Path) -> None:
    if not REQUIRE_VOLUME.exists():
        raise SystemExit(f"REQUIRED_VOLUME_NOT_MOUNTED: {REQUIRE_VOLUME}")
    resolved = out_dir.resolve() if out_dir.exists() else out_dir.absolute()
    if not str(resolved).startswith(str(REQUIRE_VOLUME.resolve())):
        raise SystemExit(f"REFUSING_WRITE_OUTSIDE_VOLUME: {out_dir}")
    st = os.statvfs(REQUIRE_VOLUME)
    free = st.f_bavail * st.f_frsize
    if free < 5 * (1024**3):
        raise SystemExit(f"INSUFFICIENT_FREE_SPACE on MaksTiger: {free / (1024**3):.1f} GiB")


def _edge_volume_share(bins: list[dict], *, edge: str, band_frac: float = 0.15) -> float:
    if not bins:
        return 0.0
    prices = [float(b["price"]) for b in bins]
    vols = [float(b["base_volume"]) for b in bins]
    lo, hi = min(prices), max(prices)
    span = hi - lo
    if span <= 0:
        return 1.0
    band = span * band_frac
    total = sum(vols) or 1e-12
    if edge == "high":
        return sum(v for p, v in zip(prices, vols) if p >= hi - band) / total
    return sum(v for p, v in zip(prices, vols) if p <= lo + band) / total


def _aggressor_at_edge(bins: list[dict], *, edge: str, band_frac: float = 0.15) -> tuple[float, float]:
    if not bins:
        return 0.0, 0.0
    prices = [float(b["price"]) for b in bins]
    lo, hi = min(prices), max(prices)
    span = max(hi - lo, 1e-12)
    band = span * band_frac
    buy = sell = 0.0
    for b in bins:
        p = float(b["price"])
        if edge == "high" and p < hi - band:
            continue
        if edge == "low" and p > lo + band:
            continue
        buy += float(b.get("buy_aggressor_volume") or 0.0)
        sell += float(b.get("sell_aggressor_volume") or 0.0)
    return buy, sell


def _features_for_bar(*, candle_row: pd.Series, trades: pd.DataFrame) -> dict:
    start = pd.Timestamp(candle_row["timestamp"]).to_pydatetime()
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=15) - timedelta(microseconds=1)
    prof = build_exact_candle_volume_profile(trades, candle_start=start, causal_cutoff=end)
    o = float(candle_row["open"])
    h = float(candle_row["high"])
    l = float(candle_row["low"])
    c = float(candle_row["close"])
    spread = float(candle_row.get("spread") or (h - l))
    body = float(candle_row.get("body") or abs(c - o))
    cp = float(
        candle_row.get("close_position")
        if pd.notna(candle_row.get("close_position"))
        else 0.5
    )
    upper_wick = float(candle_row.get("upper_wick") or max(0.0, h - max(o, c)))
    lower_wick = float(candle_row.get("lower_wick") or max(0.0, min(o, c) - l))

    total = float(prof.get("total_base_volume") or 0.0)
    trade_count = int(prof.get("trade_count") or 0)
    bins = list(prof.get("bins") or [])
    poc = prof.get("poc_price")
    poc_f = float(poc) if poc is not None else float("nan")
    poc_pos = (poc_f - l) / spread if spread > 0 and np.isfinite(poc_f) else 0.5

    vol_high = _edge_volume_share(bins, edge="high")
    vol_low = _edge_volume_share(bins, edge="low")
    buy_hi, sell_hi = _aggressor_at_edge(bins, edge="high")
    buy_lo, sell_lo = _aggressor_at_edge(bins, edge="low")
    edge_hi = buy_hi + sell_hi
    edge_lo = buy_lo + sell_lo
    delta_hi = buy_hi - sell_hi
    delta_lo = buy_lo - sell_lo

    buy_tot = sum(float(b.get("buy_aggressor_volume") or 0.0) for b in bins)
    sell_tot = sum(float(b.get("sell_aggressor_volume") or 0.0) for b in bins)
    delta = buy_tot - sell_tot
    de = abs(delta) / total if total > 0 else 0.0

    upper_rej = bool(vol_high >= 0.28 and cp < 0.45 and upper_wick >= body * 0.6)
    lower_rej = bool(vol_low >= 0.28 and cp > 0.55 and lower_wick >= body * 0.6)
    if edge_hi > 0 and (sell_hi / edge_hi) >= 0.58 and cp < 0.5:
        upper_rej = True
    if edge_lo > 0 and (buy_lo / edge_lo) >= 0.58 and cp > 0.5:
        lower_rej = True

    unfinished = bool(
        np.isfinite(poc_f) and spread > 0 and abs(c - poc_f) / spread >= 0.35 and total > 0
    )
    ts = pd.Timestamp(candle_row["timestamp"])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    return {
        "timestamp": ts,
        "fp_ok": bool(prof.get("ok")),
        "fp_trade_count": trade_count,
        "fp_volume": total,
        "fp_buy_volume": buy_tot,
        "fp_sell_volume": sell_tot,
        "fp_delta": delta,
        "fp_delta_efficiency": de,
        "fp_poc_price": poc_f if np.isfinite(poc_f) else None,
        "fp_poc_position": float(poc_pos),
        "fp_vol_at_high_share": float(vol_high),
        "fp_vol_at_low_share": float(vol_low),
        "fp_delta_at_high": float(delta_hi),
        "fp_delta_at_low": float(delta_lo),
        "fp_bin_count": int(len(bins)),
        "fp_upper_rejection": upper_rej,
        "fp_lower_rejection": lower_rej,
        "fp_unfinished": unfinished,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "spread": spread,
        "body": body,
        "close_position": cp,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "candle_type": str(candle_row.get("candle_type") or "unknown"),
        "spread_zscore": float(candle_row["spread_zscore"])
        if pd.notna(candle_row.get("spread_zscore"))
        else 0.0,
        "volume_zscore_candle": float(candle_row["volume_zscore"])
        if pd.notna(candle_row.get("volume_zscore"))
        else 0.0,
    }


def _synthesize_aes_volume_response(feat: pd.DataFrame) -> pd.DataFrame:
    n = len(feat)
    vol = feat["fp_volume"].to_numpy(dtype=float)
    vol_mean = pd.Series(vol).rolling(20, min_periods=5).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        rv = np.where(vol_mean > 0, np.clip(vol / vol_mean, 0.05, 30.0), 1.0)
    vz = (
        (pd.Series(vol) - pd.Series(vol_mean))
        / pd.Series(vol).rolling(20, min_periods=5).std().replace(0, np.nan)
    ).fillna(0.0).clip(-5, 8).to_numpy()

    de = feat["fp_delta_efficiency"].to_numpy(dtype=float)
    cp = feat["close_position"].to_numpy(dtype=float)
    sz = feat["spread_zscore"].to_numpy(dtype=float)
    body = feat["body"].to_numpy(dtype=float)
    spread = feat["spread"].to_numpy(dtype=float)
    poc_pos = feat["fp_poc_position"].fillna(0.5).to_numpy(dtype=float)
    vol_hi = feat["fp_vol_at_high_share"].to_numpy(dtype=float)
    vol_lo = feat["fp_vol_at_low_share"].to_numpy(dtype=float)
    upper_rej = feat["fp_upper_rejection"].to_numpy(dtype=bool)
    lower_rej = feat["fp_lower_rejection"].to_numpy(dtype=bool)
    unfinished_fp = feat["fp_unfinished"].to_numpy(dtype=bool)

    with np.errstate(divide="ignore", invalid="ignore"):
        relative_spread = np.clip((sz + 2.0) / 2.0, 0.05, 20.0)

    close_acceptance = np.abs(cp - 0.5) * 2.0
    rejection_penalty = upper_rej.astype(float) * 0.45 + lower_rej.astype(float) * 0.45
    edge_conc = np.maximum(vol_hi, vol_lo)
    effort_score = (rv + de + relative_spread + 0.35 * np.clip(edge_conc * 3.0, 0, 2)) / 3.35
    poc_accept = 1.0 - np.clip(np.abs(cp - poc_pos) * 2.0, 0, 1)
    result_score = (
        0.55 * close_acceptance
        + 0.45 * poc_accept
        + relative_spread * close_acceptance * 0.15
        - rejection_penalty
    )
    effort_result_ratio = result_score / (effort_score + 0.001)
    normalized_result = effort_result_ratio * (1.0 / (1.0 + rejection_penalty))

    is_climax = (vz >= 1.6) & (rv >= 1.9) & (np.abs(sz) >= 1.0)
    is_stopping = (rv >= 1.4) & (de < 0.38) & (upper_rej | lower_rej) & (edge_conc >= 0.25)
    is_stopping = is_stopping | (
        (rv >= 1.6) & unfinished_fp & (edge_conc >= 0.3) & (de < 0.35)
    )

    participation_state = np.full(n, "NORMAL_PARTICIPATION", dtype=object)
    participation_state = np.where(vz >= 1.3, "ELEVATED_PARTICIPATION", participation_state)
    participation_state = np.where(is_climax, "CLIMACTIC_PARTICIPATION", participation_state)

    climax_state = np.full(n, "NO_CLIMAX", dtype=object)
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
        (body > spread * 0.65) & (de > 0.4) & (rv > 1.25) & (poc_accept > 0.55),
        "CONTINUATION_VOLUME",
        volume_event,
    )
    volume_event = np.where(
        (cp <= 0.28) & (de < 0.32) & (rv > 1.15), "ABSORPTION_VOLUME", volume_event
    )
    volume_event = np.where((rv > 2.0) & (de < 0.28), "EXHAUSTION_VOLUME", volume_event)
    volume_event = np.where(is_stopping, "STOPPING_VOLUME", volume_event)
    volume_event = np.where(
        is_climax & (normalized_result <= 0.5), "EXHAUSTION_VOLUME", volume_event
    )

    effort_result_state = np.full(n, "BALANCED_RESPONSE", dtype=object)
    effort_result_state = np.where(
        (effort_score > 1.15) & (normalized_result < 0.55),
        "ABSORPTION_RESPONSE",
        effort_result_state,
    )
    effort_result_state = np.where(
        (effort_score > 1.15) & (normalized_result > 1.0),
        "EFFICIENT_CONTINUATION",
        effort_result_state,
    )
    effort_result_state = np.where(
        (rv > 1.9) & (normalized_result < 0.4), "EXHAUSTION_RESPONSE", effort_result_state
    )
    effort_result_state = np.where(is_stopping, "ABSORPTION_RESPONSE", effort_result_state)

    localized = np.full(n, "UNKNOWN", dtype=object)
    localized = np.where(poc_pos >= 0.7, "localized_distribution", localized)
    localized = np.where(poc_pos <= 0.3, "localized_absorption", localized)
    localized = np.where(cp >= 0.75, "localized_distribution", localized)
    localized = np.where(cp <= 0.25, "localized_absorption", localized)

    unfinished = unfinished_fp | ((effort_score > 1.0) & (normalized_result < 0.3))
    unfinished_reason = np.full(n, "NONE", dtype=object)
    unfinished_reason = np.where(unfinished_fp, "POC_NOT_ACCEPTED_BY_CLOSE", unfinished_reason)
    unfinished_reason = np.where(
        (effort_score > 1.0) & (normalized_result < 0.3),
        "INEFFICIENT_AUCTION",
        unfinished_reason,
    )

    volume_class = np.full(n, "high_average", dtype=object)
    volume_class = np.where(vz < -0.7, "low_small", volume_class)
    volume_class = np.where(is_stopping, "stopping", volume_class)
    volume_class = np.where(is_climax, "climax", volume_class)

    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(feat["timestamp"], utc=True),
            "volume_event": volume_event,
            "continuation_quality": np.where(
                volume_event == "STOPPING_VOLUME",
                "AUCTION_STALLED",
                np.where(volume_event == "ABSORPTION_VOLUME", "PASSIVE_DEFENSE", "NEUTRAL"),
            ),
            "climax_state": climax_state,
            "effort_result_state": effort_result_state,
            "volume_class": volume_class,
            "relative_volume": rv,
            "relative_spread": relative_spread,
            "delta_efficiency": de,
            "localized_behavior": localized,
            "delta": feat["fp_delta"].to_numpy(dtype=float),
            "effort_score": effort_score,
            "result_score": result_score,
            "normalized_result": normalized_result,
            "effort_result_ratio": effort_result_ratio,
            "participation_state": participation_state,
            "unfinished_auction": unfinished,
            "unfinished_reason": unfinished_reason,
            "upper_rejection": upper_rej,
            "lower_rejection": lower_rej,
            "volume_zscore": vz,
            "fp_poc_position": poc_pos,
            "fp_vol_at_high_share": vol_hi,
            "fp_vol_at_low_share": vol_lo,
            "fp_trade_count": feat["fp_trade_count"].to_numpy(),
            "fp_volume": vol,
            "proxy_source": "TIP_FOOTPRINT_M15_V1",
            "evaluation_mode": "CLOSED_BAR_EXACT_FOOTPRINT",
            "fidelity_note": "exact_aggTrade_price_bins→AES_volume_response; not live tip-engine",
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tick-repo", type=Path, default=DEFAULT_TICK_REPO)
    parser.add_argument("--candle", type=Path, default=DEFAULT_CANDLE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--from", dest="from_ts", default="2026-05-28T00:00:00Z")
    parser.add_argument("--to", dest="to_ts", default="2026-07-02T00:00:00Z")
    args = parser.parse_args()

    _assert_tiger(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.audit_dir.mkdir(parents=True, exist_ok=True)

    start = pd.Timestamp(args.from_ts).to_pydatetime()
    end = pd.Timestamp(args.to_ts).to_pydatetime()
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    candle = pd.read_parquet(args.candle)
    candle["timestamp"] = pd.to_datetime(candle["timestamp"], utc=True)
    candle = (
        candle[
            (candle["timestamp"] >= pd.Timestamp(start))
            & (candle["timestamp"] < pd.Timestamp(end))
        ]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    print(f"candle_bars={len(candle)} window={start}→{end}", flush=True)

    feat_rows: list[dict] = []
    n_trades = 0
    cur = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while cur < end_ts:
        nxt = min(cur + pd.Timedelta(hours=24), end_ts)
        print(f"chunk {cur.isoformat()} → {nxt.isoformat()}", flush=True)
        trades = load_agg_trades(
            repo=args.tick_repo,
            start=cur.to_pydatetime(),
            end=(nxt - pd.Timedelta(microseconds=1)).to_pydatetime(),
        )
        n_trades += int(len(trades))
        if not trades.empty:
            t = trades.copy()
            t["_ts"] = pd.to_datetime(t["_ts"], utc=True)
            t["_bar"] = t["_ts"].dt.floor("15min")
            grouped = {
                k: g.drop(columns=["_bar"], errors="ignore")
                for k, g in t.groupby("_bar", sort=False)
            }
        else:
            grouped = {}
        day_candles = candle[(candle["timestamp"] >= cur) & (candle["timestamp"] < nxt)]
        for _, crow in day_candles.iterrows():
            ts = pd.Timestamp(crow["timestamp"])
            feat_rows.append(
                _features_for_bar(candle_row=crow, trades=grouped.get(ts, pd.DataFrame()))
            )
        del trades, grouped
        cur = nxt

    feat = pd.DataFrame(feat_rows)
    print(f"feature_bars={len(feat)} trades_seen={n_trades}", flush=True)
    feat_path = args.out_dir / "m15_footprint_features.parquet"
    feat.to_parquet(feat_path, index=False)

    vr = _synthesize_aes_volume_response(feat)
    vr_path = args.out_dir / "volume_response_state_footprint.parquet"
    vr.to_parquet(vr_path, index=False)

    cls = candle.merge(
        vr[
            [
                "timestamp",
                "volume_class",
                "volume_zscore",
                "delta",
                "upper_rejection",
                "lower_rejection",
            ]
        ],
        on="timestamp",
        how="inner",
    )
    class_path = args.out_dir / "volume_classification_memory_footprint.parquet"
    cls.to_parquet(class_path, index=False)

    summary = {
        "generated_at": _utc_now(),
        "fidelity": "TIP_FOOTPRINT_M15_V1",
        "auction_fidelity_tag": "PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1",
        "n_trades_seen": int(n_trades),
        "n_bars": int(len(vr)),
        "feat_path": str(feat_path),
        "vr_path": str(vr_path),
        "class_path": str(class_path),
        "fp_ok_bars": int(feat["fp_ok"].sum()) if "fp_ok" in feat.columns else None,
        "volume_event_counts": {
            str(k): int(v) for k, v in vr["volume_event"].value_counts().items()
        },
        "participation_counts": {
            str(k): int(v) for k, v in vr["participation_state"].value_counts().items()
        },
        "climax_counts": {str(k): int(v) for k, v in vr["climax_state"].value_counts().items()},
        "stopping_volume_bars": int((vr["volume_event"] == "STOPPING_VOLUME").sum()),
        "climactic_participation_bars": int(
            (vr["participation_state"] == "CLIMACTIC_PARTICIPATION").sum()
        ),
        "unfinished_bars": int(vr["unfinished_auction"].sum()),
        "note_ru": "Exact footprint bins→AES volume_response. Не VSA-восьмёрка.",
    }
    for path in (
        args.out_dir / "footprint_volume_response_summary.json",
        args.audit_dir / "footprint_volume_response_summary.json",
    ):
        path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
