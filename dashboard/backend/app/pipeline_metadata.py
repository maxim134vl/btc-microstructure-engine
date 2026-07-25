"""Pipeline metadata for dashboard/ops tooling.

Patch 4.2: active engine list is loaded from canonical runtime
`src/btc_ml/runtime/pipeline.py` (AST parse — no writer side effects).
Phantom engines are retained only as LEGACY metadata, not in CANONICAL_PIPELINE.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Literal

ProcessType = Literal["in-process", "subprocess"]

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_PIPELINE_PATH = REPO_ROOT / "src" / "btc_ml" / "runtime" / "pipeline.py"

PHANTOM_ENGINES: tuple[str, ...] = (
    "volume_localization_engine_v1.py",
    "market_state_engine_v1.py",
    "trading_state_engine_v1.py",
    "shadow_inference_engine_v1.py",
    "trading_state_validation_engine_v1.py",
    "economic_validation_engine_v1.py",
)


def _load_runtime_canonical_pipeline() -> tuple[str, ...]:
    tree = ast.parse(RUNTIME_PIPELINE_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CANONICAL_PIPELINE":
                    return tuple(ast.literal_eval(node.value))
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "CANONICAL_PIPELINE":
                return tuple(ast.literal_eval(node.value))
    raise RuntimeError(f"CANONICAL_PIPELINE not found in {RUNTIME_PIPELINE_PATH}")


CANONICAL_PIPELINE: tuple[str, ...] = _load_runtime_canonical_pipeline()
EXPECTED_CANONICAL_PIPELINE_STEP_COUNT = len(CANONICAL_PIPELINE)

# Mirrors engine_registry.ENGINES keys — in-process execution only.
IN_PROCESS_ENGINES: frozenset[str] = frozenset(
    {
        "auction_convergence_engine_v1.py",
        "auction_reinforcement_engine_v1.py",
        "probabilistic_auction_engine_v1.py",
        "auction_context_arbitration_engine_v1.py",
        "adaptive_meta_cognition_engine_v1.py",
        "stage2_cognition_runtime_v1.py",
        "intermediate_cognition_engine_v1.py",
        "state_transition_engine_v1.py",
        "mtf_availability_runtime_engine_v1.py",
    }
)

DEPENDENCIES: dict[str, list[str]] = {
    "volume_response_engine_v1.py": [
        "candle_structure_memory.parquet",
        "volume_classification_memory.parquet",
    ],
    "auction_synthesis_engine_v1.py": [
        "volume_response_state.parquet",
        "htf_structure_memory.parquet",
        "htf_ltf_context_memory.parquet",
    ],
    "stage2_cognition_runtime_v1.py": [
        "candle_structure_memory.parquet",
    ],
    "runtime_cognition_engine_v1.py": [
        "runtime_cognition_memory.parquet",
    ],
    "intermediate_cognition_engine_v1.py": [
        "candle_structure_memory.parquet",
        "runtime_cognition_memory.parquet",
    ],
    "probabilistic_auction_engine_v1.py": [
        "auction_synthesis_memory.parquet",
        "auction_reinforcement_memory.parquet",
    ],
    "auction_context_arbitration_engine_v1.py": [
        "candle_structure_memory.parquet",
        "volume_response_state.parquet",
        "auction_convergence_memory.parquet",
    ],
    "state_transition_engine_v1.py": [
        "auction_synthesis_memory.parquet",
        "probabilistic_auction_memory.parquet",
    ],
    "auction_decay_engine_v1.py": [
        "auction_convergence_memory.parquet",
        "auction_reinforcement_memory.parquet",
    ],
    "mtf_availability_runtime_engine_v1.py": [
        "candle_structure_memory.parquet",
    ],
}

# Dashboard display metadata — phase labels for pipeline steps.
ENGINE_DISPLAY: dict[str, dict[str, str]] = {
    "candle_structure_engine_v1.py": {"short_name": "candle_structure", "phase": "perception"},
    "volume_classification_engine_v1.py": {"short_name": "volume_class", "phase": "perception"},
    "schema_validation_engine_v1.py": {"short_name": "schema_validation", "phase": "perception"},
    "behavioral_sequence_memory_v1.py": {"short_name": "behavioral_seq", "phase": "perception"},
    "behavioral_volume_observer_v1.py": {"short_name": "volume_observer", "phase": "perception"},
    "microstructure_candle_engine_v1.py": {"short_name": "microstructure", "phase": "perception"},
    "volume_response_engine_v1.py": {"short_name": "volume_response", "phase": "perception"},
    "climactic_behavior_engine_v1.py": {"short_name": "climactic", "phase": "perception"},
    "auction_convergence_engine_v1.py": {"short_name": "convergence", "phase": "cognition"},
    "auction_synthesis_engine_v1.py": {"short_name": "synthesis", "phase": "cognition"},
    "stage2_cognition_runtime_v1.py": {"short_name": "stage2", "phase": "cognition"},
    "intermediate_cognition_engine_v1.py": {"short_name": "intermediate", "phase": "cognition"},
    "runtime_cognition_engine_v1.py": {"short_name": "runtime_cog", "phase": "cognition"},
    "auction_reinforcement_engine_v1.py": {"short_name": "reinforcement", "phase": "probabilistic"},
    "probabilistic_auction_engine_v1.py": {"short_name": "probabilistic", "phase": "probabilistic"},
    "auction_context_arbitration_engine_v1.py": {"short_name": "arbitration", "phase": "cognition"},
    "auction_decay_engine_v1.py": {"short_name": "decay", "phase": "probabilistic"},
    "state_transition_engine_v1.py": {"short_name": "state_transition", "phase": "probabilistic"},
    "adaptive_meta_cognition_engine_v1.py": {"short_name": "meta_cognition", "phase": "cognition"},
    "mtf_availability_runtime_engine_v1.py": {"short_name": "mtf_availability", "phase": "ops_read_model"},
    # Legacy phantom labels retained for audit/legacy UI only — not in CANONICAL_PIPELINE.
    "volume_localization_engine_v1.py": {"short_name": "volume_local", "phase": "legacy"},
    "market_state_engine_v1.py": {"short_name": "market_state", "phase": "legacy"},
    "trading_state_engine_v1.py": {"short_name": "trading_state", "phase": "legacy"},
    "shadow_inference_engine_v1.py": {"short_name": "shadow_infer", "phase": "legacy"},
    "trading_state_validation_engine_v1.py": {"short_name": "ts_validation", "phase": "legacy"},
    "economic_validation_engine_v1.py": {"short_name": "econ_validation", "phase": "legacy"},
}


def engine_process_type(engine: str) -> ProcessType:
    return "in-process" if engine in IN_PROCESS_ENGINES else "subprocess"


def engine_short_name(engine: str) -> str:
    meta = ENGINE_DISPLAY.get(engine)
    if meta:
        return meta["short_name"]
    return engine.replace("_engine_v1.py", "").replace("_v1.py", "")


def engine_phase(engine: str) -> str:
    meta = ENGINE_DISPLAY.get(engine)
    return meta["phase"] if meta else "runtime"
