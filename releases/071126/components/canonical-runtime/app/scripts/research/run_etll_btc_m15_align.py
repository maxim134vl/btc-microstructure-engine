#!/usr/bin/env python3
"""ETLL Align: lived M15 trades vs external BTC OK positions.

Writes under pack/align/. Does not touch live or Toxic Box.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.align import AlignConfig, align_positions  # noqa: E402

DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--match-bars", type=int, default=4, help="±N M15 bars around external entry")
    parser.add_argument(
        "--require-interval-overlap",
        action="store_true",
        help="Require open-interval overlap in addition to entry proximity",
    )
    args = parser.parse_args()

    pack = args.pack_dir
    lived_path = pack / "lived_replay" / "lived_trades.parquet"
    external_path = pack / "external_positions_btcusdt_ok.parquet"
    if not lived_path.exists():
        raise FileNotFoundError(lived_path)
    if not external_path.exists():
        raise FileNotFoundError(external_path)

    result = align_positions(
        lived=pd.read_parquet(lived_path),
        external=pd.read_parquet(external_path),
        config=AlignConfig(
            match_bars=args.match_bars,
            require_interval_overlap=bool(args.require_interval_overlap),
        ),
    )

    out_dir = pack / "align"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = result["summary"]
    summary["artifacts"] = {
        "summary": str(out_dir / "align_summary.json"),
        "pairs": str(out_dir / "align_pairs.parquet"),
        "they_took_we_skipped": str(out_dir / "they_took_we_skipped.parquet"),
        "we_took_they_skipped": str(out_dir / "we_took_they_skipped.parquet"),
    }
    summary["inputs"] = {
        "lived_trades": str(lived_path),
        "external_positions": str(external_path),
    }

    (out_dir / "align_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result["pairs"].to_parquet(out_dir / "align_pairs.parquet", index=False)
    result["they_took_we_skipped"].to_parquet(out_dir / "they_took_we_skipped.parquet", index=False)
    result["we_took_they_skipped"].to_parquet(out_dir / "we_took_they_skipped.parquet", index=False)

    manifest_path = pack / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        manifest["status"] = "ALIGN_DONE"
        manifest["align"] = {
            "dir": str(out_dir),
            "WE_AGREED": summary["counts"]["WE_AGREED"],
            "OPPOSITE": summary["counts"]["OPPOSITE"],
            "THEY_TOOK_WE_SKIPPED": summary["counts"]["THEY_TOOK_WE_SKIPPED"],
            "WE_TOOK_THEY_SKIPPED": summary["counts"]["WE_TOOK_THEY_SKIPPED"],
            "external_match_rate": summary["coverage"]["external_match_rate"],
            "generated_at": summary["generated_at"],
        }
        manifest["next_step_ru"] = (
            "Align готов. Дальше — Distill: good → learning_candidates, bad → Toxic Box "
            "(по вашим правилам)."
        )
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
