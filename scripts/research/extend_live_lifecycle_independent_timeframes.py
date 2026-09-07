#!/usr/bin/env python3
"""Tag live M15 lifecycle and append independent M30/H1/H4 closed-bar rows.

Does not copy M15 direction onto higher timeframes. Does not touch LIVE1A journal.
M15 rows stay the live shadow-chain series (plus timeframe=M15).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.rebuild_context import (  # noqa: E402
    extend_m15_lifecycle_with_independent_higher_timeframes,
    load_m15_closed_bars_for_resample,
)

MEMORY_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
EPISODES_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"


def _write_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)


def main() -> int:
    if not MEMORY_PATH.exists() or not EPISODES_PATH.exists():
        print("ERROR: M15 lifecycle memory/episodes missing; run lifecycle builder first.", file=sys.stderr)
        return 1
    memory = pd.read_parquet(MEMORY_PATH)
    episodes = pd.read_parquet(EPISODES_PATH)
    try:
        feed = load_m15_closed_bars_for_resample(ROOT)
    except FileNotFoundError as exc:
        print(f"WARN skip higher TFs; tagging M15 only: {exc}", file=sys.stderr)
        feed = None
    if "timeframe" not in memory.columns:
        m15_before = len(memory)
    else:
        m15_before = int((memory["timeframe"].astype(str).str.upper() == "M15").sum())
    extended, extended_ep = extend_m15_lifecycle_with_independent_higher_timeframes(
        m15_lifecycle=memory,
        m15_episodes=episodes,
        feed_m15=feed,
    )
    m15_after = int((extended["timeframe"].astype(str).str.upper() == "M15").sum())
    if m15_after != m15_before:
        print(
            f"ERROR: M15 row count changed {m15_before} -> {m15_after}",
            file=sys.stderr,
        )
        return 1
    _write_atomic(extended, MEMORY_PATH)
    _write_atomic(extended_ep, EPISODES_PATH)
    counts = extended["timeframe"].astype(str).str.upper().value_counts().to_dict()
    print(f"rows written memory: {len(extended)} by_tf={counts}")
    print(f"rows written episodes: {len(extended_ep)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
