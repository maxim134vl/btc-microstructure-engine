#!/usr/bin/env python3
"""Download Binance native BTCUSDT 15m klines (with taker buy volume) into ETLL pack.

Does not touch live cognition. Writes under market_pack_btc_m15 only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

BASE_URL = "https://data-api.binance.vision"
ENDPOINT = "/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "15m"
INTERVAL_MS = 15 * 60 * 1000

COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]

DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"
DEFAULT_START = "2023-12-17T00:00:00Z"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


def request_json(params: dict, retries: int = 8):
    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}{ENDPOINT}?{query}"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": "btc-ml-etll/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"Binance request failed: {last_error}")


def download_m15(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    cursor = to_ms(start)
    end_ms = to_ms(end)
    rows: list = []
    requests = 0
    while cursor <= end_ms:
        payload = request_json(
            {
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        requests += 1
        if not payload:
            break
        rows.extend(payload)
        last_open = int(payload[-1][0])
        nxt = last_open + INTERVAL_MS
        if nxt <= cursor:
            raise RuntimeError("pagination stuck")
        cursor = nxt
        if requests % 20 == 0:
            print(json.dumps({"progress_requests": requests, "rows": len(rows), "cursor": cursor}), flush=True)
        if len(payload) < 1000:
            break
        time.sleep(0.05)
    if not rows:
        raise RuntimeError("no klines downloaded")
    frame = pd.DataFrame(rows, columns=COLUMNS)
    for col in (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["number_of_trades"] = pd.to_numeric(frame["number_of_trades"], errors="coerce").astype("Int64")
    frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    frame = frame.drop_duplicates(subset=["open_time"], keep="last").sort_values("open_time")
    frame["symbol"] = SYMBOL
    frame["timeframe"] = "M15"
    frame["taker_buy_volume"] = frame["taker_buy_base_volume"]
    frame["buy_volume"] = frame["taker_buy_base_volume"]
    frame["sell_volume"] = (frame["volume"] - frame["taker_buy_base_volume"]).clip(lower=0)
    frame["delta"] = frame["buy_volume"] - frame["sell_volume"]
    print(json.dumps({"download_done": True, "requests": requests, "rows": int(len(frame))}), flush=True)
    return frame.reset_index(drop=True)


def to_feed(native: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": native["open_time"],
            "open": native["open"],
            "high": native["high"],
            "low": native["low"],
            "close": native["close"],
            "volume": native["volume"],
            "taker_buy_volume": native["taker_buy_volume"],
            "buy_volume": native["buy_volume"],
            "sell_volume": native["sell_volume"],
            "delta": native["delta"],
            "number_of_trades": native["number_of_trades"],
            "quote_asset_volume": native["quote_asset_volume"],
        }
    )


def refresh_pack_bars(pack_dir: Path, feed: pd.DataFrame) -> None:
    bars = feed.copy()
    bars["bar_open"] = pd.to_datetime(bars["timestamp"], utc=True)
    bars["bar_close"] = bars["bar_open"] + pd.Timedelta(minutes=15)
    bars["symbol"] = "BTCUSDT"
    bars["timeframe"] = "M15"
    bars_out = bars[
        [
            "symbol",
            "timeframe",
            "bar_open",
            "bar_close",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "taker_buy_volume",
            "buy_volume",
            "sell_volume",
            "delta",
        ]
    ]
    bars_out.to_parquet(pack_dir / "bars_m15.parquet", index=False)
    clock = pd.DataFrame(
        {
            "evaluation_timestamp": bars_out["bar_close"],
            "timeframe": "M15",
            "source_bar_open": bars_out["bar_open"],
            "source_bar_close": bars_out["bar_close"],
            "availability_status": "FRESH_EVENT",
            "symbol": "BTCUSDT",
        }
    )
    clock.to_parquet(pack_dir / "evaluation_clock_m15.parquet", index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--start", type=str, default=DEFAULT_START)
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="UTC end (default: now). Example: 2026-07-24T23:59:00Z",
    )
    parser.add_argument("--skip-context-rebuild", action="store_true")
    args = parser.parse_args()

    pack_dir = args.pack_dir
    pack_dir.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(args.start)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.now(tz="UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")

    native = download_m15(start, end)
    native_path = pack_dir / "binance_native_m15.parquet"
    feed_path = pack_dir / "feed_m15.parquet"
    native.to_parquet(native_path, index=False)
    feed = to_feed(native)
    feed.to_parquet(feed_path, index=False)
    refresh_pack_bars(pack_dir, feed)

    report = {
        "generated_at": _utc_now(),
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
        "rows": int(len(native)),
        "has_taker_buy_volume": True,
        "outputs": {
            "binance_native_m15": str(native_path),
            "feed_m15": str(feed_path),
            "bars_m15": str(pack_dir / "bars_m15.parquet"),
        },
        "note_ru": "Нативные Binance klines с taker buy volume — основа для полного volume/context restore.",
    }

    if not args.skip_context_rebuild:
        from btc_ml.external_traders.rebuild_context import rebuild_btc_m15_historical_context

        ctx = rebuild_btc_m15_historical_context(pack_dir=pack_dir)
        report["context_rebuild"] = {
            "status": ctx.get("status"),
            "lifecycle_active_market_context_counts": ctx.get("lifecycle_active_market_context_counts"),
            "episodes_rows": ctx.get("spans", {}).get("episodes_rows"),
            "fidelity": ctx.get("fidelity"),
        }

    # Update pack manifest
    manifest_path = pack_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    manifest["status"] = "NATIVE_VOLUME_CONTEXT_READY"
    manifest["native_volume"] = {
        "source": "binance_data_api_klines",
        "rows": report["rows"],
        "start": report["start"],
        "end": report["end"],
        "generated_at": report["generated_at"],
    }
    manifest["next_step_ru"] = (
        "Нативный объём Binance загружен и context пересобран. "
        "Дальше — lived replay модели на M15."
    )
    window = manifest.setdefault("window", {})
    window["pack_bar_open_first"] = feed["timestamp"].min().isoformat().replace("+00:00", "Z")
    window["pack_bar_close_last"] = (
        (feed["timestamp"].max() + pd.Timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    )
    window["bars_in_pack"] = int(len(feed))
    window["coverage_gap_after_bars"] = False
    window["coverage_gap_note_ru"] = "Свечи докачаны с Binance API до выбранного end."
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    report_path = pack_dir / "native_volume_download_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
