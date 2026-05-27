"""Phase 4A canonical consolidation verification."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))


def check_canonical_entrypoint() -> bool:
    from btc_ml.runtime.pipeline import CANONICAL_PIPELINE, run_once

    if len(CANONICAL_PIPELINE) != 17:
        print(f"FAIL: expected 17 pipeline steps, got {len(CANONICAL_PIPELINE)}")
        return False

    if not os.path.exists(os.path.join(ROOT, "run.py")):
        print("FAIL: run.py missing")
        return False

    print("PASS: canonical entrypoint and pipeline defined")
    return True


def check_no_duplicate_runtime_paths() -> bool:
    from scripts.final_repo_audit import check_duplicate_backups_at_root

    if not check_duplicate_backups_at_root():
        return False

    package_pipeline = os.path.join(ROOT, "src", "btc_ml", "runtime", "pipeline.py")
    if not os.path.exists(package_pipeline):
        print("FAIL: package pipeline missing")
        return False

    print("PASS: no duplicate runtime backup paths at root")
    return True


def check_migration_integrity() -> bool:
    packages = [
        "btc_ml",
        "btc_ml.runtime",
        "btc_ml.ontology",
        "btc_ml.calibration",
        "btc_ml.diagnostics",
        "btc_ml.resilience",
        "btc_ml.storage",
        "btc_ml.config",
    ]
    for name in packages:
        try:
            __import__(name)
        except ImportError as error:
            print(f"FAIL: cannot import {name}: {error}")
            return False

    print("PASS: src/btc_ml migration shims import successfully")
    return True


def check_topology_audit() -> bool:
    from ontology_topology_audit import build_ontology_topology_audit

    audit = build_ontology_topology_audit()
    required = [
        "ontology_topology_map",
        "ontology_compression_zones",
        "semantic_stability_index",
    ]
    missing = [key for key in required if key not in audit]
    if missing:
        print(f"FAIL: topology audit missing: {missing}")
        return False

    stability = float(audit["semantic_stability_index"])
    if stability < 0 or stability > 1:
        print(f"FAIL: semantic_stability_index out of range: {stability}")
        return False

    print(f"PASS: ontology topology audit (stability={stability:.3f})")
    return True


def check_replay_integrity() -> bool:
    from scripts.replay_validation.final_validation.final_validation_runner import main as replay_main

    if replay_main() != 0:
        print("FAIL: final validation replay suite failed")
        return False

    print("PASS: final validation replay suite executed")
    return True


def check_repo_audit() -> bool:
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "final_repo_audit.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("FAIL: final_repo_audit failed")
        print(result.stdout[-800:])
        return False

    print("PASS: final repository audit passed")
    return True


def check_no_regression() -> bool:
    scripts = (
        "verify_phase0b_integrity.py",
        "verify_phase2a_robustness.py",
        "verify_phase2b_adversarial.py",
        "verify_phase3a_ontology.py",
        "verify_phase3b_stabilization.py",
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

    print("PASS: Phase 0B–3B verification still passing")
    return True


def main() -> int:
    print()
    print("PHASE 4A CANONICAL CONSOLIDATION VERIFICATION")
    print("=" * 60)

    checks = [
        ("canonical entrypoint", check_canonical_entrypoint()),
        ("no duplicate runtime paths", check_no_duplicate_runtime_paths()),
        ("migration integrity", check_migration_integrity()),
        ("topology audit", check_topology_audit()),
        ("replay integrity", check_replay_integrity()),
        ("repository audit", check_repo_audit()),
        ("no Phase 0B–3B regression", check_no_regression()),
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
