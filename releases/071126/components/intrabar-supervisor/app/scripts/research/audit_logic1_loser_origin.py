#!/usr/bin/env python3
"""Step 1: label train losers as book-lag chase vs dead/fading thesis.

This is an autopsy, not a trainer. It does not fit a policy, does not
score allow/block on total R, does not train CatBoost, and does not
open the holdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from btc_ml.research.logic1_loser_origin import (  # noqa: E402
    attach_origin_audit,
    load_m15_bars,
    summarize_train,
)
from btc_ml.research.logic1_open_gate import (  # noqa: E402
    DEFAULT_ARCHIVE,
    build_open_events,
    resolve_pack_root,
)
from calibration_split import assign_segment, load_split  # noqa: E402

OUT_DIR = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/logic1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--pack-root", type=Path, default=None)
    args = parser.parse_args()
    pack = resolve_pack_root(args.pack_root, ROOT)
    if pack is None:
        raise SystemExit("market packs not found")

    events = build_open_events(args.archive, pack_root=pack)
    events["segment"] = assign_segment(events, load_split())
    train = events.loc[events["segment"] == "train"].copy()
    if train.empty:
        raise SystemExit("train segment is empty")

    labeled = attach_origin_audit(train, load_m15_bars(pack))
    report = summarize_train(labeled)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "loser_origin_audit_train.json"
    parquet_path = OUT_DIR / "loser_origin_audit_train.parquet"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    keep = [
        "trade_id",
        "position_id",
        "timeframe",
        "side",
        "R",
        "exit_reason",
        "entry_price",
        "context_origin_price",
        "context_started_at",
        "source_bar_close",
        "age_bars",
        "lag_minutes",
        "signed_fill_origin_bps",
        "signed_event_origin_bps",
        "chase_axis",
        "path_axis",
        "entry_kind",
        "primary_loser_bucket",
        "mfe_from_fill_bps",
        "mae_from_fill_bps",
        "mfe_from_origin_bps",
        "mae_from_origin_bps",
        "first_m15_from_fill_bps",
        "first_m15_from_origin_bps",
        "episode_open_index",
        "loser",
    ]
    labeled[[c for c in keep if c in labeled.columns]].to_parquet(parquet_path, index=False)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"\nwritten: {json_path}")
    print(f"written: {parquet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
