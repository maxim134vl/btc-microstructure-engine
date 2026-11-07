#!/usr/bin/env python3
"""Read-only production WAL tail benchmark using an isolated temporary copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.trading.intrabar_paper.execution_market_wal_archive import SegmentedWalStorage


def canonical(row: dict) -> bytes:
    return json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wal", type=Path)
    parser.add_argument("--events", type=int, default=250_000)
    args = parser.parse_args()
    tail: deque[bytes] = deque(maxlen=args.events)
    with args.wal.open("rb") as handle:
        for line in handle:
            tail.append(line)
    rows, invalid = [], 0
    for raw in tail:
        try:
            rows.append(json.loads(raw))
        except (json.JSONDecodeError, UnicodeDecodeError):
            invalid += 1
    by_type, bytes_by_type = Counter(), defaultdict(int)
    digest = hashlib.sha256()
    for row in rows:
        kind = str(row.get("event_type"))
        by_type[kind] += 1
        bytes_by_type[kind] += len(canonical(row))
        digest.update(canonical(row))
    stamps = [datetime.fromisoformat(str(r["durable_append_timestamp"]).replace("Z", "+00:00")) for r in rows if r.get("durable_append_timestamp")]
    seconds = max(0.001, (max(stamps) - min(stamps)).total_seconds())
    with tempfile.TemporaryDirectory(prefix="execution-wal-p1-") as name:
        root = Path(name)
        source = root / f"closed-{int(rows[0]['wal_offset']):020d}-{int(rows[-1]['wal_offset']):020d}.jsonl"
        with source.open("wb") as handle:
            for row in rows:
                handle.write(json.dumps(row).encode() + b"\n")
        raw_size = source.stat().st_size
        storage = SegmentedWalStorage(root, delete_verified_plaintext=False)
        archive = storage.compact_pending()[0]
        replay = list(
            storage.iter_from_offset(
                int(rows[-101]["wal_offset"]),
                active_start_offset=int(rows[-1]["wal_offset"]) + 1,
                active_last_offset=int(rows[-1]["wal_offset"]),
            )
        )
        after = hashlib.sha256()
        for row in storage.iter_archive(archive, 0):
            after.update(canonical(row))
        result = {
            "sample_events": len(rows), "invalid_tail_lines": invalid,
            "offset_range": [rows[0]["wal_offset"], rows[-1]["wal_offset"]],
            "sample_seconds": seconds, "events_by_type": dict(by_type),
            "bytes_by_type": dict(bytes_by_type),
            "bytes_per_event": {k: round(bytes_by_type[k] / by_type[k], 2) for k in by_type},
            "projected_gb_day_by_type": {k: round(bytes_by_type[k] / seconds * 86400 / 1e9, 4) for k in by_type},
            "raw_copy_bytes": raw_size, "archive_bytes": archive.stat().st_size,
            "compression_ratio": round(archive.stat().st_size / raw_size, 5),
            "projected_archive_gb_day": round(archive.stat().st_size / raw_size * sum(bytes_by_type.values()) / seconds * 86400 / 1e9, 4),
            "logical_hash_equal": digest.hexdigest() == after.hexdigest(),
            "archive_row_count": sum(group.num_rows for group in __import__("pyarrow.parquet", fromlist=["ParquetFile"]).ParquetFile(archive).iter_batches()),
            "near_tail_replay_count": len(replay),
            "near_tail_offsets": [replay[0]["wal_offset"], replay[-1]["wal_offset"]],
        }
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
