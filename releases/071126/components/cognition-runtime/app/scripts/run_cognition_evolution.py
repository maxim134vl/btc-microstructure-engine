#!/usr/bin/env python3
"""Run longitudinal cognition memory evolution cycle."""

from __future__ import annotations

import argparse
import json
import sys

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, ROOT)

from benchmark.memory.runner import run_full_evolution_cycle, run_longitudinal_evolution, should_auto_run_memory


def main() -> int:
    parser = argparse.ArgumentParser(description="Longitudinal cognition memory evolution")
    parser.add_argument("--full-cycle", action="store_true", help="Run all benchmarks then evolution")
    parser.add_argument("--auto-check", action="store_true")
    args = parser.parse_args()

    if args.auto_check and not should_auto_run_memory():
        print(json.dumps({"status": "SKIPPED", "reason": "auto interval not elapsed"}, indent=2))
        return 0

    result = run_full_evolution_cycle() if args.full_cycle else run_longitudinal_evolution()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
