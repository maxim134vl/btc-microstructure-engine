#!/usr/bin/env python3
"""Run integrated cognition validation benchmark."""

from __future__ import annotations

import argparse
import json
import sys

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, ROOT)

from benchmark.integrated.runner import run_integrated_benchmark, should_auto_run_integrated


def main() -> int:
    parser = argparse.ArgumentParser(description="Integrated cognition validation benchmark")
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--forward-horizon", type=int, default=None)
    parser.add_argument("--no-visuals", action="store_true")
    parser.add_argument("--auto-check", action="store_true")
    args = parser.parse_args()

    if args.auto_check and not should_auto_run_integrated():
        print(json.dumps({"status": "SKIPPED", "reason": "auto interval not elapsed"}, indent=2))
        return 0

    result = run_integrated_benchmark(
        lookback_days=args.lookback_days,
        forward_horizon=args.forward_horizon,
        generate_visuals=not args.no_visuals,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") in ("OK", "SKIPPED") else 1


if __name__ == "__main__":
    sys.exit(main())
