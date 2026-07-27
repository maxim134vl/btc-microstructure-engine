#!/usr/bin/env python3
"""Isolated shadow launcher for TRD1A raw market event journal.

Does NOT touch live_binance_feed_v2, cognition, manager, or traders.
Writes only to the provided --journal-root (candidate path for smoke).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.feeds.raw_event_journal.collector import CollectorConfig, RawMarketEventCollector
from btc_ml.feeds.raw_event_journal.disk import check_disk
from btc_ml.feeds.raw_event_journal.writer import BatchPolicy


def main() -> int:
    parser = argparse.ArgumentParser(description="TRD1A shadow raw event journal collector")
    parser.add_argument("--journal-root", type=Path, required=True)
    parser.add_argument("--health-path", type=Path, required=True)
    parser.add_argument("--metrics-out", type=Path, default=None)
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument("--max-events-per-batch", type=int, default=500)
    parser.add_argument("--max-seconds-per-batch", type=float, default=2.0)
    parser.add_argument("--max-buffered-bytes", type=int, default=512_000)
    parser.add_argument("--retain-raw-payload", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args()

    min_free = int(args.min_free_gb * 1024**3)
    disk = check_disk(args.journal_root, min_free_bytes=min_free)
    print(json.dumps({"disk_preflight": disk.__dict__}, indent=2))
    if disk.is_low:
        print("DISK_LOW: refusing to start collector", file=sys.stderr)
        return 2

    config = CollectorConfig(
        journal_root=args.journal_root,
        health_path=args.health_path,
        symbol=args.symbol,
        duration_seconds=args.duration_seconds,
        min_free_bytes=min_free,
        retain_raw_payload=args.retain_raw_payload,
        batch_policy=BatchPolicy(
            max_events_per_batch=args.max_events_per_batch,
            max_seconds_per_batch=args.max_seconds_per_batch,
            max_buffered_bytes=args.max_buffered_bytes,
        ),
    )
    collector = RawMarketEventCollector(config)
    metrics = collector.run()
    print(json.dumps({"metrics": metrics}, indent=2))
    if args.metrics_out:
        args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    ok = metrics.get("aggtrade_event_count", 0) > 0 and metrics.get("bookticker_event_count", 0) > 0
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
