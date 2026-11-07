#!/usr/bin/env python3
"""Build AES-compatible volume_response from exact aggTrade tip aggregates (M15).

Reads tick pack on MaksTiger; writes tip volume_response on MaksTiger.
Does not overwrite pack V2 volume_response on system disk.

Fidelity: TIP_AGGTRADE_M15_AGGREGATE — exact Binance UM aggTrades rolled to M15,
not live tip-engine / footprint localization.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.shadow_structural_protection.trades import load_agg_trades  # noqa: E402

DEFAULT_TICK_REPO = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_tip/tick_pack_202606/repo"
)
DEFAULT_OUT = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_tip/tip_volume_response_202606"
)
DEFAULT_CANDLE = (
    ROOT
    / "data/research/external_traders/market_pack_btc_m15/context/candle_structure_memory.parquet"
)
DEFAULT_AUDIT = ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_june"
REQUIRE_VOLUME = Path("/Volumes/MaksTiger")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _assert_tiger(out_dir: Path) -> None:
    if not REQUIRE_VOLUME.exists():
        raise SystemExit(f"REQUIRED_VOLUME_NOT_MOUNTED: {REQUIRE_VOLUME}")
    out_dir = out_dir if out_dir.exists() else out_dir
    resolved = out_dir.resolve() if out_dir.exists() else out_dir.absolute()
    if not str(resolved).startswith(str(REQUIRE_VOLUME.resolve())):
        raise SystemExit(f"REFUSING_WRITE_OUTSIDE_VOLUME: {out_dir}")
    st = os.statvfs(REQUIRE_VOLUME)
    free = st.f_bavail * st.f_frsize
    if free < 5 * (1024**3):
        raise SystemExit(f"INSUFFICIENT_FREE_SPACE on MaksTiger: {free / (1024**3):.1f} GiB")


def _bar_rows_from_trades(trades: pd.DataFrame) -> list[dict]:
    """Aggregate one chunk of trades into M15 bar open rows."""
    if trades.empty:
        return []
    t = trades.copy()
    t["_ts"] = pd.to_datetime(t["_ts"], utc=True)
    t["bar_open"] = t["_ts"].dt.floor("15min")
    maker_col = None
    for cand in ("buyer_is_market_maker", "is_buyer_maker"):
        if cand in t.columns:
            maker_col = cand
            break
    if maker_col is None:
        buy_qty = t["quantity"].to_numpy() * 0.5
        sell_qty = t["quantity"].to_numpy() * 0.5
    else:
        maker = t[maker_col].astype(bool).to_numpy()
        qty = t["quantity"].to_numpy(dtype=float)
        # buyer is maker => seller-initiated (sell volume)
        sell_qty = np.where(maker, qty, 0.0)
        buy_qty = np.where(~maker, qty, 0.0)
    t["buy_qty"] = buy_qty
    t["sell_qty"] = sell_qty
    t["signed_qty"] = t["buy_qty"] - t["sell_qty"]

    rows: list[dict] = []
    for bar_open, g in t.groupby("bar_open", sort=True):
        vol = float(g["quantity"].sum())
        buy = float(g["buy_qty"].sum())
        sell = float(g["sell_qty"].sum())
        delta = buy - sell
        quote = (
            float(g["quote_quantity"].sum())
            if "quote_quantity" in g.columns
            else float((g["price"] * g["quantity"]).sum())
        )
        ts = pd.Timestamp(bar_open)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        rows.append(
            {
                "timestamp": ts,
                "tip_trade_count": int(len(g)),
                "tip_volume": vol,
                "tip_buy_volume": buy,
                "tip_sell_volume": sell,
                "tip_delta": delta,
                "tip_abs_delta": float(np.abs(g["signed_qty"]).sum()),
                "tip_quote_volume": quote,
                "tip_vwap": float((g["price"] * g["quantity"]).sum() / max(vol, 1e-12)),
            }
        )
    return rows


def _stream_tip_m15(
    *,
    tick_repo: Path,
    start: datetime,
    end: datetime,
    chunk_hours: int = 24,
) -> tuple[pd.DataFrame, int]:
    """Day-chunked aggTrade → M15 tip features (avoids full-span OOM)."""
    rows: list[dict] = []
    n_trades = 0
    cur = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while cur < end_ts:
        nxt = min(cur + pd.Timedelta(hours=chunk_hours), end_ts)
        print(f"  chunk {cur.isoformat()} → {nxt.isoformat()}", flush=True)
        trades = load_agg_trades(
            repo=tick_repo,
            start=cur.to_pydatetime(),
            end=(nxt - pd.Timedelta(microseconds=1)).to_pydatetime(),
        )
        n_trades += int(len(trades))
        rows.extend(_bar_rows_from_trades(trades))
        del trades
        cur = nxt
    if not rows:
        raise RuntimeError("no aggTrades loaded")
    tip = pd.DataFrame(rows)
    # Chunk boundaries can duplicate the last/first bar open — re-sum.
    tip = (
        tip.groupby("timestamp", as_index=False)
        .agg(
            {
                "tip_trade_count": "sum",
                "tip_volume": "sum",
                "tip_buy_volume": "sum",
                "tip_sell_volume": "sum",
                "tip_delta": "sum",
                "tip_abs_delta": "sum",
                "tip_quote_volume": "sum",
                "tip_vwap": "mean",  # approx; rewritten below
            }
        )
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    tip["tip_vwap"] = tip["tip_quote_volume"] / tip["tip_volume"].clip(lower=1e-12)
    tip["tip_delta_efficiency"] = np.where(
        tip["tip_volume"] > 0, tip["tip_delta"].abs() / tip["tip_volume"], 0.0
    )
    tip["tip_imbalance"] = np.where(
        tip["tip_volume"] > 0, tip["tip_delta"] / tip["tip_volume"], 0.0
    )
    vol_mean = tip["tip_volume"].rolling(20, min_periods=5).mean()
    cnt_mean = tip["tip_trade_count"].rolling(20, min_periods=5).mean()
    tip["tip_relative_volume"] = (
        (tip["tip_volume"] / vol_mean.replace(0, np.nan)).fillna(1.0).clip(0.05, 30.0)
    )
    tip["tip_relative_trades"] = (
        (tip["tip_trade_count"] / cnt_mean.replace(0, np.nan)).fillna(1.0).clip(0.05, 30.0)
    )
    tip["tip_volume_z"] = (
        (tip["tip_volume"] - vol_mean)
        / tip["tip_volume"].rolling(20, min_periods=5).std().replace(0, np.nan)
    ).fillna(0.0).clip(-5, 8)
    return tip, n_trades


def _aggregate_tip_to_m15(
    tip: pd.DataFrame,
    candle: pd.DataFrame,
) -> pd.DataFrame:
    """Join tip M15 aggregates onto candle structure rows."""
    candle = candle.copy()
    candle["timestamp"] = pd.to_datetime(candle["timestamp"], utc=True)
    tip = tip.copy()
    tip["timestamp"] = pd.to_datetime(tip["timestamp"], utc=True)
    merged = candle.merge(tip, on="timestamp", how="inner", suffixes=("", "_tip"))
    return merged


def _synthesize_tip_volume_response(merged: pd.DataFrame) -> pd.DataFrame:
    n = len(merged)
    vz = pd.to_numeric(merged.get("tip_volume_z"), errors="coerce").fillna(0.0).to_numpy()
    rv = pd.to_numeric(merged.get("tip_relative_volume"), errors="coerce").fillna(1.0).to_numpy()
    rt = pd.to_numeric(merged.get("tip_relative_trades"), errors="coerce").fillna(1.0).to_numpy()
    de = pd.to_numeric(merged.get("tip_delta_efficiency"), errors="coerce").fillna(0.0).to_numpy()
    imb = pd.to_numeric(merged.get("tip_imbalance"), errors="coerce").fillna(0.0).to_numpy()
    body = pd.to_numeric(merged.get("body"), errors="coerce").fillna(0.0).to_numpy()
    spread = pd.to_numeric(merged.get("spread"), errors="coerce").fillna(0.0).to_numpy()
    upper = pd.to_numeric(merged.get("upper_wick"), errors="coerce").fillna(0.0).to_numpy()
    lower = pd.to_numeric(merged.get("lower_wick"), errors="coerce").fillna(0.0).to_numpy()
    cp = pd.to_numeric(merged.get("close_position"), errors="coerce").fillna(0.5).to_numpy()
    ctype = merged.get("candle_type", pd.Series(["unknown"] * n)).astype(str).to_numpy()
    sz = pd.to_numeric(merged.get("spread_zscore"), errors="coerce").fillna(0.0).to_numpy()

    with np.errstate(divide="ignore", invalid="ignore"):
        relative_spread = np.where(
            (sz == sz),
            np.clip((sz + 2.0) / 2.0, 0.05, 20.0),
            1.0,
        )

    upper_rejection = (upper > body) & (cp < 0.45) & (spread > 0)
    lower_rejection = (lower > body) & (cp > 0.55) & (spread > 0)
    close_acceptance = np.abs(cp - 0.5) * 2.0
    rejection_penalty = upper_rejection.astype(float) * 0.4 + lower_rejection.astype(float) * 0.4

    # Tip-aware effort: participation + delta efficiency + relative spread
    effort_score = (rv + de + relative_spread + 0.25 * np.clip(rt / 3.0, 0, 2)) / 3.25
    result_score = close_acceptance + relative_spread * close_acceptance - rejection_penalty
    effort_result_ratio = result_score / (effort_score + 0.001)
    normalized_result = effort_result_ratio * (1.0 / (1.0 + rejection_penalty))

    # Climax-like: extreme tip participation + large range
    is_climax = (vz >= 1.8) & (rv >= 2.0) & (np.abs(sz) >= 1.2)
    # Stopping: high tip participation, weak delta efficiency, reclaim wick
    is_stopping = (rv >= 1.6) & (de < 0.35) & (upper_rejection | lower_rejection)
    # also classic bearish reclaim stopping
    is_stopping = is_stopping | (
        (ctype == "bearish") & (vz > 0.7) & (lower > body) & (cp > 0.5) & (rv >= 1.2)
    )

    participation_state = np.full(n, "NORMAL_PARTICIPATION", dtype=object)
    participation_state = np.where(vz >= 1.5, "ELEVATED_PARTICIPATION", participation_state)
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
        (body > spread * 0.7) & (de > 0.4) & (rv > 1.3),
        "CONTINUATION_VOLUME",
        volume_event,
    )
    volume_event = np.where(
        (cp <= 0.25) & (de < 0.3) & (rv > 1.2),
        "ABSORPTION_VOLUME",
        volume_event,
    )
    volume_event = np.where((rv > 2.2) & (de < 0.25), "EXHAUSTION_VOLUME", volume_event)
    volume_event = np.where(is_stopping, "STOPPING_VOLUME", volume_event)
    volume_event = np.where(is_climax & (normalized_result <= 0.5), "EXHAUSTION_VOLUME", volume_event)

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
        (rv > 2.0) & (normalized_result < 0.4),
        "EXHAUSTION_RESPONSE",
        effort_result_state,
    )
    effort_result_state = np.where(is_stopping, "ABSORPTION_RESPONSE", effort_result_state)

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

    volume_class = np.full(n, "high_average", dtype=object)
    volume_class = np.where(vz < -0.7, "low_small", volume_class)
    volume_class = np.where(is_stopping, "stopping", volume_class)
    volume_class = np.where(is_climax, "climax", volume_class)

    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(merged["timestamp"], utc=True),
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
            "delta": pd.to_numeric(merged.get("tip_delta"), errors="coerce").fillna(0.0),
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
            "tip_trade_count": merged["tip_trade_count"].to_numpy(),
            "tip_volume": merged["tip_volume"].to_numpy(),
            "tip_imbalance": imb,
            "proxy_source": "TIP_AGGTRADE_M15_AGGREGATE",
            "evaluation_mode": "CLOSED_BAR_TIP_AGGREGATE",
            "fidelity_note": "exact_aggTrade_to_M15; not live tip-engine footprint",
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

    print(f"streaming aggTrades {start} → {end} from {args.tick_repo}", flush=True)
    tip, n_trades = _stream_tip_m15(
        tick_repo=args.tick_repo, start=start, end=end, chunk_hours=24
    )
    print(f"  trades={n_trades} tip_bars={len(tip)}", flush=True)
    candle = pd.read_parquet(args.candle)
    candle["timestamp"] = pd.to_datetime(candle["timestamp"], utc=True)
    candle = candle[(candle["timestamp"] >= pd.Timestamp(start)) & (candle["timestamp"] < pd.Timestamp(end))]
    print(f"  candle_bars={len(candle)}", flush=True)

    merged = _aggregate_tip_to_m15(tip, candle)
    print(f"  merged_bars={len(merged)}", flush=True)
    vr = _synthesize_tip_volume_response(merged)

    out_path = args.out_dir / "volume_response_state_tip.parquet"
    class_path = args.out_dir / "volume_classification_memory_tip.parquet"
    vr.to_parquet(out_path, index=False)
    # classification sibling for adapter primary path
    cls = vr[
        [
            "timestamp",
            "volume_class",
            "volume_zscore",
            "delta",
            "upper_rejection",
            "lower_rejection",
        ]
    ].copy()
    # join OHLC from candle for adapter if used as primary
    ohlc = candle[
        [
            c
            for c in (
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "buy_volume",
                "sell_volume",
                "close_position",
                "body",
                "spread",
                "upper_wick",
                "lower_wick",
                "spread_zscore",
                "candle_type",
            )
            if c in candle.columns
        ]
    ]
    cls = ohlc.merge(cls, on="timestamp", how="inner")
    cls.to_parquet(class_path, index=False)

    summary = {
        "generated_at": _utc_now(),
        "fidelity": "TIP_AGGTRADE_M15_AGGREGATE",
        "n_trades": int(n_trades),
        "n_bars": int(len(vr)),
        "out_path": str(out_path),
        "class_path": str(class_path),
        "volume_event_counts": {str(k): int(v) for k, v in vr["volume_event"].value_counts().items()},
        "participation_counts": {
            str(k): int(v) for k, v in vr["participation_state"].value_counts().items()
        },
        "climax_counts": {str(k): int(v) for k, v in vr["climax_state"].value_counts().items()},
        "volume_class_counts": {str(k): int(v) for k, v in vr["volume_class"].value_counts().items()},
        "stopping_volume_bars": int((vr["volume_event"] == "STOPPING_VOLUME").sum()),
        "climactic_participation_bars": int(
            (vr["participation_state"] == "CLIMACTIC_PARTICIPATION").sum()
        ),
    }
    (args.out_dir / "tip_volume_response_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (args.audit_dir / "tip_volume_response_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
