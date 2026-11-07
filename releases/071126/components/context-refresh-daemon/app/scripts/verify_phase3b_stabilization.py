"""Phase 3B ontology stabilization verification."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from parquet_utils import safe_read_parquet


def bootstrap_runtime(enable_stabilization: bool = False) -> None:
    os.environ["ENABLE_ONTOLOGY_REFINEMENT"] = "true"
    if enable_stabilization:
        os.environ["ENABLE_ONTOLOGY_STABILIZATION"] = "true"
    else:
        os.environ.pop("ENABLE_ONTOLOGY_STABILIZATION", None)
    os.environ.pop("USE_LEGACY_CLIMAX_ONTOLOGY", None)

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


def check_stabilization_exports_default() -> bool:
    import pandas as pd

    os.environ.pop("ENABLE_ONTOLOGY_STABILIZATION", None)
    bootstrap_runtime(enable_stabilization=False)
    frame = safe_read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]

    required = [
        "reinforcement_stability_score",
        "contradiction_resolution_quality",
        "ontology_stability_score",
        "semantic_fragility_score",
        "ontology_overlap_matrix",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        print(f"FAIL: stabilization columns missing: {missing}")
        return False

    if latest.get("ontology_stabilization_active") not in {True, False}:
        print("FAIL: ontology_stabilization_active missing")
        return False

    print("PASS: stabilization export columns present")
    return True


def check_stabilization_exports_enabled() -> bool:
    import pandas as pd

    os.environ["ENABLE_ONTOLOGY_STABILIZATION"] = "true"
    bootstrap_runtime(enable_stabilization=True)
    frame = safe_read_parquet("probabilistic_auction_memory.parquet")
    latest = frame.iloc[-1]

    if not bool(latest.get("ontology_stabilization_active")):
        print("FAIL: ontology_stabilization_active not true when enabled")
        return False

    stability = float(latest.get("ontology_stability_score", -1))
    if stability < 0 or stability > 1:
        print(f"FAIL: ontology_stability_score out of range: {stability}")
        return False

    print(
        "PASS: stabilization exports active "
        f"(stability={stability:.3f}, fragility={latest.get('semantic_fragility_score')})"
    )
    return True


def check_reinforcement_redistribution() -> bool:
    from post_split_reinforcement_analysis import analyze_reinforcement_redistribution
    from stabilization_data_utils import load_climax_events, load_probabilistic, load_reinforcement

    exports = analyze_reinforcement_redistribution(
        load_climax_events(),
        probabilistic=load_probabilistic(),
        reinforcement=load_reinforcement(),
    )
    score = float(exports.get("reinforcement_stability_score", -1))
    if score < 0 or score > 1:
        print("FAIL: reinforcement_stability_score out of range")
        return False

    print("PASS: reinforcement redistribution integrity")
    return True


def check_contradiction_redistribution() -> bool:
    from contradiction_redistribution import analyze_contradiction_redistribution
    from stabilization_data_utils import load_climax_events, load_probabilistic

    exports = analyze_contradiction_redistribution(
        load_climax_events(),
        probabilistic=load_probabilistic(),
    )
    quality = float(exports.get("contradiction_resolution_quality", -1))
    if quality < 0 or quality > 1:
        print("FAIL: contradiction_resolution_quality out of range")
        return False

    print("PASS: contradiction redistribution stability")
    return True


def check_entropy_divergence() -> bool:
    from semantic_entropy_evolution import analyze_entropy_evolution_divergence
    from stabilization_data_utils import load_climax_events

    exports = analyze_entropy_evolution_divergence(load_climax_events())
    if "entropy_divergence_score" not in exports:
        print("FAIL: entropy divergence exports missing")
        return False

    print("PASS: entropy divergence consistency")
    return True


def check_overlap_and_buying_hav() -> bool:
    import json

    from buying_exhaustion_validation import analyze_buying_exhaustion
    from hav_semantic_analysis import analyze_hav_semantics
    from ontology_overlap_matrix import build_overlap_matrix
    from stabilization_data_utils import load_candle_structure, load_climax_events, load_probabilistic

    events = load_climax_events()
    dataset = load_candle_structure()
    probabilistic = load_probabilistic()

    buying = analyze_buying_exhaustion(events, dataset)
    hav = analyze_hav_semantics(events, dataset, probabilistic=probabilistic)
    overlap = build_overlap_matrix(events, dataset, probabilistic=probabilistic)

    if "buying_exhaustion_quality" not in buying:
        print("FAIL: buying exhaustion exports missing")
        return False
    if "hav_ontology_ambiguity_score" not in hav:
        print("FAIL: HAV ambiguity exports missing")
        return False

    try:
        json.loads(overlap.get("ontology_overlap_matrix", "{}"))
        json.loads(overlap.get("ontology_ambiguity_heatmap", "{}"))
    except json.JSONDecodeError:
        print("FAIL: overlap matrix JSON invalid")
        return False

    print("PASS: overlap stability + BUYING/HAV audit exports")
    return True


def check_replay_consistency() -> bool:
    from scripts.replay_validation.stabilization.stabilization_runner import main as replay_main

    if replay_main() != 0:
        print("FAIL: stabilization replay suite failed")
        return False

    print("PASS: stabilization replay suite executed")
    return True


def check_no_regression() -> bool:
    scripts = (
        "verify_phase2a_robustness.py",
        "verify_phase2b_adversarial.py",
        "verify_phase3a_ontology.py",
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

    print("PASS: Phase 2A/2B/3A systems still passing")
    return True


def main() -> int:
    print()
    print("PHASE 3B ONTOLOGY STABILIZATION VERIFICATION")
    print("=" * 60)

    checks = [
        ("stabilization exports present", check_stabilization_exports_default()),
        ("stabilization exports enabled", check_stabilization_exports_enabled()),
        ("reinforcement redistribution", check_reinforcement_redistribution()),
        ("contradiction redistribution", check_contradiction_redistribution()),
        ("entropy divergence", check_entropy_divergence()),
        ("overlap + BUYING/HAV audit", check_overlap_and_buying_hav()),
        ("replay consistency", check_replay_consistency()),
        ("no Phase 2A/2B/3A regression", check_no_regression()),
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
