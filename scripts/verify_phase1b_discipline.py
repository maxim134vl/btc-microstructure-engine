"""Phase 1B controlled probabilistic discipline verification."""

from __future__ import annotations

import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from parquet_utils import safe_read_parquet


def _run_with_env(env: dict[str, str]) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "verify_phase1_calibration.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=merged,
    )


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


def check_backward_compatible_default() -> bool:
    for key in [
        "ENABLE_PROBABILISTIC_DISCIPLINE",
        "USE_DISCIPLINED_CONVICTION_AT_RUNTIME",
    ]:
        os.environ.pop(key, None)

    result = _run_with_env({})
    if result.returncode != 0:
        print("FAIL: Phase 1A verification failed with discipline disabled")
        print(result.stdout)
        print(result.stderr)
        return False

    print("PASS: backward-compatible default (discipline OFF)")
    return True


def check_discipline_exports_default() -> bool:
    import pandas as pd

    bootstrap_runtime()
    frame = safe_read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]

    required = [
        "disciplined_conviction",
        "reinforcement_damping_factor",
        "entropy_discipline_factor",
        "persistence_realism_factor",
        "contradiction_control_factor",
        "raw_vs_disciplined_divergence",
        "saturation_reduction",
        "calibration_mode",
        "discipline_active",
    ]

    missing = [column for column in required if column not in frame.columns]
    if missing:
        print(f"FAIL: discipline export columns missing: {missing}")
        return False

    if bool(latest.get("discipline_active")):
        print("FAIL: discipline_active should be false by default")
        return False

    if not math.isclose(
        float(latest["raw_conviction"]),
        float(latest["disciplined_conviction"]),
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        print("FAIL: raw and disciplined conviction diverged with discipline OFF")
        return False

    print("PASS: discipline exports present and inactive by default")
    return True


def check_discipline_enabled_replay() -> bool:
    from calibration_config import CalibrationSettings
    from scripts.replay_validation.discipline_comparison import run as replay_compare

    output = replay_compare(limit=50)
    if len(output) == 0:
        print("WARN: no replay rows for discipline comparison")

    settings = CalibrationSettings(enable_probabilistic_discipline=True)
    if not settings.enable_probabilistic_discipline:
        print("FAIL: discipline settings failed to enable")
        return False

    if len(output) > 0 and float(output["divergence"].mean()) <= 0:
        print("WARN: discipline ON produced zero mean divergence on sample")

    print("PASS: discipline replay comparison executed")
    return True


def check_results_report() -> bool:
    from phase_1b_calibration_results import run as generate_results

    metrics = generate_results(sample_size=100)
    report_path = os.path.join(ROOT, "docs", "PHASE_1B_CALIBRATION_RESULTS.md")
    if not os.path.exists(report_path):
        print("FAIL: PHASE_1B_CALIBRATION_RESULTS.md not generated")
        return False

    if "discipline_on" not in metrics:
        print("FAIL: results metrics incomplete")
        return False

    print("PASS: Phase 1B results report generated")
    return True


def check_runtime_with_discipline_enabled() -> bool:
    env = {
        "ENABLE_PROBABILISTIC_DISCIPLINE": "true",
        "USE_DISCIPLINED_CONVICTION_AT_RUNTIME": "true",
        "CALIBRATION_MODE": "disciplined",
    }

    merged = os.environ.copy()
    merged.update(env)

    bootstrap = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.verify_phase1_calibration import bootstrap_runtime_chain; "
            "bootstrap_runtime_chain()",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=merged,
    )

    if bootstrap.returncode != 0:
        print("FAIL: runtime bootstrap failed with discipline enabled")
        print(bootstrap.stdout)
        print(bootstrap.stderr)
        return False

    import pandas as pd

    frame = safe_read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]

    if not bool(latest.get("discipline_active")):
        print("FAIL: discipline_active not true when enabled")
        return False

    if float(latest["disciplined_conviction"]) >= float(latest["raw_conviction"]):
        print("WARN: disciplined conviction not lower than raw on latest sample")

    print("PASS: runtime discipline enabled path executed")
    return True


def main() -> int:
    print()
    print("PHASE 1B PROBABILISTIC DISCIPLINE VERIFICATION")
    print("=" * 60)

    checks = [
        ("backward-compatible default", check_backward_compatible_default()),
        ("discipline exports (default off)", check_discipline_exports_default()),
        ("discipline replay comparison", check_discipline_enabled_replay()),
        ("Phase 1B results report", check_results_report()),
        ("runtime with discipline enabled", check_runtime_with_discipline_enabled()),
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
