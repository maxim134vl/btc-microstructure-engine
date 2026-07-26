"""Canonical runtime pipeline — extracted from master_auction_runtime_v1 (no logic changes)."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from runtime_config import ENGINE_TIMEOUT_SECONDS, RUNTIME_LOOP_DELAY
from runtime_dependency_guard import should_run_engine
from runtime_dependency_map import DEPENDENCIES
from runtime_engine_guard import (
    EngineTimeoutError,
    export_runtime_blocking_chain,
    run_engine_subprocess,
    run_inprocess_with_timeout,
)
from runtime_state_manager import update_runtime_state

try:
    from runtime_cache import clear_cache
except ImportError:
    def clear_cache() -> None:
        pass

_CYCLE_COUNT = 0

# Base order before volume-localization insertion (Phase 4A/4B candidate base).
_BASE_CANONICAL_PIPELINE_WITHOUT_VOLUME_LOCALIZATION = [
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
    "intermediate_cognition_engine_v1.py",
    "auction_reinforcement_engine_v1.py",
    "probabilistic_auction_engine_v1.py",
    "auction_context_arbitration_engine_v1.py",
    "auction_decay_engine_v1.py",
    "state_transition_engine_v1.py",
    "adaptive_meta_cognition_engine_v1.py",
    # Patch 3.2 — operational MTF availability read-model (after Stage-2 sources ready)
    "mtf_availability_runtime_engine_v1.py",
]

# Order contract: candle_structure → volume_localization → … → volume_response.
VOLUME_LOCALIZATION_LIVE_WIRING_ENGINE = "volume_localization_engine_v1.py"
VOLUME_LOCALIZATION_LIVE_WIRING_INSERT_AFTER = "candle_structure_engine_v1.py"


def canonical_pipeline_with_volume_localization_candidate(
    pipeline: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Return pipeline list with volume localization inserted in proven order."""
    base = list(
        pipeline
        if pipeline is not None
        else _BASE_CANONICAL_PIPELINE_WITHOUT_VOLUME_LOCALIZATION
    )
    engine = VOLUME_LOCALIZATION_LIVE_WIRING_ENGINE
    if engine in base:
        return base
    if VOLUME_LOCALIZATION_LIVE_WIRING_INSERT_AFTER not in base:
        raise ValueError(
            f"missing insert anchor {VOLUME_LOCALIZATION_LIVE_WIRING_INSERT_AFTER}"
        )
    if "volume_response_engine_v1.py" not in base:
        raise ValueError("missing volume_response_engine_v1.py in pipeline")
    idx = base.index(VOLUME_LOCALIZATION_LIVE_WIRING_INSERT_AFTER) + 1
    candidate = base[:idx] + [engine] + base[idx:]
    # Prove order invariants for callers/tests.
    assert candidate.index(engine) > candidate.index(
        VOLUME_LOCALIZATION_LIVE_WIRING_INSERT_AFTER
    )
    assert candidate.index(engine) < candidate.index("volume_response_engine_v1.py")
    return candidate


# Phase 4C controlled live activation — use proven helper order (21 steps).
CANONICAL_PIPELINE = canonical_pipeline_with_volume_localization_candidate()
EXPECTED_CANONICAL_PIPELINE_STEP_COUNT = 21


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

    global _CYCLE_COUNT
    _CYCLE_COUNT += 1

    clear_cache()

    engines = _load_engines()
    root = _repo_root()
    python = sys.executable

    print()
    print("=" * 40)
    print(datetime.now())
    print(f"PIPELINE CYCLE: {_CYCLE_COUNT}")
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
                result = run_inprocess_with_timeout(
                    engine,
                    engines[engine],
                    ENGINE_TIMEOUT_SECONDS,
                )
                if isinstance(result, int) and result != 0:
                    raise RuntimeError(f"ENGINE FAILED: {engine} (exit {result})")
            else:
                run_engine_subprocess(
                    python,
                    os.path.join(root, engine),
                    root,
                    engine,
                    ENGINE_TIMEOUT_SECONDS,
                    cycle_id=_CYCLE_COUNT,
                )

            duration = round(time.time() - start_time, 2)
            print(f"SUCCESS ({duration}s)")
            update_runtime_state(engine, "SUCCESS", duration)
        except EngineTimeoutError as error:
            duration = round(time.time() - start_time, 2)
            print(f"TIMEOUT ({duration}s)")
            update_runtime_state(engine, "TIMEOUT", duration)
            print(error)
            export_runtime_blocking_chain()
        except Exception as error:
            duration = round(time.time() - start_time, 2)
            print(f"FAILED ({duration}s)")
            update_runtime_state(engine, "FAILED", duration)
            print(error)
            export_runtime_blocking_chain()

        print()

    _emit_pipeline_dataset_metadata()


