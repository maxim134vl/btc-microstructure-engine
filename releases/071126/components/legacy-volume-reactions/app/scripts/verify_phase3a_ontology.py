"""Phase 3A behavioral ontology refinement verification."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def bootstrap_runtime() -> None:
    os.environ["ENABLE_ONTOLOGY_REFINEMENT"] = "true"
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


def check_effort_result_separation() -> bool:
    import pandas as pd

    from auction_climax_engine_v1 import process_auction_climax
    from parquet_utils import safe_read_parquet

    dataset = safe_read_parquet("candle_structure_memory.parquet")
    if len(dataset) == 0:
        print("SKIP: no candle structure data for effort/result check")
        return True

    result = process_auction_climax(dataset=dataset, timeframe="M15")
    events = result["auction_states"]
    stopping = events[events["auction_event_type"] == "STOPPING_VOLUME"]
    selling = events[events["auction_event_type"] == "SELLING_CLIMAX"]

    if len(stopping) > 0:
        if (stopping["efficiency_decay"] >= 0.85).any():
            print("FAIL: STOPPING_VOLUME found in grey/capitulation decay zone")
            return False

    if len(selling) > 0:
        if (selling["efficiency_decay"] <= 1.20).any():
            print("FAIL: SELLING_CLIMAX found outside capitulation decay zone")
            return False

    print(
        "PASS: effort/result separation "
        f"(stopping={len(stopping)}, selling={len(selling)})"
    )
    return True


def check_no_overlap_collapse() -> bool:
    from ontology_refinement import detect_overlap_violations
    from auction_climax_engine_v1 import process_auction_climax
    from scripts.replay_validation.ontology.replay_utils import load_candle_structure

    dataset = load_candle_structure()
    if len(dataset) == 0:
        print("SKIP: no candle data for overlap check")
        return True

    classified = process_auction_climax(dataset=dataset, timeframe="M15")["auction_states"]
    violations = detect_overlap_violations(classified)
    if violations:
        print(f"FAIL: overlap collapse signals on {len(violations)} rows")
        return False

    stopping = classified[classified["auction_event_type"] == "STOPPING_VOLUME"]
    selling = classified[classified["auction_event_type"] == "SELLING_CLIMAX"]
    dual = stopping.index.intersection(selling.index)
    if len(dual) > 0:
        print("FAIL: dual STOPPING/SELLING labels on same rows")
        return False

    print("PASS: no ontology overlap collapse")
    return True


def _build_test_frame(**overrides) -> "pd.DataFrame":
    import pandas as pd

    rows = []
    for _ in range(23):
        rows.append(
            {
                "volume_percentile_50": 0.70,
                "spread_percentile_50": 0.50,
                "delta": -600.0,
                "range_position": 0.30,
                "efficiency_decay": 0.95,
                "close_position_ratio": 0.30,
                "lower_wick_ratio": 0.15,
                "auction_event_type": "NORMAL",
                "location_bias": "NEUTRAL",
            }
        )

    rows.append(
        {
            "volume_percentile_50": 0.85,
            "spread_percentile_50": 0.50,
            "delta": -950.0,
            "range_position": 0.30,
            "efficiency_decay": 0.95,
            "close_position_ratio": 0.30,
            "lower_wick_ratio": 0.15,
            "auction_event_type": "NORMAL",
            "location_bias": "NEUTRAL",
        }
    )

    final_row = {
        "volume_percentile_50": 0.90,
        "spread_percentile_50": 0.55,
        "delta": -900.0,
        "range_position": 0.30,
        "efficiency_decay": 0.70,
        "close_position_ratio": 0.40,
        "lower_wick_ratio": 0.30,
        "auction_event_type": "NORMAL",
        "location_bias": "NEUTRAL",
    }
    final_row.update(overrides)
    rows.append(final_row)
    return pd.DataFrame(rows)


def check_no_overwrite_behavior() -> bool:
    from ontology_refinement import apply_semantic_separation

    frame = _build_test_frame()
    classified = apply_semantic_separation(frame)
    if classified.iloc[-1]["auction_event_type"] != "STOPPING_VOLUME":
        print("FAIL: STOPPING_VOLUME not assigned under absorption anatomy")
        return False

    frame = _build_test_frame(
        efficiency_decay=1.35,
        close_position_ratio=0.15,
        lower_wick_ratio=0.10,
        delta=-1100.0,
    )
    classified = apply_semantic_separation(frame)
    if classified.iloc[-1]["auction_event_type"] != "SELLING_CLIMAX":
        print("FAIL: SELLING_CLIMAX not assigned when NORMAL and capitulation anatomy")
        return False

    frame.iloc[-1, frame.columns.get_loc("auction_event_type")] = "STOPPING_VOLUME"
    frame.iloc[-1, frame.columns.get_loc("location_bias")] = "LOWER_ABSORPTION"
    classified = apply_semantic_separation(frame)
    if classified.iloc[-1]["auction_event_type"] != "STOPPING_VOLUME":
        print("FAIL: SELLING_CLIMAX overwrote STOPPING_VOLUME")
        return False

    print("PASS: mutual exclusion — no overwrite behavior")
    return True


def check_no_runtime_lookahead() -> bool:
    import inspect

    from auction_climax_engine_v1 import process_auction_climax

    source = inspect.getsource(process_auction_climax)
    os.environ["ENABLE_ONTOLOGY_REFINEMENT"] = "true"
    os.environ.pop("USE_LEGACY_CLIMAX_ONTOLOGY", None)

    if "future_return_3" in source and "shift(-3)" in source:
        # Allowed only behind legacy gate
        if "ontology_refinement_active" not in source:
            print("FAIL: future_return_3 still unconditionally in runtime path")
            return False

    from ontology_config import ontology_refinement_active

    if ontology_refinement_active():
        from parquet_utils import safe_read_parquet

        dataset = safe_read_parquet("candle_structure_memory.parquet")
        if len(dataset) > 0:
            result = process_auction_climax(dataset=dataset, timeframe="M15")
            if "future_return_3" in result["auction_states"].columns:
                print("FAIL: future_return_3 exported in refined runtime ontology")
                return False

    print("PASS: no runtime lookahead dependency in refined ontology")
    return True


def check_adversarial_ontology_stability() -> bool:
    from adversarial_ontology_stability import evaluate_ontology_under_stress

    result = evaluate_ontology_under_stress()
    if not bool(result.get("ontology_adversarial_stable")):
        print(
            "FAIL: adversarial ontology instability "
            f"({result.get('ontology_stress_failures')})"
        )
        return False

    print(
        "PASS: adversarial ontology stable "
        f"(score={result.get('ontology_separation_score')})"
    )
    return True


def check_replay_consistency() -> bool:
    from scripts.replay_validation.ontology.ontology_replay_runner import main as replay_main

    if replay_main() != 0:
        print("FAIL: ontology replay suite failed")
        return False

    print("PASS: ontology replay suite executed")
    return True


def check_no_regression() -> bool:
    for script in ("verify_phase2a_robustness.py", "verify_phase2b_adversarial.py"):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"FAIL: regression in {script}")
            print(result.stdout[-500:])
            print(result.stderr[-500:])
            return False

    print("PASS: Phase 2A/2B systems still passing")
    return True


def main() -> int:
    print()
    print("PHASE 3A ONTOLOGY REFINEMENT VERIFICATION")
    print("=" * 60)

    checks = [
        ("effort/result separation", check_effort_result_separation()),
        ("no overlap collapse", check_no_overlap_collapse()),
        ("no overwrite behavior", check_no_overwrite_behavior()),
        ("no runtime lookahead", check_no_runtime_lookahead()),
        ("adversarial ontology stability", check_adversarial_ontology_stability()),
        ("replay consistency", check_replay_consistency()),
        ("no Phase 2A/2B regression", check_no_regression()),
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
