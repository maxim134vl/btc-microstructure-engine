#!/usr/bin/env python3
"""Build BTC-only M15 market pack aligned to external trader OK positions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.market_pack import build_btc_m15_market_pack  # noqa: E402

DEFAULT_BARS = ROOT / "btc_15m.parquet"
DEFAULT_POSITIONS = ROOT / "data/research/external_traders/canonical_external_positions.parquet"
DEFAULT_OUT = ROOT / "data/research/external_traders/market_pack_btc_m15"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=Path, default=DEFAULT_BARS)
    parser.add_argument("--positions", type=Path, default=DEFAULT_POSITIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if not args.bars.exists():
        raise SystemExit(f"bars missing: {args.bars}")
    if not args.positions.exists():
        raise SystemExit(f"positions missing: {args.positions}")
    report = build_btc_m15_market_pack(
        bars_path=args.bars,
        positions_path=args.positions,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
