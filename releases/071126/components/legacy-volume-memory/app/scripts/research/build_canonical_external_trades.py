#!/usr/bin/env python3
"""Build canonical external trader fills/positions from Downloads CSVs (PDF skipped)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.build import build_canonical_external_trades  # noqa: E402

DEFAULT_BYBIT = Path("/Users/fontecrypto/Downloads/positions_bybit_2026-07-26_17-19-41.csv")
DEFAULT_FILTERED = Path("/Users/fontecrypto/Downloads/filtered_rounded_trades.csv")
DEFAULT_OKX_DIR = Path(
    "/Users/fontecrypto/Downloads/"
    "NDQxMDM2NzU=~2023-03-14~2026-03-14~UTC0~309e788d39ad52b4d43dd4001adecaad_Swap_BillHistory/"
    "479784980202055069"
)
DEFAULT_OUT = ROOT / "data" / "research" / "external_traders"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bybit", type=Path, default=DEFAULT_BYBIT)
    parser.add_argument("--filtered", type=Path, default=DEFAULT_FILTERED)
    parser.add_argument("--okx-dir", type=Path, default=DEFAULT_OKX_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--batch-id", type=str, default=None)
    args = parser.parse_args()

    okx_paths = sorted(args.okx_dir.glob("OKX Trading History_*.csv")) if args.okx_dir.exists() else []
    report = build_canonical_external_trades(
        bybit_path=args.bybit if args.bybit.exists() else None,
        filtered_path=args.filtered if args.filtered.exists() else None,
        okx_paths=okx_paths,
        output_dir=args.output_dir,
        import_batch_id=args.batch_id,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
