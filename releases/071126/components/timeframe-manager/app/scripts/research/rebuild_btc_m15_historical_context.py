#!/usr/bin/env python3
"""Rebuild BTC M15 historical context into ETLL market pack (does not touch live cognition)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.rebuild_context import rebuild_btc_m15_historical_context  # noqa: E402

DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument(
        "--limit-bars",
        type=int,
        default=None,
        help="Optional smoke limit (first N bars). Full rebuild: omit.",
    )
    args = parser.parse_args()
    report = rebuild_btc_m15_historical_context(
        pack_dir=args.pack_dir,
        limit_bars=args.limit_bars,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
