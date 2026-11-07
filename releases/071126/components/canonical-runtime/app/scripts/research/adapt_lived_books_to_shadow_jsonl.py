#!/usr/bin/env python3
"""Adapt lived M15 parquet books → synthetic paper JSONL for Shadow lab."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.shadow_lab import adapt_lived_books_to_jsonl  # noqa: E402

DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--limit-trades", type=int, default=None)
    args = parser.parse_args()
    summary = adapt_lived_books_to_jsonl(pack_dir=args.pack_dir, limit_trades=args.limit_trades)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
