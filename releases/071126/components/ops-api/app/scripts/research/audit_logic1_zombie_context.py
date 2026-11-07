#!/usr/bin/env python3
"""Step 6: zombie-context autopsy on train directional episodes. Not a trainer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from btc_ml.research.logic1_open_gate import resolve_pack_root  # noqa: E402
from btc_ml.research.logic1_zombie_context import (  # noqa: E402
    BUILDER_VERSION,
    DEFAULT_LIFECYCLE,
    attach_stop_volume,
    episode_table,
    load_tf_ohlc,
    replay_v3,
    summarize_train,
)
from calibration_split import load_split  # noqa: E402

OUT = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/logic1/zombie_context_audit_train.json"
REPLAY_CACHE = OUT.parent / "zombie_v3_replay.parquet"


def _train_mask(start: pd.Series, end: pd.Series, split: dict) -> pd.Series:
    seg = split["segments"]["train"]
    lo = pd.Timestamp(seg["from"])
    hi = pd.Timestamp(seg["to"])
    if lo.tzinfo is None:
        lo = lo.tz_localize("UTC")
    if hi.tzinfo is None:
        hi = hi.tz_localize("UTC")
    start = pd.to_datetime(start, utc=True)
    end = pd.to_datetime(end, utc=True)
    return (start >= lo) & (start < hi) & (end < hi)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifecycle", type=Path, default=DEFAULT_LIFECYCLE)
    parser.add_argument("--pack-root", type=Path, default=None)
    args = parser.parse_args()
    pack = resolve_pack_root(args.pack_root, ROOT)
    if pack is None:
        raise SystemExit("market packs not found")
    if not args.lifecycle.is_file():
        raise SystemExit(f"lifecycle missing: {args.lifecycle}")

    replayed = None
    if REPLAY_CACHE.is_file():
        cached = pd.read_parquet(REPLAY_CACHE)
        if str(cached.get("builder_version_replay", pd.Series(dtype=object)).iloc[0] if len(cached) else "") == BUILDER_VERSION:
            replayed = cached
            print(f"loaded replay cache: {REPLAY_CACHE} n={len(replayed)}", flush=True)
    if replayed is None:
        raw = pd.read_parquet(args.lifecycle)
        replayed = replay_v3(raw)
        REPLAY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        replayed.to_parquet(REPLAY_CACHE, index=False)
        print(f"wrote replay cache: {REPLAY_CACHE} n={len(replayed)}", flush=True)
    ohlc = {tf: load_tf_ohlc(pack, tf) for tf in ("M15", "M30", "H1", "H4")}
    episodes = episode_table(replayed, ohlc)
    episodes = attach_stop_volume(episodes, pack)
    split = load_split()
    train = episodes.loc[_train_mask(episodes["start_time"], episodes["end_time"], split)].copy()
    report = summarize_train(train)
    report["lifecycle_path"] = str(args.lifecycle)
    report["n_replayed_bars"] = int(len(replayed))
    report["n_episodes_all_segments"] = int(len(episodes))
    report["holdout"] = "SEALED"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    train.to_parquet(OUT.with_suffix(".parquet"), index=False)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"\nwritten: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
