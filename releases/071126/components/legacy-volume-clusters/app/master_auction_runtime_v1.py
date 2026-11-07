#!/usr/bin/env python3
"""Deprecated legacy entrypoint — use ./run.sh or python run.py (Phase 4B)."""

from __future__ import annotations

import os
import sys
import warnings


def _bootstrap_paths() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(root, "src")
    if root not in sys.path:
        sys.path.insert(0, root)
    if src not in sys.path:
        sys.path.insert(0, src)


def main() -> int:
    warnings.warn(
        "master_auction_runtime_v1.py is deprecated; use ./run.sh or python run.py",
        DeprecationWarning,
        stacklevel=1,
    )
    print()
    print("DEPRECATED ENTRYPOINT")
    print("Redirecting to canonical runtime (run.py pipeline)...")
    print()

    _bootstrap_paths()

    from btc_ml.runtime.pipeline import run_forever

    run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
