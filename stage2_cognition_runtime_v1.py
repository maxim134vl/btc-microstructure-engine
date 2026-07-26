import pandas as pd

from auction_climax_engine_v1 import process_auction_climax
from multi_timeframe_dataset_builder import aggregate_behavioral_timeframe
from multi_timeframe_synthesis_engine import synthesize_multi_timeframe_behavior
from parquet_utils import atomic_parquet_write, safe_read_parquet
from runtime_lineage import apply_lineage_metadata
from state_manager_v1 import STATE, refresh_state

SYNTHESIS_OUTPUT_PATH = "multi_timeframe_synthesis.parquet"
RUNTIME_COGNITION_MEMORY_PATH = "runtime_cognition_memory.parquet"
CANDLE_STRUCTURE_SOURCE = "candle_structure_memory.parquet"
AUCTION_SYNTHESIS_SOURCE = "auction_synthesis_memory.parquet"

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

AUCTION_BRIDGE_COLUMNS = [
    "auction_state",
    "auction_event_timestamp",
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


def _prepare_auction_frame(auction_synthesis: pd.DataFrame | None) -> pd.DataFrame:
    if auction_synthesis is None or len(auction_synthesis) == 0:
        return pd.DataFrame(columns=["auction_event_timestamp", "auction_state"])
    if "timestamp" not in auction_synthesis.columns or "auction_state" not in auction_synthesis.columns:
        return pd.DataFrame(columns=["auction_event_timestamp", "auction_state"])
    frame = auction_synthesis[["timestamp", "auction_state"]].copy()
    frame["auction_event_timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.dropna(subset=["auction_event_timestamp"]).sort_values(
        "auction_event_timestamp"
    )
    return frame[["auction_event_timestamp", "auction_state"]].reset_index(drop=True)


def export_runtime_cognition_memory(
    synthesis_output: pd.DataFrame,
    candle_structure: pd.DataFrame | None = None,
    auction_synthesis: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build evaluation-time decision snapshots from event-sparse MTF + auction carry.

    multi_timeframe_synthesis remains event-sparse structural memory.
    runtime_cognition_memory becomes decision snapshots where:
      timestamp                 = evaluation bar (candle identity)
      lineage_event_timestamp   = climax/MTF event time (set by apply_lineage_metadata)
      auction_state / auction_event_timestamp = latest valid auction asof evaluation
    """

    if synthesis_output is None or len(synthesis_output) == 0:
        return pd.DataFrame(columns=COGNITION_COLUMNS + AUCTION_BRIDGE_COLUMNS)

    mtf = synthesis_output.dropna(subset=["synthesis_state"]).copy()
    if len(mtf) == 0:
        return pd.DataFrame(columns=COGNITION_COLUMNS + AUCTION_BRIDGE_COLUMNS)

    missing = [c for c in COGNITION_COLUMNS if c not in mtf.columns]
    if missing:
        raise ValueError(f"MTF synthesis missing required cognition columns: {missing}")

    mtf["mtf_event_timestamp"] = pd.to_datetime(mtf["timestamp"], utc=True)
    mtf = mtf.sort_values("mtf_event_timestamp").reset_index(drop=True)

    # Legacy path: no candle frame → keep prior event-sparse export semantics.
    if candle_structure is None or len(candle_structure) == 0 or "timestamp" not in candle_structure.columns:
        out = mtf[COGNITION_COLUMNS].copy().reset_index(drop=True)
        out["auction_state"] = pd.NA
        out["auction_event_timestamp"] = pd.NaT
        return out

    eval_frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(candle_structure["timestamp"], utc=True),
        }
    )
    eval_frame = (
        eval_frame.dropna(subset=["timestamp"])
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if len(eval_frame) == 0:
        return pd.DataFrame(columns=COGNITION_COLUMNS + AUCTION_BRIDGE_COLUMNS)

    mtf_for_asof = mtf[
        [
            "mtf_event_timestamp",
            "synthesis_state",
            "trigger_event",
            "persistence",
            "persistence_score",
            "structural_rank",
            "alignment_score",
            "location_bias",
        ]
    ].copy()

    merged = pd.merge_asof(
        eval_frame,
        mtf_for_asof,
        left_on="timestamp",
        right_on="mtf_event_timestamp",
        direction="backward",
    )
    merged = merged.dropna(subset=["synthesis_state"]).reset_index(drop=True)
    if len(merged) == 0:
        return pd.DataFrame(columns=COGNITION_COLUMNS + AUCTION_BRIDGE_COLUMNS)

    auction = _prepare_auction_frame(auction_synthesis)
    if len(auction) == 0:
        merged["auction_state"] = pd.NA
        merged["auction_event_timestamp"] = pd.NaT
    else:
        merged = pd.merge_asof(
            merged,
            auction,
            left_on="timestamp",
            right_on="auction_event_timestamp",
            direction="backward",
        )
        # Same-cycle wall-clock skew: auction_synthesis timestamps with utcnow
        # can land after the current M15 bar-open identity. Carry the latest
        # valid auction state onto the current evaluation tip only.
        latest_auc = auction.iloc[-1]
        tip_eval = merged["timestamp"].max()
        if pd.notna(latest_auc["auction_event_timestamp"]) and latest_auc[
            "auction_event_timestamp"
        ] > tip_eval:
            tip_mask = merged["timestamp"] == tip_eval
            merged.loc[tip_mask, "auction_state"] = latest_auc["auction_state"]
            merged.loc[tip_mask, "auction_event_timestamp"] = latest_auc[
                "auction_event_timestamp"
            ]

    # Temporarily place MTF event time in timestamp so lineage_event_timestamp
    # captures event time; caller restores evaluation timestamps afterward.
    out = merged[
        [
            "mtf_event_timestamp",
            "timestamp",
            "synthesis_state",
            "trigger_event",
            "persistence",
            "persistence_score",
            "structural_rank",
            "alignment_score",
            "location_bias",
            "auction_state",
            "auction_event_timestamp",
        ]
    ].copy()
    out = out.rename(
        columns={
            "timestamp": "evaluation_timestamp",
            "mtf_event_timestamp": "timestamp",
        }
    )
    return out.reset_index(drop=True)


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

    auction_synthesis = safe_read_parquet(AUCTION_SYNTHESIS_SOURCE)
    if len(auction_synthesis) == 0:
        print("AUCTION SYNTHESIS UNAVAILABLE — decision bridge omits auction state")

    runtime_cognition_memory = export_runtime_cognition_memory(
        synthesis_output,
        candle_structure=base_dataset,
        auction_synthesis=auction_synthesis,
    )

    if len(runtime_cognition_memory) == 0:
        print("NO RUNTIME COGNITION SNAPSHOTS")
        print()
        return

    evaluation_timestamps = runtime_cognition_memory["evaluation_timestamp"].copy()
    domain = runtime_cognition_memory.drop(columns=["evaluation_timestamp"])

    domain = apply_lineage_metadata(
        domain,
        engine_name=STAGE2_ENGINE,
        source_parquet=SYNTHESIS_OUTPUT_PATH,
        dependency_chain=[
            CANDLE_STRUCTURE_SOURCE,
            AUCTION_SYNTHESIS_SOURCE,
            STAGE2_ENGINE,
            SYNTHESIS_OUTPUT_PATH,
            RUNTIME_COGNITION_MEMORY_PATH,
        ],
        event_timestamp_col="timestamp",
    )
    # timestamp = evaluation bar; lineage_event_timestamp retains climax/MTF event time.
    domain["timestamp"] = pd.to_datetime(evaluation_timestamps, utc=True).to_numpy()

    atomic_parquet_write(
        domain,
        RUNTIME_COGNITION_MEMORY_PATH,
    )

    print(
        "SYNTHESIS ROWS:",
        len(synthesis_output),
    )

    print(
        "COGNITION ROWS:",
        len(domain),
    )

    if len(domain) > 0:
        latest = domain.iloc[-1]
        print(
            "LATEST COGNITION TIMESTAMP:",
            latest["timestamp"],
        )
        print(
            "LATEST SYNTHESIS STATE:",
            latest["synthesis_state"],
        )
        print(
            "LATEST LINEAGE EVENT TIMESTAMP:",
            latest.get("lineage_event_timestamp"),
        )
        print(
            "LATEST AUCTION STATE:",
            latest.get("auction_state"),
        )

    print()


if __name__ == "__main__":
    run()
