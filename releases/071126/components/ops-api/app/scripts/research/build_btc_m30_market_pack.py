#!/usr/bin/env python3
"""Build BTC M30 ETLL market pack from the M15 pack (same external window)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.tf_market_pack import build_btc_tf_market_pack_from_m15  # noqa: E402

DEFAULT_M15 = ROOT / "data/research/external_traders/market_pack_btc_m15"
DEFAULT_OUT = ROOT / "data/research/external_traders/market_pack_btc_m30"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-m15-pack", type=Path, default=DEFAULT_M15)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    report = build_btc_tf_market_pack_from_m15(
        source_m15_pack=args.source_m15_pack,
        output_dir=args.output_dir,
        timeframe="M30",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
