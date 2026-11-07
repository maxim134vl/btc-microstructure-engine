#!/usr/bin/env python3
"""Patch 3.2 — MTF availability runtime engine (post Stage-2 operational read-model).

REQUIRED_OPERATIONAL_READ_MODEL — not a trading decision engine.
Failures leave previous artifacts intact and do not roll back upstream cognition.
"""

from __future__ import annotations


_FORWARD_START = None


def run() -> int:
    print()
    print("MTF AVAILABILITY RUNTIME ENGINE")
    print()
    from runtime_engine_guard import EngineTimeoutError
    try:
        from runtime_multi_timeframe_availability import run_availability_cycle
        from multi_timeframe_availability import load_m15_candles, safe_m15_evaluation_timestamp

        global _FORWARD_START
        m15 = load_m15_candles()
        if _FORWARD_START is None:
            _FORWARD_START = safe_m15_evaluation_timestamp(m15)
        result = run_availability_cycle(bootstrap_window=None, enrich_climax=False,
                                        m15_frame=m15, forward_since=_FORWARD_START)
        print("event:", result.get("event"))
        print("rows_added:", result.get("rows_added"))
        print("latest_evaluation_timestamp:", result.get("latest_evaluation_timestamp"))
        print("overall_health:", result.get("overall_health"))
        print()
        return 0
    except EngineTimeoutError:
        raise
    except Exception as error:  # noqa: BLE001
        # Fail-closed for this stage only; pipeline catches and continues.
        print(f"MTF_AVAILABILITY_FAILED: {type(error).__name__}: {error}")
        print()
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
