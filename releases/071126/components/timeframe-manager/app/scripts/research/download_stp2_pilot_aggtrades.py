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
import os
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
# Heavy tick packs live on MaksTiger — never default to system disk.
DEFAULT_OUT = Path("/Volumes/MaksTiger/btc-ml/research/etll_tip/tick_pack_202606")
DEFAULT_REQUIRE_VOLUME = Path("/Volumes/MaksTiger")
DEFAULT_MIN_FREE_GB = 20.0
LOCAL_MANIFEST_COPY = (
    ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_june/tick_pack_manifest.json"
)
VISION_DAILY = (
    "https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/"
    "BTCUSDT-aggTrades-{date}.zip"
)


def _volume_free_bytes(path: Path) -> int:
    st = os.statvfs(path)
    return int(st.f_bavail * st.f_frsize)


def assert_volume_ready(
    *,
    require_volume: Path,
    out_dir: Path,
    min_free_gb: float,
) -> None:
    if not require_volume.exists():
        raise SystemExit(f"REQUIRED_VOLUME_NOT_MOUNTED: {require_volume}")
    try:
        out_resolved = out_dir.resolve()
    except FileNotFoundError:
        out_resolved = out_dir
    vol_resolved = require_volume.resolve()
    if not str(out_resolved).startswith(str(vol_resolved)):
        raise SystemExit(
            f"REFUSING_WRITE_OUTSIDE_VOLUME: out_dir={out_dir} must be under {require_volume}"
        )
    free = _volume_free_bytes(require_volume)
    need = int(min_free_gb * (1024**3))
    if free < need:
        raise SystemExit(
            f"INSUFFICIENT_FREE_SPACE: {require_volume} has {free / (1024**3):.1f} GiB free; "
            f"need >={min_free_gb} GiB"
        )
    print(
        f"volume_ok path={require_volume} free_gib={free / (1024**3):.1f} out_dir={out_dir}",
        flush=True,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_by_ranges(
    url: str,
    dest: Path,
    *,
    chunk_size: int = 16 * 1024,
    timeout_sec: int = 45,
    retries_per_chunk: int = 10,
    workers: int = 4,
) -> dict:
    """Download via small HTTP Range requests (optionally parallel).

    Some paths to data.binance.vision stall after ~16 KiB on a single GET
    (seen on CloudFront POP ARN53). Fixed-size Range chunks of <=16 KiB
    complete; parallel workers recover most of the lost throughput.
    Bench on this host: 1 worker ~20 KiB/s, 4 workers ~100 KiB/s;
    8+ workers often slower (edge contention).
    """
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    dest.parent.mkdir(parents=True, exist_ok=True)
    ua = {"User-Agent": "btc-ml-stp2-pilot/1.0"}
    head = urllib.request.Request(url, method="HEAD", headers=ua)
    with urllib.request.urlopen(head, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
    if total <= 0:
        raise RuntimeError(f"missing Content-Length for {url}")

    tmp = dest.with_suffix(dest.suffix + ".partial")
    # Contiguous prefix from a prior sequential run is reusable.
    resume_off = tmp.stat().st_size if tmp.exists() else 0
    if resume_off > total:
        tmp.unlink(missing_ok=True)
        resume_off = 0
    workers = max(1, int(workers))
    print(
        f"  range_download total={total} resume_off={resume_off} "
        f"chunk={chunk_size} workers={workers}",
        flush=True,
    )

    ranges: list[tuple[int, int]] = []
    off = resume_off
    while off < total:
        end = min(off + chunk_size - 1, total - 1)
        ranges.append((off, end))
        off = end + 1

    def _fetch_one(rng: tuple[int, int]) -> tuple[int, bytes]:
        start, end = rng
        want = end - start + 1
        last_exc: Exception | None = None
        for attempt in range(1, retries_per_chunk + 1):
            try:
                req = urllib.request.Request(
                    url,
                    headers={**ua, "Range": f"bytes={start}-{end}"},
                )
                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    data = resp.read()
                if len(data) != want:
                    raise RuntimeError(f"short range body got={len(data)} want={want}")
                return start, data
            except Exception as exc:
                last_exc = exc
                time.sleep(min(30, 2 * attempt))
        raise RuntimeError(f"range failed at {start}-{end}") from last_exc

    # Assemble in memory so parallel writes cannot leave holey on-disk partials.
    # Daily zips are tens of MiB — fine for this host.
    if tmp.exists() and resume_off == total:
        try:
            with zipfile.ZipFile(tmp) as zf:
                if zf.testzip() is not None:
                    raise RuntimeError("corrupt zip")
            tmp.replace(dest)
            return {
                "url": url,
                "path": str(dest),
                "bytes": dest.stat().st_size,
                "sha256": _sha256(dest),
                "cached": False,
                "method": f"http_range_16k_w{workers}_recovered",
            }
        except Exception:
            tmp.unlink(missing_ok=True)
            resume_off = 0
            ranges = []
            off = 0
            while off < total:
                end = min(off + chunk_size - 1, total - 1)
                ranges.append((off, end))
                off = end + 1

    buf = bytearray(total)
    if resume_off:
        prefix = tmp.read_bytes()
        if len(prefix) < resume_off:
            resume_off = len(prefix)
            ranges = [(s, e) for (s, e) in ranges if s >= resume_off]
        buf[0:resume_off] = prefix[:resume_off]

    done = resume_off
    lock = threading.Lock()
    t0 = time.perf_counter()

    def _store(start: int, data: bytes) -> None:
        nonlocal done
        with lock:
            buf[start : start + len(data)] = data
            done += len(data)
            if done == total or (done % (chunk_size * 64) == 0):
                dt = max(1e-6, time.perf_counter() - t0)
                rate = (done - resume_off) / dt / 1024.0
                print(
                    f"  range_progress {done}/{total} ~{rate:.1f} KiB/s",
                    flush=True,
                )

    if workers == 1:
        for rng in ranges:
            start, data = _fetch_one(rng)
            _store(start, data)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_fetch_one, rng) for rng in ranges]
            for fut in as_completed(futs):
                start, data = fut.result()
                _store(start, data)

    tmp.write_bytes(buf)
    if tmp.stat().st_size != total:
        raise RuntimeError(f"size mismatch got={tmp.stat().st_size} expected={total}")
    tmp.replace(dest)
    return {
        "url": url,
        "path": str(dest),
        "bytes": dest.stat().st_size,
        "sha256": _sha256(dest),
        "cached": False,
        "method": f"http_range_16k_w{workers}",
    }


