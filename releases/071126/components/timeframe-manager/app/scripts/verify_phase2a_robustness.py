"""Phase 2A cross-regime robustness and calibration stability verification."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from parquet_utils import safe_read_parquet


def bootstrap_runtime() -> None:
    from runtime_cognition_engine_v1 import run as run_runtime_cognition
    from stage2_cognition_runtime_v1 import run as run_stage2
    from state_manager_v1 import refresh_state

    run_stage2()
    run_runtime_cognition()
    refresh_state()

    from auction_reinforcement_engine_v1 import run as run_reinforcement
    from probabilistic_auction_engine_v1 import run as run_probabilistic

    run_reinforcement()
    run_probabilistic()
    refresh_state()


def check_regime_exports() -> bool:
    import pandas as pd

    bootstrap_runtime()
    frame = safe_read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]

    required = [
        "regime_state",
        "regime_confidence",
        "regime_transition_probability",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        print(f"FAIL: regime export columns missing: {missing}")
        return False

    if latest.get("regime_state") not in {
        "TREND_EXPANSION",
        "TREND_EXHAUSTION",
        "COMPRESSION",
        "VOLATILITY_EXPANSION",
        "VOLATILITY_COLLAPSE",
        "LIQUIDATION_EVENT",
        "ABSORPTION_RECOVERY",
        "BALANCED_AUCTION",
    }:
        print(f"FAIL: invalid regime_state: {latest.get('regime_state')}")
        return False

    confidence = float(latest.get("regime_confidence", -1))
    if confidence < 0 or confidence > 1:
        print(f"FAIL: regime_confidence out of range: {confidence}")
        return False

    print(
        "PASS: regime exports present "
        f"({latest.get('regime_state')}, confidence={confidence:.3f})"
    )
    return True


def check_drift_metrics() -> bool:
    import pandas as pd

    frame = safe_read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]
    required = [
        "calibration_drift_score",
        "drift_components",
        "drift_direction",
        "drift_persistence_duration",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        print(f"FAIL: drift metrics missing: {missing}")
        return False

    score = float(latest.get("calibration_drift_score", -1))
    if score < 0 or score > 1:
        print(f"FAIL: calibration_drift_score out of range: {score}")
        return False

    print(
        "PASS: drift metrics exported "
        f"(score={score:.3f}, direction={latest.get('drift_direction')})"
    )
    return True


def check_walk_forward_stability() -> bool:
    import pandas as pd

    frame = safe_read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]
    required = [
        "walk_forward_epoch",
        "calibration_stability_score",
        "regime_drift_score",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        print(f"FAIL: walk-forward stability exports missing: {missing}")
        return False

    stability = float(latest.get("calibration_stability_score", -1))
    if stability < 0 or stability > 1:
        print(f"FAIL: calibration_stability_score out of range: {stability}")
        return False

    print(
        "PASS: walk-forward stability exported "
        f"(epoch={latest.get('walk_forward_epoch')}, score={stability:.3f})"
    )
    return True


def check_replay_consistency() -> bool:
    from scripts.replay_validation.cross_regime.regime_transition_replay import (
        run as regime_replay,
    )
    from scripts.replay_validation.cross_regime.calibration_drift_replay import (
        run as drift_replay,
    )

    regime_replay(limit=50)
    drift_replay(limit=50)
    print("PASS: cross-regime replay modules executed")
    return True


def check_cross_regime_analysis() -> bool:
    from cross_regime_calibration_analysis import run as generate_analysis

    metrics = generate_analysis(sample_size=200)
    path = os.path.join(ROOT, "docs", "CROSS_REGIME_CALIBRATION_ANALYSIS.md")
    if not os.path.exists(path):
        print("FAIL: CROSS_REGIME_CALIBRATION_ANALYSIS.md not generated")
        return False

    if not metrics.get("regime_metrics"):
        print("WARN: no regime metrics in analysis sample")

    print("PASS: cross-regime calibration analysis generated")
    return True


def check_no_runtime_regression() -> bool:
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "verify_phase1b_discipline.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("FAIL: Phase 1B regression detected")
        print(result.stdout)
        print(result.stderr)
        return False

    print("PASS: Phase 1B integrity still passing")
    return True


def main() -> int:
    print()
    print("PHASE 2A CROSS-REGIME ROBUSTNESS VERIFICATION")
    print("=" * 60)

    checks = [
        ("regime exports", check_regime_exports()),
        ("drift metrics", check_drift_metrics()),
        ("walk-forward stability", check_walk_forward_stability()),
        ("replay consistency", check_replay_consistency()),
        ("cross-regime analysis", check_cross_regime_analysis()),
        ("no runtime regression", check_no_runtime_regression()),
    ]

    print()
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")

    print()
    if all(result for _, result in checks):
        print("RESULT: PASS")
        return 0

    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
