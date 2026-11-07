#!/usr/bin/env python3
"""Deprecated behavioral orchestrator — use ./run.sh or python run.py (Phase 4B)."""

from __future__ import annotations

import sys
import warnings


def main() -> int:
    warnings.warn(
        "behavioral_runtime_orchestrator_v1.py is deprecated; use ./run.sh or python run.py",
        DeprecationWarning,
        stacklevel=1,
    )
    print()
    print("DEPRECATED: behavioral_runtime_orchestrator_v1.py")
    print("Canonical runtime: ./run.sh  or  python run.py")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
