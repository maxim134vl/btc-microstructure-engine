"""Phase 2B adversarial robustness and failure-mode verification."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from parquet_utils import safe_read_parquet


def bootstrap_runtime(enable_adversarial: bool = False) -> None:
    if enable_adversarial:
        os.environ["ENABLE_ADVERSARIAL_DIAGNOSTICS"] = "true"
        os.environ["ENABLE_STRESS_SENSITIVITY"] = "true"
    else:
        os.environ.pop("ENABLE_ADVERSARIAL_DIAGNOSTICS", None)
        os.environ.pop("ENABLE_STRESS_SENSITIVITY", None)

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


def check_stress_engine_reproducibility() -> bool:
    from synthetic_stress_engine import apply_stress_scenario

    base = {
        "raw_conviction": 0.65,
        "entropy_penalty": 0.45,
        "conflict_density": 0.20,
    }
    first, _ = apply_stress_scenario("ENTROPY_SHOCK", base, seed=42)
    second, _ = apply_stress_scenario("ENTROPY_SHOCK", base, seed=42)
    if first != second:
        print("FAIL: stress engine not reproducible with same seed")
        return False

    third, _ = apply_stress_scenario("ENTROPY_SHOCK", base, seed=43)
    if first == third:
        print("FAIL: stress engine did not vary with seed")
        return False

    print("PASS: stress engine reproducible and seedable")
    return True


def check_failure_mode_exports_default() -> bool:
    import pandas as pd

    bootstrap_runtime(enable_adversarial=False)
    frame = safe_read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]

    required = [
        "failure_mode",
        "failure_probability",
        "collapse_velocity",
        "instability_cluster",
        "probabilistic_fragility_score",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        print(f"FAIL: failure-mode columns missing: {missing}")
        return False

    if latest.get("failure_mode") != "NONE":
        print("FAIL: failure_mode should be NONE when adversarial diagnostics off")
        return False

    print("PASS: failure-mode exports present and neutral by default")
    return True


def check_adversarial_exports_enabled() -> bool:
    import pandas as pd

    bootstrap_runtime(enable_adversarial=True)
    frame = safe_read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]

    if not bool(latest.get("adversarial_diagnostics_active")):
        print("FAIL: adversarial_diagnostics_active not true when enabled")
        return False

    required = [
        "instability_origin",
        "instability_propagation_chain",
        "transition_survival_score",
        "resilience_score",
        "adversarial_stability_score",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        print(f"FAIL: adversarial exports missing: {missing}")
        return False

    print(
        "PASS: adversarial exports active "
        f"(mode={latest.get('failure_mode')}, "
        f"fragility={latest.get('probabilistic_fragility_score')})"
    )
    return True


def check_instability_propagation() -> bool:
    from instability_propagation import compute_instability_propagation

    snapshot = {
        "alignment_monoculture_score": 0.85,
        "alignment_component": 1.25,
        "reinforcement_acceleration": 0.08,
        "conflict_density": 0.40,
        "entropy_penalty": 0.30,
        "raw_conviction": 0.72,
        "regime_transition_probability": 0.50,
    }
    result = compute_instability_propagation(snapshot)
    if result.get("instability_origin") == "none":
        print("FAIL: instability origin not detected for stressed snapshot")
        return False

    if not result.get("instability_propagation_chain"):
        print("FAIL: propagation chain empty")
        return False

    print("PASS: instability propagation tracking works")
    return True


def check_replay_consistency() -> bool:
    from scripts.replay_validation.adversarial.replay_runner import main as replay_main

    code = replay_main()
    if code != 0:
        print("FAIL: adversarial replay suite failed")
        return False

    print("PASS: adversarial replay suite executed")
    return True


def check_no_runtime_regression() -> bool:
    os.environ.pop("ENABLE_ADVERSARIAL_DIAGNOSTICS", None)
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "verify_phase2a_robustness.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("FAIL: Phase 2A regression detected")
        print(result.stdout)
        print(result.stderr)
        return False

    print("PASS: Phase 2A integrity still passing")
    return True


def main() -> int:
    print()
    print("PHASE 2B ADVERSARIAL ROBUSTNESS VERIFICATION")
    print("=" * 60)

    checks = [
        ("stress engine reproducibility", check_stress_engine_reproducibility()),
        ("failure-mode exports (default off)", check_failure_mode_exports_default()),
        ("adversarial exports (enabled)", check_adversarial_exports_enabled()),
        ("instability propagation", check_instability_propagation()),
        ("replay consistency", check_replay_consistency()),
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
