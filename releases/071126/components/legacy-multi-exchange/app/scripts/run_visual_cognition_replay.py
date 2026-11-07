#!/usr/bin/env python3
"""CLI — build visual cognition replay snapshot."""

from __future__ import annotations

import argparse
import json
import sys

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, ROOT)

from visual_cognition.replay_controller import build_replay_snapshot, list_replay_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Visual cognition replay")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--max-bars", type=int, default=60)
    parser.add_argument("--timestamp")
    parser.add_argument("--event-index", type=int)
    parser.add_argument("--list-events", action="store_true")
    args = parser.parse_args()

    if args.list_events:
        result = list_replay_events(lookback_days=args.lookback_days)
    else:
        result = build_replay_snapshot(
            lookback_days=args.lookback_days,
            max_bars=args.max_bars,
            timestamp=args.timestamp,
            event_index=args.event_index,
        )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") in ("OK", "NO_EVENTS") else 1


if __name__ == "__main__":
    sys.exit(main())