def _download(
    url: str,
    dest: Path,
    *,
    retries: int = 2,
    timeout_sec: int = 60,
    prefer_range: bool = False,
    range_workers: int = 4,
) -> dict:
    import time

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return {
            "url": url,
            "path": str(dest),
            "bytes": dest.stat().st_size,
            "sha256": _sha256(dest),
            "cached": True,
        }
    if prefer_range:
        return _download_by_ranges(url, dest, workers=range_workers)

    last_exc: Exception | None = None
    tmp = dest.with_suffix(dest.suffix + ".partial")
    for attempt in range(1, retries + 1):
        try:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": "btc-ml-stp2-pilot/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                with tmp.open("wb") as out:
                    while True:
                        chunk = resp.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
            if not tmp.exists() or tmp.stat().st_size <= 0:
                raise RuntimeError("empty response body")
            tmp.replace(dest)
            return {
                "url": url,
                "path": str(dest),
                "bytes": dest.stat().st_size,
                "sha256": _sha256(dest),
                "cached": False,
                "http_status": getattr(resp, "status", None),
                "attempt": attempt,
                "method": "single_get",
            }
        except Exception as exc:
            last_exc = exc
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            if dest.exists() and dest.stat().st_size <= 0:
                dest.unlink(missing_ok=True)
            wait = min(30, 5 * attempt)
            print(
                f"  download attempt {attempt}/{retries} failed: {exc}; sleep {wait}s",
                flush=True,
            )
            time.sleep(wait)

    print("  falling back to 16KiB HTTP Range download", flush=True)
    try:
        return _download_by_ranges(url, dest, workers=range_workers)
    except Exception as range_exc:
        raise RuntimeError(
            f"download failed after {retries} attempts + range fallback: {url}"
        ) from (range_exc if last_exc is None else last_exc)


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
    parser.add_argument(
        "--skip-complete-days",
        action="store_true",
        help="Skip YYYY-MM-DD if 24 hour parquet partitions already exist under out-dir",
    )
    parser.add_argument(
        "--continue-on-download-error",
        action="store_true",
        help="Log failed days and continue instead of aborting the whole run",
    )
    parser.add_argument(
        "--prefer-range",
        action="store_true",
        help="Download via 16KiB HTTP Range chunks (workaround for Vision body stalls)",
    )
    parser.add_argument(
        "--range-workers",
        type=int,
        default=4,
        help="Parallel Range workers when using --prefer-range (4 ~best on ARN53 path)",
    )
    parser.add_argument(
        "--require-volume",
        type=Path,
        default=DEFAULT_REQUIRE_VOLUME,
        help="Refuse to write unless out-dir is under this mounted volume",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=DEFAULT_MIN_FREE_GB,
        help="Minimum free space on require-volume before download",
    )
    parser.add_argument(
        "--allow-local",
        action="store_true",
        help="Disable volume guard (dangerous on low-disk hosts)",
    )
    args = parser.parse_args()

    if not args.allow_local:
        assert_volume_ready(
            require_volume=args.require_volume,
            out_dir=args.out_dir,
            min_free_gb=float(args.min_free_gb),
        )

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
        day_part = agg_root / f"date={day}"
        if args.skip_complete_days and day_part.exists():
            hours = list(day_part.glob("hour=*"))
            # Incomplete calendar edge days may have <24; still skip if any hours present
            # and caller is mid-resume. Prefer full 24 for interior days.
            n_hours = len(hours)
            if n_hours >= 24 or (
                n_hours > 0 and day == start_ts.strftime("%Y-%m-%d")
            ) or (
                n_hours > 0 and day == (end_ts - pd.Timedelta(microseconds=1)).strftime("%Y-%m-%d")
            ):
                print(f"SKIP {day} existing_hours={n_hours}", flush=True)
                # Count existing hours into coverage without re-download.
                for h in hours:
                    stats.setdefault("hour_keys", set()).add(f"{day}T{h.name.replace('hour=', '')}")
                downloads.append({"day": day, "skipped_complete": True, "hours": n_hours})
                continue
        url = VISION_DAILY.format(date=day)
        dest = zip_dir / f"BTCUSDT-aggTrades-{day}.zip"
        print(f"DOWNLOAD {day}", flush=True)
        try:
            meta = _download(
                url,
                dest,
                prefer_range=bool(args.prefer_range),
                range_workers=int(args.range_workers),
            )
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
        except Exception as exc:
            print(f"  FAILED {day}: {exc}", flush=True)
            downloads.append({"day": day, "failed": True, "error": str(exc)})
            stats.setdefault("failed_days", []).append(day)
            if not args.continue_on_download_error:
                raise
            continue

    hour_keys = stats.pop("hour_keys")
    present_hours = len(hour_keys)
    expected_hours = int((end_ts - start_ts).total_seconds() // 3600)
    dates = sorted({p.name for p in agg_root.glob("date=*")})

    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from btc_ml.trading.shadow_structural_protection.trades import load_agg_trades

    # Only sample a short window — full-span load can OOM after multi-GB ingest.
    sample_end = min(end, start + timedelta(hours=2))
    sample = load_agg_trades(
        repo=repo_root, start=start, end=sample_end - timedelta(microseconds=1)
    )
    ready = present_hours >= expected_hours and len(sample) > 0
    manifest = {
        "generated_at": ingested_at,
        "stage": "STP2_PILOT_P1_TICK_PACK",
        "status": "TICK_PACK_READY" if ready else "TICK_PACK_PARTIAL",
        "symbol": "BTCUSDT",
        "market": "binance_um_futures",
        "source": "data.binance.vision",
        "mode": "daily_streaming",
        "window": {"from": args.from_ts, "to": args.to_ts},
        "downloads": downloads,
        "rows_clipped_total": stats["rows_clipped_total"],
        "rows_loader_sample": int(len(sample)),
        "loader_sample_window": {
            "from": start.isoformat().replace("+00:00", "Z"),
            "to": sample_end.isoformat().replace("+00:00", "Z"),
        },
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
        "storage_root": str(out_dir),
        "next_step": "P2_FILTER_RUNNER",
        "next_step_ru": "Написать research runner STP2 filter overlay на pilot universe.",
    }
    manifest_paths = [
        out_dir / "tick_pack_manifest.json",
        Path("/Volumes/MaksTiger/btc-ml/manifests") / f"{out_dir.name}_manifest.json",
        ROOT
        / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_full"
        / "tick_pack_manifest.json",
    ]
    # Keep June/stp2 copies only when writing the June pilot pack.
    if out_dir.name == "tick_pack_202606":
        manifest_paths.extend(
            [
                Path("/Volumes/MaksTiger/btc-ml/manifests/tick_pack_202606_manifest.json"),
                LOCAL_MANIFEST_COPY,
                ROOT / "output/audits/etll_lived_replay_20260825/stp2_pilot/tick_pack_manifest.json",
            ]
        )
    for path in manifest_paths:
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