def _emit_pipeline_dataset_metadata() -> None:
    """Patch 1: best-effort metadata sidecars for pipeline-owned datasets.

    Never mutates parquet payloads. Failures must not stop the pipeline.
    Takes effect after process restart (not auto-restarted in Patch 1).
    """
    try:
        root = _repo_root()
        if root not in sys.path:
            sys.path.insert(0, root)
        from runtime_dataset_metadata import emit_metadata_for_path

        for rel in (
            "data/cognition/candle_structure_memory.parquet",
            "data/cognition/volume_response_state.parquet",
            "data/reinforcement/auction_synthesis_memory.parquet",
            "data/cognition/multi_timeframe_synthesis.parquet",
            "data/cognition/runtime_cognition_memory.parquet",
            "data/reinforcement/auction_reinforcement_memory.parquet",
            "data/probabilistic/probabilistic_auction_memory.parquet",
            "data/cognition/multi_timeframe_availability_memory.parquet",
            "data/runtime/multi_timeframe_availability_latest.json",
        ):
            emit_metadata_for_path(rel, root=Path(root), metadata_origin="LIVE_WRITER")
    except Exception as error:  # noqa: BLE001
        print(f"METADATA_WARN pipeline sidecars: {error}")


def _maybe_run_stage1_benchmark() -> None:
    try:
        from benchmark.stage1.runner import maybe_auto_run_benchmark

        result = maybe_auto_run_benchmark()
        if result and result.get("status") == "OK":
            print(f"Stage 1 benchmark auto-run complete: {result.get('run_id')}")
    except Exception as error:
        print(f"Stage 1 benchmark auto-run skipped: {error}")


def _maybe_run_stage2_benchmark() -> None:
    try:
        from benchmark.stage2.runner import maybe_auto_run_stage2_benchmark

        result = maybe_auto_run_stage2_benchmark()
        if result and result.get("status") == "OK":
            print(f"Stage 2 benchmark auto-run complete: {result.get('run_id')}")
    except Exception as error:
        print(f"Stage 2 benchmark auto-run skipped: {error}")


def _maybe_run_integrated_benchmark() -> None:
    try:
        from benchmark.integrated.runner import maybe_auto_run_integrated_benchmark

        result = maybe_auto_run_integrated_benchmark()
        if result and result.get("status") == "OK":
            print(f"Integrated benchmark auto-run complete: {result.get('run_id')}")
    except Exception as error:
        print(f"Integrated benchmark auto-run skipped: {error}")


def _maybe_run_conformance_backtest() -> None:
    try:
        from benchmark.conformance.runner import maybe_auto_run_conformance_backtest

        result = maybe_auto_run_conformance_backtest()
        if result and result.get("status") == "OK":
            print(f"Conformance backtest auto-run complete: {result.get('run_id')}")
    except Exception as error:
        print(f"Conformance backtest auto-run skipped: {error}")


def _maybe_run_evolution_memory() -> None:
    try:
        from benchmark.memory.runner import maybe_auto_run_evolution

        result = maybe_auto_run_evolution()
        if result and result.get("status") == "OK":
            print(f"Cognition evolution cycle complete: {result.get('run_id')}")
    except Exception as error:
        print(f"Cognition evolution cycle skipped: {error}")


def run_forever() -> None:
    """Run canonical pipeline loop."""

    print()
    print("BTC-ML CANONICAL RUNTIME")
    print()

    while True:
        run_once()
        _maybe_run_stage1_benchmark()
        _maybe_run_stage2_benchmark()
        _maybe_run_integrated_benchmark()
        _maybe_run_conformance_backtest()
        _maybe_run_evolution_memory()
        time.sleep(RUNTIME_LOOP_DELAY)
