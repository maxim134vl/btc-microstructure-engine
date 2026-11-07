"""Build higher-TF ETLL market packs from the M15 pack (same external window)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from btc_ml.external_traders.market_pack import _to_utc_series, resolve_external_window

TF_MINUTES: dict[str, int] = {
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
}

PACK_VERSION = "btc_tf_market_pack_from_m15_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tf_key(timeframe: str) -> str:
    return str(timeframe or "").upper()


def resample_m15_feed_to_tf(feed_m15: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate M15 native feed to M30/H1/H4 (OHLCV + taker sums)."""
    tf = _tf_key(timeframe)
    minutes = TF_MINUTES.get(tf)
    if minutes is None or minutes <= 15:
        raise ValueError(f"unsupported target timeframe: {tf}")
    if minutes % 15 != 0:
        raise ValueError(f"timeframe {tf} not divisible from M15")

    work = feed_m15.copy()
    work["timestamp"] = _to_utc_series(work["timestamp"])
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").set_index("timestamp")
    rule = f"{minutes}min"
    agg: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    for col in ("taker_buy_volume", "buy_volume", "sell_volume", "delta", "number_of_trades", "quote_asset_volume"):
        if col in work.columns:
            agg[col] = "sum"
    out = work.resample(rule, label="left", closed="left").agg(agg)
    out = out.dropna(subset=["open"]).reset_index()
    return out


def build_btc_tf_market_pack_from_m15(
    *,
    source_m15_pack: Path,
    output_dir: Path,
    timeframe: str,
) -> dict[str, Any]:
    """Clone external window from M15 pack; build TF bars/feed/clock."""
    tf = _tf_key(timeframe)
    minutes = TF_MINUTES.get(tf)
    if minutes is None or minutes <= 15:
        raise ValueError(f"unsupported timeframe: {tf}")

    feed_m15_path = source_m15_pack / "feed_m15.parquet"
    external_path = source_m15_pack / "external_positions_btcusdt_ok.parquet"
    if not feed_m15_path.exists():
        raise FileNotFoundError(feed_m15_path)
    if not external_path.exists():
        raise FileNotFoundError(external_path)

    feed_m15 = pd.read_parquet(feed_m15_path)
    feed_tf = resample_m15_feed_to_tf(feed_m15, tf)

    delta = pd.Timedelta(minutes=minutes)
    bars = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "timeframe": tf,
            "bar_open": feed_tf["timestamp"],
            "bar_close": feed_tf["timestamp"] + delta,
            "open": feed_tf["open"],
            "high": feed_tf["high"],
            "low": feed_tf["low"],
            "close": feed_tf["close"],
            "volume": feed_tf["volume"],
        }
    )

    clock = pd.DataFrame(
        {
            "evaluation_timestamp": bars["bar_close"],
            "timeframe": tf,
            "source_bar_open": bars["bar_open"],
            "source_bar_close": bars["bar_close"],
            "availability_status": "FRESH_EVENT",
            "symbol": "BTCUSDT",
        }
    )

    tf_lower = tf.lower()
    output_dir.mkdir(parents=True, exist_ok=True)
    bars_out = output_dir / f"bars_{tf_lower}.parquet"
    feed_out = output_dir / f"feed_{tf_lower}.parquet"
    clock_out = output_dir / f"evaluation_clock_{tf_lower}.parquet"
    external_out = output_dir / "external_positions_btcusdt_ok.parquet"
    manifest_out = output_dir / "manifest.json"

    bars.to_parquet(bars_out, index=False)
    feed_tf.to_parquet(feed_out, index=False)
    clock.to_parquet(clock_out, index=False)
    pd.read_parquet(external_path).to_parquet(external_out, index=False)

    pack_end = bars["bar_close"].max()
    manifest = {
        "pack_version": PACK_VERSION,
        "generated_at": _utc_now(),
        "symbol": "BTCUSDT",
        "timeframe": tf,
        "source_m15_pack": str(source_m15_pack),
        "note_ru": (
            f"BTC {tf} pack агрегирован из M15 feed того же ETLL окна. "
            "Для честного канона нужны context + lived replay на этом TF."
        ),
        "window": {
            "pack_bar_open_first": bars["bar_open"].min().isoformat().replace("+00:00", "Z"),
            "pack_bar_close_last": pack_end.isoformat().replace("+00:00", "Z"),
            "bars_in_pack": int(len(bars)),
        },
        "outputs": {
            f"bars_{tf_lower}": str(bars_out),
            f"feed_{tf_lower}": str(feed_out),
            f"evaluation_clock_{tf_lower}": str(clock_out),
            "external_positions_btcusdt_ok": str(external_out),
            "manifest": str(manifest_out),
        },
        "status": "PACK_READY_LIVED_REPLAY_PENDING_CONTEXT",
    }
    manifest_out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest
