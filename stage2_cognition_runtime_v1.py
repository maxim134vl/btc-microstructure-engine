import pandas as pd

from auction_climax_engine_v1 import process_auction_climax
from multi_timeframe_dataset_builder import aggregate_behavioral_timeframe
from multi_timeframe_synthesis_engine import synthesize_multi_timeframe_behavior
from parquet_utils import atomic_parquet_write
from runtime_lineage import apply_lineage_metadata
from state_manager_v1 import STATE, refresh_state

SYNTHESIS_OUTPUT_PATH = "multi_timeframe_synthesis.parquet"
RUNTIME_COGNITION_MEMORY_PATH = "runtime_cognition_memory.parquet"
CANDLE_STRUCTURE_SOURCE = "candle_structure_memory.parquet"

COGNITION_COLUMNS = [
    "timestamp",
    "synthesis_state",
    "trigger_event",
    "persistence",
    "persistence_score",
    "structural_rank",
    "alignment_score",
    "location_bias",
]

STAGE2_ENGINE = "stage2_cognition_runtime_v1.py"


def build_stage2_synthesis(base_dataset: pd.DataFrame) -> pd.DataFrame:
    """Run Stage 2 climax + MTF synthesis on the provided dataset."""

    m15_dataset = base_dataset.copy()

    m30_dataset = aggregate_behavioral_timeframe(
        base_dataset.copy(),
        "M30",
    )

    h1_dataset = aggregate_behavioral_timeframe(
        base_dataset.copy(),
        "H1",
    )

    h4_dataset = aggregate_behavioral_timeframe(
        base_dataset.copy(),
        "H4",
    )

    m15_result = process_auction_climax(
        dataset=m15_dataset,
        timeframe="M15",
    )

    m30_result = process_auction_climax(
        dataset=m30_dataset,
        timeframe="M30",
    )

    h1_result = process_auction_climax(
        dataset=h1_dataset,
        timeframe="H1",
    )

    h4_result = process_auction_climax(
        dataset=h4_dataset,
        timeframe="H4",
    )

    return synthesize_multi_timeframe_behavior(
        m15_states=m15_result["auction_states"],
        m30_states=m30_result["auction_states"],
        h1_states=h1_result["auction_states"],
        h4_states=h4_result["auction_states"],
    )


def export_runtime_cognition_memory(
    synthesis_output: pd.DataFrame,
) -> pd.DataFrame:
    """Export cognition memory frame (same columns as research batch export)."""

    runtime_cognition_memory = synthesis_output[
        COGNITION_COLUMNS
    ].copy()

    runtime_cognition_memory = (
        runtime_cognition_memory
        .dropna(subset=["synthesis_state"])
        .reset_index(drop=True)
    )

    return runtime_cognition_memory


def run() -> None:
    print()
    print("STAGE 2 COGNITION RUNTIME")
    print()

    refresh_state()

    base_dataset = STATE["candle_structure"].copy()

    if len(base_dataset) == 0:
        print("NO CANDLE STRUCTURE DATA")
        print()
        return

    synthesis_output = build_stage2_synthesis(base_dataset)

    synthesis_output = apply_lineage_metadata(
        synthesis_output,
        engine_name=STAGE2_ENGINE,
        source_parquet=CANDLE_STRUCTURE_SOURCE,
        dependency_chain=[
            CANDLE_STRUCTURE_SOURCE,
            STAGE2_ENGINE,
            SYNTHESIS_OUTPUT_PATH,
        ],
    )

    atomic_parquet_write(
        synthesis_output,
        SYNTHESIS_OUTPUT_PATH,
    )

    runtime_cognition_memory = export_runtime_cognition_memory(
        synthesis_output
    )

    runtime_cognition_memory = apply_lineage_metadata(
        runtime_cognition_memory,
        engine_name=STAGE2_ENGINE,
        source_parquet=SYNTHESIS_OUTPUT_PATH,
        dependency_chain=[
            CANDLE_STRUCTURE_SOURCE,
            STAGE2_ENGINE,
            SYNTHESIS_OUTPUT_PATH,
            RUNTIME_COGNITION_MEMORY_PATH,
        ],
    )

    atomic_parquet_write(
        runtime_cognition_memory,
        RUNTIME_COGNITION_MEMORY_PATH,
    )

    print(
        "SYNTHESIS ROWS:",
        len(synthesis_output),
    )

    print(
        "COGNITION ROWS:",
        len(runtime_cognition_memory),
    )

    if len(runtime_cognition_memory) > 0:
        latest = runtime_cognition_memory.iloc[-1]
        print(
            "LATEST COGNITION TIMESTAMP:",
            latest["timestamp"],
        )
        print(
            "LATEST SYNTHESIS STATE:",
            latest["synthesis_state"],
        )

    print()


if __name__ == "__main__":
    run()
