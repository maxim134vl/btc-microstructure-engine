#!/usr/bin/env python3
"""One-shot / bounded research runner for volume localization shadow producer.

Does not register in pipeline.
Does not start a persistent daemon.
Does not write live cognition / trading artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))

from volume_localization_shadow.producer import (  # noqa: E402
    DEFAULT_OUT_DIR,
    DEFAULT_SOURCE,
    run_shadow_once,
    watch_natural_bars,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Volume localization shadow (research-only)")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=256, help="Latest completed rows")
    parser.add_argument(
        "--watch-natural-bars",
        type=int,
        default=0,
        help="If >0, bounded watch for N natural completed bars then exit",
    )
    parser.add_argument("--timeout-s", type=float, default=1200.0)
    parser.add_argument("--poll-s", type=float, default=15.0)
    parser.add_argument("--skip-full-parity", action="store_true")
    args = parser.parse_args()

    status = run_shadow_once(
        out_dir=args.out_dir,
        source=args.source,
        limit=args.limit,
        include_full_parity=not args.skip_full_parity,
    )
    print(json.dumps({"oneshot": status}, indent=2, default=str))

    if status.get("historical_parity", {}).get("parity_ok") is False:
        print("STOP — VOLUME_LOCALIZATION_PARITY_REGRESSION", file=sys.stderr)
        return 2

    if args.watch_natural_bars > 0:
        natural = watch_natural_bars(
            out_dir=args.out_dir,
            source=args.source,
            target_bars=args.watch_natural_bars,
            timeout_s=args.timeout_s,
            poll_s=args.poll_s,
            limit=args.limit,
        )
        print(json.dumps({"natural": natural}, indent=2, default=str))
        if natural["status"] == "VOLUME_LOCALIZATION_SHADOW_READY_PENDING_MORE_NATURAL_BARS":
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
