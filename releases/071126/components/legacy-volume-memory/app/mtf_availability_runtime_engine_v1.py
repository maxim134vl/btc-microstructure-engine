#!/usr/bin/env python3
"""Patch 3.2 — MTF availability runtime engine (post Stage-2 operational read-model).

REQUIRED_OPERATIONAL_READ_MODEL — not a trading decision engine.
Failures leave previous artifacts intact and do not roll back upstream cognition.
"""

from __future__ import annotations


def run() -> int:
    print()
    print("MTF AVAILABILITY RUNTIME ENGINE")
    print()
    try:
        from runtime_multi_timeframe_availability import run_availability_cycle

        result = run_availability_cycle(bootstrap_window=None, enrich_climax=False)
        print("event:", result.get("event"))
        print("rows_added:", result.get("rows_added"))
        print("latest_evaluation_timestamp:", result.get("latest_evaluation_timestamp"))
        print("overall_health:", result.get("overall_health"))
        print()
        return 0
    except Exception as error:  # noqa: BLE001
        # Fail-closed for this stage only; pipeline catches and continues.
        print(f"MTF_AVAILABILITY_FAILED: {type(error).__name__}: {error}")
        print()
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
