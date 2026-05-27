#!/usr/bin/env python3
"""Unified canonical runtime entrypoint — Phase 4A."""

from __future__ import annotations

import argparse
import os
import sys


def _bootstrap_paths() -> str:
    root = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(root, "src")
    if root not in sys.path:
        sys.path.insert(0, root)
    if src not in sys.path:
        sys.path.insert(0, src)
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description="BTC-ML canonical runtime")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single pipeline pass instead of looping",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run Phase 4A consolidation verification and exit",
    )
    args = parser.parse_args()

    _bootstrap_paths()

    if args.verify:
        from scripts.verify_phase4a_consolidation import main as verify_main

        return verify_main()

    from btc_ml.runtime.pipeline import run_forever, run_once

    print()
    print("CANONICAL RUNTIME ENTRYPOINT")
    print("Root:", os.getcwd())
    print()

    if args.once:
        run_once()
        return 0

    run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
