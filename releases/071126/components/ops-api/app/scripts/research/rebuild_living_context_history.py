#!/usr/bin/env python3
"""Rebuild living-process context on ETLL packs (2023–2026). Does not touch live cognition.

  python3 scripts/research/rebuild_living_context_history.py
  python3 scripts/research/rebuild_living_context_history.py --timeframes M15
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.rebuild_context import (  # noqa: E402
    rebuild_btc_m15_historical_context,
    rebuild_btc_tf_historical_context,
)

PACK_ROOTS = (
    ROOT / "data/research/external_traders",
    Path("/Volumes/MaksTiger/btc-ml/from-mac-20260907/btc-ml-cold/research/external_traders"),
)


def resolve_pack_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    for root in PACK_ROOTS:
        if (root / "market_pack_btc_m15" / "feed_m15.parquet").exists():
            return root
    return PACK_ROOTS[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-root", type=Path, default=None)
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=["M15", "M30", "H1", "H4"],
    )
    parser.add_argument("--limit-bars", type=int, default=None)
    args = parser.parse_args()
    pack_root = resolve_pack_root(args.pack_root)

    reports = []
    for tf in args.timeframes:
        tf_u = str(tf).upper()
        pack = pack_root / f"market_pack_btc_{tf_u.lower()}"
        feed = pack / f"feed_{tf_u.lower()}.parquet"
        if not feed.exists():
            reports.append({"timeframe": tf_u, "status": "SKIPPED_NO_FEED", "pack_dir": str(pack)})
            continue
        if tf_u == "M15":
            report = rebuild_btc_m15_historical_context(pack_dir=pack, limit_bars=args.limit_bars)
        else:
            report = rebuild_btc_tf_historical_context(
                pack_dir=pack, timeframe=tf_u, limit_bars=args.limit_bars
            )
        reports.append(report)
        print(json.dumps({"timeframe": tf_u, "status": report.get("status"), "spans": report.get("spans")}, ensure_ascii=False))

    summary = {
        "live_cognition_touched": False,
        "reports": [
            {
                "timeframe": r.get("timeframe") or "M15",
                "status": r.get("status"),
                "context_version": r.get("context_version"),
                "spans": r.get("spans"),
                "lifecycle_active_market_context_counts": r.get("lifecycle_active_market_context_counts"),
            }
            for r in reports
        ],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
