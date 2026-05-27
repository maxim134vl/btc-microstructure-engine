#!/usr/bin/env python3
"""Unified canonical runtime entrypoint — Phase 4A/4B."""

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


def _run_hardening() -> int:
    from runtime_hardening import run_hardening_checks

    report = run_hardening_checks()
    for item in report.passed:
        print(f"  [PASS] {item}")
    for item in report.warnings:
        print(f"  [WARN] {item}")
    for item in report.failures:
        print(f"  [FAIL] {item}")
    print()
    return 0 if report.ok else 1


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
    parser.add_argument(
        "--verify-4b",
        action="store_true",
        help="Run Phase 4B hardening verification and exit",
    )
    parser.add_argument(
        "--hardening",
        action="store_true",
        help="Run operational hardening checks only",
    )
    parser.add_argument(
        "--skip-hardening",
        action="store_true",
        help="Skip startup hardening checks (not recommended)",
    )
    args = parser.parse_args()

    _bootstrap_paths()

    if args.hardening:
        print()
        print("OPERATIONAL HARDENING")
        print("=" * 60)
        return _run_hardening()

    if args.verify_4b:
        from scripts.verify_phase4b_hardening import main as verify_4b_main

        return verify_4b_main()

    if args.verify:
        from scripts.verify_phase4a_consolidation import main as verify_main

        return verify_main()

    if not args.skip_hardening:
        code = _run_hardening()
        if code != 0:
            print("Startup blocked — fix hardening failures or use --skip-hardening")
            return code

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
