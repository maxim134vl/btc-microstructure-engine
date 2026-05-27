#!/usr/bin/env python3
"""Verify ontology density restoration — replay env audit + regression gates."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def check_replay_environment_audit() -> bool:
    from ontology_density.replay_environment_audit import build_replay_environment_profile

    profile = build_replay_environment_profile()
    if profile.get("candle_row_count", 0) <= 0:
        print("FAIL: no candle structure data for replay")
        return False
    if profile.get("row_count_mismatch", {}).get("is_misleading_denominator"):
        print("PASS: replay env audit flags probabilistic/candle denominator mismatch")
    else:
        print("PASS: replay environment profile built")
    return True


def check_density_restored() -> bool:
    from ontology_density._climax_helpers import count_events, run_climax_mode
    from stabilization_data_utils import load_candle_structure

    candles = load_candle_structure()
    n = len(candles)
    if n == 0:
        print("FAIL: empty candle structure")
        return False

    legacy = count_events(run_climax_mode("legacy", candles))
    current = count_events(run_climax_mode("current", candles))

    # Sell-side separation must exist when legacy had sell-side events
    legacy_sell = legacy.get("SELLING_CLIMAX", 0) + legacy.get("STOPPING_VOLUME", 0)
    current_sell = current.get("SELLING_CLIMAX", 0) + current.get("STOPPING_VOLUME", 0)

    if legacy_sell > 0 and current_sell == 0:
        print(f"FAIL: sell-side density collapsed (legacy={legacy_sell}, current={current_sell})")
        return False

    # Total non-normal should not be below 25% of legacy on same window (restoration floor)
    legacy_total = legacy.get("TOTAL_NON_NORMAL", 0)
    current_total = current.get("TOTAL_NON_NORMAL", 0)
    if legacy_total > 0 and current_total < max(1, int(legacy_total * 0.25)):
        print(f"FAIL: total ontology density too low ({current_total} vs legacy {legacy_total})")
        return False

    print(f"PASS: ontology density restored (current={current}, legacy={legacy}, candles={n})")
    return True


def check_separation_preserved() -> bool:
    from ontology_refinement import detect_overlap_violations
    from ontology_density.ontology_filter_waterfall import _prepare_frame
    from stabilization_data_utils import load_candle_structure

    dataset = load_candle_structure()
    if len(dataset) == 0:
        print("WARN: skip separation check — no data")
        return True

    frame = _prepare_frame(dataset)
    violations = detect_overlap_violations(frame)
    if violations:
        print(f"FAIL: overlap violations={len(violations)}")
        return False

    print("PASS: SELLING/STOPPING separation preserved (no overlap violations)")
    return True


def check_replay_integrity() -> bool:
    from scripts.replay_validation.final_validation.final_validation_runner import main as replay_main

    if replay_main() != 0:
        print("FAIL: final validation replay suite")
        return False
    print("PASS: replay integrity")
    return True


def check_no_regression() -> bool:
    scripts = (
        "verify_phase3a_ontology.py",
        "verify_phase3b_stabilization.py",
        "verify_phase4b_hardening.py",
    )
    for script in scripts:
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"FAIL: regression in {script}")
            return False
    print("PASS: Phase 3A–4B verification still passing")
    return True


def main() -> int:
    print()
    print("ONTOLOGY DENSITY RESTORATION VERIFICATION")
    print("=" * 60)

    checks = [
        ("replay environment audit", check_replay_environment_audit()),
        ("ontology density restored", check_density_restored()),
        ("SELLING/STOPPING separation", check_separation_preserved()),
        ("replay integrity", check_replay_integrity()),
        ("no Phase 3A–4B regression", check_no_regression()),
    ]

    print()
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")

    print()
    if all(p for _, p in checks):
        print("RESULT: PASS")
        return 0
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
