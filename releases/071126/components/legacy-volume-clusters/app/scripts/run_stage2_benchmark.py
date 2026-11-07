#!/usr/bin/env python3
"""Run Stage 2 reasoning validation benchmark."""

from __future__ import annotations

import argparse
import json
import sys

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, ROOT)

from benchmark.stage2.runner import run_stage2_benchmark, should_auto_run_stage2


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 2 reasoning validation benchmark")
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--forward-horizon", type=int, default=None)
    parser.add_argument("--no-visuals", action="store_true")
    parser.add_argument("--auto-check", action="store_true", help="Run only if auto interval elapsed")
    args = parser.parse_args()

    if args.auto_check and not should_auto_run_stage2():
        print(json.dumps({"status": "SKIPPED", "reason": "auto interval not elapsed"}, indent=2))
        return 0

    result = run_stage2_benchmark(
        lookback_days=args.lookback_days,
        forward_horizon=args.forward_horizon,
        generate_visuals=not args.no_visuals,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") in ("OK", "SKIPPED") else 1


if __name__ == "__main__":
    sys.exit(main())
