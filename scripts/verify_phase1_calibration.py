"""Phase 1A probabilistic calibration diagnostics verification."""

from __future__ import annotations

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd

from calibration_diagnostics import (
    CALIBRATION_EXPORT_COLUMNS,
    CONFLICT_EXPORT_COLUMNS,
    DECOMPOSITION_COMPONENTS,
    DIAGNOSTIC_EXPORT_COLUMNS,
    PERSISTENCE_EXPORT_COLUMNS,
    SATURATION_EXPORT_COLUMNS,
    apply_sigmoid_calibration,
)
from conviction_realism_audit import run as run_realism_audit
from runtime_cognition_engine_v1 import run as run_runtime_cognition
from stage2_cognition_runtime_v1 import run as run_stage2
from state_manager_v1 import STATE, refresh_state


def bootstrap_runtime_chain() -> None:
    run_stage2()
    run_runtime_cognition()
    refresh_state()

    from auction_reinforcement_engine_v1 import run as run_reinforcement
    from probabilistic_auction_engine_v1 import run as run_probabilistic

    run_reinforcement()
    run_probabilistic()
    refresh_state()


def check_decomposition_integrity() -> bool:
    ok = True
    for path in [
        "auction_reinforcement_memory.parquet",
        "probabilistic_auction_memory.parquet",
    ]:
        if not os.path.exists(path):
            print(f"FAIL: {path} missing")
            return False

        frame = pd.read_parquet(path)
        if len(frame) == 0:
            print(f"FAIL: {path} empty")
            return False

        missing = set(DECOMPOSITION_COMPONENTS) - set(frame.columns)
        if missing:
            print(f"FAIL: {path} missing decomposition columns: {sorted(missing)}")
            ok = False
            continue

        print(f"PASS: {path} decomposition intact")

    return ok


def check_saturation_metrics() -> bool:
    frame = pd.read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]
    missing = set(SATURATION_EXPORT_COLUMNS) - set(frame.columns)
    if missing:
        print(f"FAIL: saturation metrics missing: {sorted(missing)}")
        return False

    score = float(latest.get("saturation_score", -1))
    if score < 0 or score > 1:
        print(f"FAIL: saturation_score out of range: {score}")
        return False

    print(
        "PASS: saturation metrics exported "
        f"(saturation_score={score:.4f}, "
        f"saturated={latest.get('conviction_saturated')})"
    )
    return True


def check_persistence_tracking() -> bool:
    frame = pd.read_parquet("probabilistic_auction_memory.parquet")
    missing = set(PERSISTENCE_EXPORT_COLUMNS) - set(frame.columns)
    if missing:
        print(f"FAIL: persistence tracking missing: {sorted(missing)}")
        return False

    latest = frame.iloc[-1]
    duration = latest.get("persistence_duration")
    print(
        "PASS: persistence tracking exported "
        f"(persistence_duration={duration})"
    )
    return True


def check_contradiction_export() -> bool:
    frame = pd.read_parquet("probabilistic_auction_memory.parquet")
    missing = set(CONFLICT_EXPORT_COLUMNS) - set(frame.columns)
    if missing:
        print(f"FAIL: contradiction export missing: {sorted(missing)}")
        return False

    latest = frame.iloc[-1]
    density = float(latest.get("conflict_density", -1))
    if density < 0:
        print(f"FAIL: conflict_density invalid: {density}")
        return False

    print(
        "PASS: contradiction export present "
        f"(conflict_density={density:.4f}, "
        f"flags={latest.get('contradiction_flags')})"
    )
    return True


def check_sigmoid_wrapper_consistency() -> bool:
    frame = pd.read_parquet("probabilistic_auction_memory.parquet")
    missing = set(CALIBRATION_EXPORT_COLUMNS) - set(frame.columns)
    if missing:
        print(f"FAIL: sigmoid wrapper columns missing: {sorted(missing)}")
        return False

    latest = frame.iloc[-1]
    raw = float(latest["raw_conviction"])
    calibrated = float(latest["calibrated_conviction"])
    runtime = float(latest["conviction_probability"])
    expected = apply_sigmoid_calibration(raw)

    if not math.isclose(calibrated, expected, rel_tol=1e-9, abs_tol=1e-9):
        print(
            "FAIL: calibrated_conviction mismatch "
            f"(got {calibrated}, expected {expected})"
        )
        return False

    if not math.isclose(raw, runtime, rel_tol=1e-9, abs_tol=1e-9):
        print(
            "FAIL: runtime conviction_probability diverged from raw_conviction "
            f"(raw={raw}, runtime={runtime})"
        )
        return False

    print(
        "PASS: sigmoid wrapper consistent "
        f"(raw={raw:.4f}, calibrated={calibrated:.4f}, runtime uses raw)"
    )
    return True


def check_no_runtime_regression() -> bool:
    import subprocess

    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "verify_phase0b_integrity.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("FAIL: Phase 0B integrity regression detected")
        print(result.stdout)
        print(result.stderr)
        return False

    print("PASS: Phase 0B integrity still passing")
    return True


def check_realism_audit_generated() -> bool:
    metrics = run_realism_audit()
    audit_path = os.path.join(ROOT, "docs", "CONVICTION_REALISM_AUDIT.md")
    if not os.path.exists(audit_path):
        print("FAIL: CONVICTION_REALISM_AUDIT.md not generated")
        return False

    if metrics.get("probabilistic_rows_analyzed", 0) <= 0:
        print("WARN: realism audit had zero probabilistic rows")

    print("PASS: conviction realism audit generated")
    return True


def check_diagnostic_column_count() -> bool:
    frame = pd.read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]
    missing = set(DIAGNOSTIC_EXPORT_COLUMNS) - set(frame.columns)
    if missing:
        print(f"FAIL: diagnostic export columns missing: {sorted(missing)}")
        return False

    print(
        "PASS: all diagnostic columns present on latest row "
        f"({len(DIAGNOSTIC_EXPORT_COLUMNS)} fields)"
    )
    return True


def main() -> int:
    print()
    print("PHASE 1A CALIBRATION DIAGNOSTICS VERIFICATION")
    print("=" * 60)

    bootstrap_runtime_chain()

    checks = [
        ("decomposition integrity", check_decomposition_integrity()),
        ("saturation metrics", check_saturation_metrics()),
        ("persistence tracking", check_persistence_tracking()),
        ("contradiction export", check_contradiction_export()),
        ("sigmoid wrapper consistency", check_sigmoid_wrapper_consistency()),
        ("diagnostic column export", check_diagnostic_column_count()),
        ("conviction realism audit", check_realism_audit_generated()),
        ("no runtime regression", check_no_runtime_regression()),
    ]

    print()
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    print()
    if all(result for _, result in checks):
        print("RESULT: PASS")
        return 0

    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
