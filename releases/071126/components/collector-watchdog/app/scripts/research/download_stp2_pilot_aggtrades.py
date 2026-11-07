#!/usr/bin/env python3
"""P1: Download Binance UM BTCUSDT aggTrades and convert to STP-readable partitions.

Writes under a research tree (does not mutate live raw_market_events_v2 ingest).
Layout matches load_agg_trades(): data/raw_market_events_v2/agg_trade/date=/hour=/*.parquet

Processes one daily zip at a time to avoid OOM on monthly archives.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = (
    ROOT
    / "data/research/external_traders/market_pack_btc_m15/stp2_pilot"
    / "tick_pack_202606"
)
VISION_DAILY = (
    "https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/"
    "BTCUSDT-aggTrades-{date}.zip"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, *, retries: int = 5) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return {
            "url": url,
            "path": str(dest),
            "bytes": dest.stat().st_size,
            "sha256": _sha256(dest),
            "cached": True,
        }
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "btc-ml-stp2-pilot/1.0"})
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = resp.read()
            if not data:
                raise RuntimeError("empty response body")
            dest.write_bytes(data)
            return {
                "url": url,
                "path": str(dest),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "cached": False,
                "http_status": getattr(resp, "status", None),
                "attempt": attempt,
            }
        except Exception as exc:
            last_exc = exc
            if dest.exists():
                dest.unlink(missing_ok=True)
            print(f"  download attempt {attempt}/{retries} failed: {exc}", flush=True)
    raise RuntimeError(f"download failed after {retries} attempts: {url}") from last_exc


def _daterange(start: datetime, end_exclusive: datetime) -> list[datetime]:
    out: list[datetime] = []
    cur = start
    while cur < end_exclusive:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _read_binance_zip(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            raise RuntimeError(f"no csv in {zip_path}")
        raw = zf.read(names[0])
    cols = [
        "aggregate_trade_id",
        "price",
        "quantity",
        "first_trade_id",
        "last_trade_id",
        "timestamp_ms",
        "buyer_is_market_maker",
    ]
    bio = io.BytesIO(raw)
    peek = raw[:64].decode("utf-8", errors="ignore")
    header = peek.lower().startswith("agg") or "price" in peek.lower()
    df = pd.read_csv(
        bio,
        header=0 if header else None,
        names=None if header else cols,
    )
    if header:
        rename = {
            "a": "aggregate_trade_id",
            "p": "price",
            "q": "quantity",
            "f": "first_trade_id",
            "l": "last_trade_id",
            "T": "timestamp_ms",
            "m": "buyer_is_market_maker",
            "agg_trade_id": "aggregate_trade_id",
            "transact_time": "timestamp_ms",
            "is_buyer_maker": "buyer_is_market_maker",
        }
        df = df.rename(columns={c: rename.get(c, c) for c in df.columns})
        lower_map = {c.lower(): c for c in df.columns}
        for src, dst in [
            ("agg_trade_id", "aggregate_trade_id"),
            ("aggregate_trade_id", "aggregate_trade_id"),
            ("price", "price"),
            ("quantity", "quantity"),
            ("first_trade_id", "first_trade_id"),
            ("last_trade_id", "last_trade_id"),
            ("transact_time", "timestamp_ms"),
            ("timestamp", "timestamp_ms"),
            ("is_buyer_maker", "buyer_is_market_maker"),
        ]:
            if src in lower_map and dst not in df.columns:
                df[dst] = df[lower_map[src]]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"missing columns {missing} in {zip_path}; got {list(df.columns)}")
    return df[cols].copy()


def _to_stp_frame(df: pd.DataFrame, *, ingested_at: str) -> pd.DataFrame:
    ts = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    iso = ts.dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3] + "Z"
    price = df["price"].astype(float)
    qty = df["quantity"].astype(float)
    return pd.DataFrame(
        {
            "schema_version": "stp2_pilot_binance_vision_v1",
            "stream_type": "aggTrade",
            "symbol": "BTCUSDT",
            "exchange_event_timestamp": iso,
            "exchange_trade_timestamp": iso,
            "local_receive_timestamp": iso,
            "local_receive_monotonic_ns": ts.astype("int64"),
            "aggregate_trade_id": df["aggregate_trade_id"].astype("int64"),
            "first_trade_id": df["first_trade_id"].astype("int64"),
            "last_trade_id": df["last_trade_id"].astype("int64"),
            "price": price,
            "quantity": qty,
            "quote_quantity": price * qty,
            "buyer_is_market_maker": df["buyer_is_market_maker"].astype(bool),
            "connection_session_id": "binance_vision_stp2_pilot",
            "reconnect_generation": 0,
            "source_sequence": df["aggregate_trade_id"].astype("int64"),
            "raw_payload_hash": "",
            "ingested_at": ingested_at,
            "date": ts.dt.strftime("%Y-%m-%d"),
            "hour": ts.dt.strftime("%H"),
        }
    )


def _write_hour_partitions(
    df: pd.DataFrame,
    agg_root: Path,
    *,
    stats: dict,
) -> None:
    for (date, hour), part in df.groupby(["date", "hour"], sort=True):
        hour_dir = agg_root / f"date={date}" / f"hour={hour}"
        hour_dir.mkdir(parents=True, exist_ok=True)
        path = hour_dir / f"agg_trade__binance_vision__{date}T{hour}.parquet"
        part = part.sort_values("aggregate_trade_id").reset_index(drop=True)
        if path.exists():
            prev = pd.read_parquet(path)
            part = (
                pd.concat([prev, part], ignore_index=True)
                .drop_duplicates(subset=["aggregate_trade_id"], keep="first")
                .sort_values("aggregate_trade_id")
                .reset_index(drop=True)
            )
        part.to_parquet(path, index=False)
        stats["parquet_files"] = int(stats.get("parquet_files", 0)) + 1
        stats["rows_written"] = int(stats.get("rows_written", 0)) + len(part)
        stats.setdefault("hour_keys", set()).add(f"{date}T{hour}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--from", dest="from_ts", default="2026-05-28T00:00:00Z")
    parser.add_argument("--to", dest="to_ts", default="2026-07-02T00:00:00Z")
    parser.add_argument("--fresh", action="store_true", help="Delete existing repo partitions")
    parser.add_argument("--start-day", default=None, help="Resume from YYYY-MM-DD (inclusive)")
    args = parser.parse_args()

    start = pd.Timestamp(args.from_ts).to_pydatetime()
    end = pd.Timestamp(args.to_ts).to_pydatetime()
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    out_dir: Path = args.out_dir
    zip_dir = out_dir / "binance_vision_zips"
    repo_root = out_dir / "repo"
    agg_root = repo_root / "data" / "raw_market_events_v2" / "agg_trade"
    if args.fresh and agg_root.exists():
        shutil.rmtree(agg_root)
    agg_root.mkdir(parents=True, exist_ok=True)

    # Daily-only plan for entire padded window.
    day_start = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    day_end = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    if end.hour or end.minute or end.second:
        day_end += timedelta(days=1)

    downloads: list[dict] = []
    ingested_at = _utc_now()
    stats: dict = {"parquet_files": 0, "rows_written": 0, "hour_keys": set(), "rows_clipped_total": 0}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    for d in _daterange(day_start, day_end):
        day = d.strftime("%Y-%m-%d")
        if args.start_day and day < str(args.start_day):
            continue
        url = VISION_DAILY.format(date=day)
        dest = zip_dir / f"BTCUSDT-aggTrades-{day}.zip"
        print(f"DOWNLOAD {day}", flush=True)
        meta = _download(url, dest)
        meta["day"] = day
        downloads.append(meta)
        print(
            f"  bytes={meta['bytes']} cached={meta['cached']} sha256={meta['sha256'][:16]}...",
            flush=True,
        )
        raw = _read_binance_zip(dest)
        framed = _to_stp_frame(raw, ingested_at=ingested_at)
        ts = pd.to_datetime(framed["exchange_trade_timestamp"], utc=True)
        clipped = framed.loc[(ts >= start_ts) & (ts < end_ts)].copy()
        stats["rows_clipped_total"] += int(len(clipped))
        _write_hour_partitions(clipped, agg_root, stats=stats)
        print(f"  parsed={len(raw)} clipped={len(clipped)}", flush=True)
        del raw, framed, clipped

    hour_keys = stats.pop("hour_keys")
    present_hours = len(hour_keys)
    expected_hours = int((end_ts - start_ts).total_seconds() // 3600)
    dates = sorted({p.name for p in agg_root.glob("date=*")})

    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from btc_ml.trading.shadow_structural_protection.trades import load_agg_trades

    sample = load_agg_trades(repo=repo_root, start=start, end=end - timedelta(microseconds=1))
    manifest = {
        "generated_at": ingested_at,
        "stage": "STP2_PILOT_P1_TICK_PACK",
        "status": "TICK_PACK_READY" if len(sample) > 0 else "TICK_PACK_EMPTY",
        "symbol": "BTCUSDT",
        "market": "binance_um_futures",
        "source": "data.binance.vision",
        "mode": "daily_streaming",
        "window": {"from": args.from_ts, "to": args.to_ts},
        "downloads": downloads,
        "rows_clipped_total": stats["rows_clipped_total"],
        "rows_loader_sample": int(len(sample)),
        "write_stats": {
            "parquet_files_touched": stats["parquet_files"],
            "rows_written_cumulative": stats["rows_written"],
            "hour_partitions_present": present_hours,
        },
        "date_partitions": dates,
        "hour_partitions_expected": expected_hours,
        "hour_coverage_pct": round(100.0 * present_hours / max(expected_hours, 1), 4),
        "agg_trade_root": str(agg_root),
        "repo_root_for_stp_loader": str(repo_root),
        "live_store_mutated": False,
        "fidelity": "EXACT_AGG_TRADE",
        "approximation_used": False,
        "next_step": "P2_FILTER_RUNNER",
        "next_step_ru": "Написать research runner STP2 filter overlay на pilot universe.",
    }
    for path in (
        out_dir / "tick_pack_manifest.json",
        ROOT / "output/audits/etll_lived_replay_20260825/stp2_pilot/tick_pack_manifest.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                k: manifest[k]
                for k in [
                    "status",
                    "rows_clipped_total",
                    "rows_loader_sample",
                    "hour_coverage_pct",
                    "write_stats",
                    "repo_root_for_stp_loader",
                    "next_step",
                ]
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if manifest["status"] == "TICK_PACK_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
