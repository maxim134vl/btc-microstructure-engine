#!/usr/bin/env python3
"""Isolated shadow launcher for raw market event journal (TRD1A/TRD1B).

Does NOT touch live_binance_feed_v2, cognition, manager, or traders.
Writes only to the provided --journal-root.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.feeds.raw_event_journal.collector import CollectorConfig, RawMarketEventCollector
from btc_ml.feeds.raw_event_journal.disk import check_disk
from btc_ml.feeds.raw_event_journal.archival_writer import ChunkPolicy
from btc_ml.feeds.raw_event_journal.writer import BatchPolicy


def _write_pid(path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Shadow raw event journal collector (aggTrade + bookTicker)"
    )
    parser.add_argument("--journal-root", type=Path, required=True)
    parser.add_argument("--health-path", type=Path, required=True)
    parser.add_argument("--metrics-out", type=Path, default=None)
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Optional run limit. Omit for continuous shadow operation.",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=5.0,
        help="Working stop threshold (GiB). Default 5.0.",
    )
    parser.add_argument(
        "--emergency-min-free-gb",
        type=float,
        default=2.0,
        help="Emergency floor (GiB). Working threshold stops first.",
    )
    parser.add_argument("--max-events-per-batch", type=int, default=500)
    parser.add_argument("--max-seconds-per-batch", type=float, default=2.0)
    parser.add_argument("--max-buffered-bytes", type=int, default=512_000)
    parser.add_argument("--storage-format", choices=["parquet", "jsonl"], default="parquet")
    parser.add_argument("--writer-mode", choices=["thread", "process"], default="thread")
    parser.add_argument("--chunk-max-events", type=int, default=25000)
    parser.add_argument("--chunk-max-seconds", type=float, default=60.0)
    parser.add_argument("--chunk-max-bytes", type=int, default=33_554_432)
    parser.add_argument("--chunk-zstd-level", type=int, default=6)
    parser.add_argument("--queue-capacity-events", type=int, default=50_000)
    parser.add_argument("--queue-capacity-bytes", type=int, default=67_108_864)
    parser.add_argument("--retain-raw-payload", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--pid-file", type=Path, default=None)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--stale-agg-seconds", type=float, default=60.0)
    parser.add_argument("--stale-book-seconds", type=float, default=15.0)
    parser.add_argument("--no-auto-reconnect", action="store_true")
    args = parser.parse_args()

    if args.log_file is not None:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(args.log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_fh  # type: ignore[assignment]
        sys.stderr = log_fh  # type: ignore[assignment]

    min_free = int(args.min_free_gb * 1024**3)
    emergency = int(args.emergency_min_free_gb * 1024**3)
    disk = check_disk(args.journal_root, min_free_bytes=min_free)
    print(json.dumps({"disk_preflight": disk.__dict__}, indent=2), flush=True)
    if disk.is_low:
        print("DISK_LOW: refusing to start collector", file=sys.stderr, flush=True)
        return 2

    _write_pid(args.pid_file)
    atexit.register(_remove_pid, args.pid_file)

    config = CollectorConfig(
        journal_root=args.journal_root,
        health_path=args.health_path,
        symbol=args.symbol,
        duration_seconds=args.duration_seconds,
        min_free_bytes=min_free,
        emergency_min_free_bytes=emergency,
        retain_raw_payload=args.retain_raw_payload,
        stale_agg_after_seconds=args.stale_agg_seconds,
        stale_book_after_seconds=args.stale_book_seconds,
        auto_reconnect=not args.no_auto_reconnect,
        storage_format=args.storage_format,
        writer_mode=args.writer_mode,
        queue_capacity_events=args.queue_capacity_events,
        queue_capacity_bytes=args.queue_capacity_bytes,
        chunk_policy=ChunkPolicy(
            max_events_per_chunk=args.chunk_max_events,
            max_seconds_per_chunk=args.chunk_max_seconds,
            max_bytes_per_chunk=args.chunk_max_bytes,
            compression_level=args.chunk_zstd_level,
        ),
        batch_policy=BatchPolicy(
            max_events_per_batch=args.max_events_per_batch,
            max_seconds_per_batch=args.max_seconds_per_batch,
            max_buffered_bytes=args.max_buffered_bytes,
        ),
    )
    collector = RawMarketEventCollector(config)
    metrics = collector.run()
    print(json.dumps({"metrics": metrics}, indent=2), flush=True)
    if args.metrics_out:
        args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    _remove_pid(args.pid_file)

    if metrics.get("fault_stop"):
        return 1
    if metrics.get("stop_reason") == "disk_low":
        return 2
    # Continuous mode stopped gracefully, or duration elapsed with events.
    if args.duration_seconds is not None:
        ok = metrics.get("aggtrade_event_count", 0) > 0 and metrics.get("bookticker_event_count", 0) > 0
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
