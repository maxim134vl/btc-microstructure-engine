"""Canonical runtime pipeline — extracted from master_auction_runtime_v1 (no logic changes)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime

from runtime_config import RUNTIME_LOOP_DELAY
from runtime_dependency_guard import should_run_engine
from runtime_dependency_map import DEPENDENCIES
from runtime_state_manager import update_runtime_state

CANONICAL_PIPELINE = [
    "candle_structure_engine_v1.py",
    "volume_classification_engine_v1.py",
    "schema_validation_engine_v1.py",
    "behavioral_sequence_memory_v1.py",
    "behavioral_volume_observer_v1.py",
    "microstructure_candle_engine_v1.py",
    "volume_response_engine_v1.py",
    "climactic_behavior_engine_v1.py",
    "auction_convergence_engine_v1.py",
    "auction_synthesis_engine_v1.py",
    "stage2_cognition_runtime_v1.py",
    "runtime_cognition_engine_v1.py",
    "auction_reinforcement_engine_v1.py",
    "probabilistic_auction_engine_v1.py",
    "auction_decay_engine_v1.py",
    "state_transition_engine_v1.py",
    "adaptive_meta_cognition_engine_v1.py",
]


def _repo_root() -> str:
    return os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        )
    )


def _load_engines():
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    from engine_registry import ENGINES

    return ENGINES


def run_once() -> None:
    """Execute one full canonical pipeline pass."""

    engines = _load_engines()
    root = _repo_root()
    python = sys.executable

    print()
    print("=" * 40)
    print(datetime.now())
    print("=" * 40)
    print()

    for engine in CANONICAL_PIPELINE:
        print("RUNNING:", engine)

        if engine in DEPENDENCIES:
            if not should_run_engine(engine, DEPENDENCIES[engine]):
                print("SKIPPED:", engine)
                print()
                continue

        start_time = time.time()
        try:
            if engine in engines:
                engines[engine]()
            else:
                result = subprocess.run(
                    [python, os.path.join(root, engine)],
                    cwd=root,
                    capture_output=False,
                    text=True,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"ENGINE FAILED: {engine}")

            duration = round(time.time() - start_time, 2)
            print(f"SUCCESS ({duration}s)")
            update_runtime_state(engine, "SUCCESS", duration)
        except Exception as error:
            duration = round(time.time() - start_time, 2)
            print(f"FAILED ({duration}s)")
            update_runtime_state(engine, "FAILED", duration)
            print(error)

        print()


def run_forever() -> None:
    """Run canonical pipeline loop."""

    print()
    print("BTC-ML CANONICAL RUNTIME")
    print()

    while True:
        run_once()
        time.sleep(RUNTIME_LOOP_DELAY)
