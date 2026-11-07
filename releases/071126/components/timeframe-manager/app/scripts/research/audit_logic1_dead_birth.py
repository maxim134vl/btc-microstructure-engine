#!/usr/bin/env python3
"""Step 4: dead-at-birth audit on train NO_CHASE losers. Not a trainer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from btc_ml.research.logic1_dead_birth import attach_birth_bar, summarize_dead_birth  # noqa: E402
from btc_ml.research.logic1_loser_origin import attach_origin_audit, load_m15_bars  # noqa: E402
from btc_ml.research.logic1_open_gate import DEFAULT_ARCHIVE, build_open_events, resolve_pack_root  # noqa: E402
from calibration_split import assign_segment, load_split  # noqa: E402

OUT = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/logic1/dead_birth_audit_train.json"


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
    labeled = attach_origin_audit(train, load_m15_bars(pack))
    birth = attach_birth_bar(labeled, pack)
    report = summarize_dead_birth(birth)
    report["birth_bar_exact_frac"] = round(float(birth["birth_bar_exact"].mean()), 4)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"\nwritten: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
