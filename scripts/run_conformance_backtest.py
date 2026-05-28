#!/usr/bin/env python3
"""Run cognition architecture conformance backtest."""

from __future__ import annotations

import argparse
import json
import sys

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, ROOT)

from benchmark.conformance.runner import run_conformance_backtest, should_auto_run_conformance


def main() -> int:
    parser = argparse.ArgumentParser(description="Cognition architecture conformance backtest")
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--layer", action="append", choices=["stage1", "stage2", "integrated"])
    parser.add_argument("--no-visuals", action="store_true")
    parser.add_argument("--auto-check", action="store_true")
    args = parser.parse_args()

    if args.auto_check and not should_auto_run_conformance():
        print(json.dumps({"status": "SKIPPED", "reason": "auto interval not elapsed"}, indent=2))
        return 0

    result = run_conformance_backtest(
        layers=args.layer,
        lookback_days=args.lookback_days,
        generate_visuals=not args.no_visuals,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") in ("OK", "SKIPPED") else 1


if __name__ == "__main__":
    sys.exit(main())
