import pandas as pd
import numpy as np
import time
from datetime import datetime

print("\nREALTIME STREAMING ENGINE STARTED\n")

# =====================================
# LOAD MEMORIES
# =====================================

intent_df = pd.read_parquet(
    "intent_inference_memory.parquet"
)

causal_df = pd.read_parquet(
    "causal_auction_memory.parquet"
)

path_df = pd.read_parquet(
    "auction_path_dependency_memory.parquet"
)

temporal_df = pd.read_parquet(
    "temporal_persistence_memory.parquet"
)

# =====================================
# LIVE MEMORY
# =====================================

live_memory = []

# =====================================
# IMPORTANT EVENT STORAGE
# =====================================

important_events = []

# =====================================
# STREAM LOOP
# =====================================

for i in range(len(intent_df)):

    intent_row = intent_df.iloc[i]

    timestamp = intent_row["timestamp"]

    causal_row = causal_df.iloc[i]

    path_row = path_df.iloc[i]

    temporal_row = temporal_df.iloc[i]

    # =====================================
    # BUILD LIVE STATE
    # =====================================

    live_state = {

        "timestamp": timestamp,

        "intent": intent_row[
            "inferred_intent"
        ],

        "intent_strength": intent_row[
            "intent_strength"
        ],

        "causal_condition": causal_row[
            "causal_condition"
        ],

        "market_condition": path_row[
            "market_condition"
        ],

        "persistent_phase": temporal_row[
            "dominant_persistent_phase"
        ],

        "maturity_score": temporal_row[
            "maturity_score"
        ],

        "instability_score": temporal_row[
            "instability_score"
        ]

    }

    # =====================================
    # IMPORTANT EVENT DETECTION
    # =====================================

    important = False

    if (

        live_state[
            "intent_strength"
        ] > 1

    ):

        important = True

    if (

        live_state[
            "instability_score"
        ] > 0.6

    ):

        important = True

    if (

        "liquidity"

        in

        live_state[
            "intent"
        ]

    ):

        important = True

    # =====================================
    # STORE IMPORTANT EVENT
    # =====================================

    if important:

        important_events.append(
            live_state
        )

    # =====================================
    # LIVE MEMORY UPDATE
    # =====================================

    live_memory.append(
        live_state
    )

    # =====================================
    # MEMORY COMPRESSION
    # =====================================

    if len(live_memory) > 500:

        live_memory = live_memory[-250:]

    # =====================================
    # LIVE OUTPUT
    # =====================================

    print("=" * 50)

    print(f"TIME: {timestamp}")

    print()

    print(
        f"INTENT: {live_state['intent']}"
    )

    print(
        f"CAUSAL: {live_state['causal_condition']}"
    )

    print(
        f"MARKET: {live_state['market_condition']}"
    )

    print(
        f"PHASE: {live_state['persistent_phase']}"
    )

    print()

    print(
        f"INTENT STRENGTH: {round(live_state['intent_strength'], 4)}"
    )

    print(
        f"MATURITY: {round(live_state['maturity_score'], 4)}"
    )

    print(
        f"INSTABILITY: {round(live_state['instability_score'], 4)}"
    )

    print()

    print(
        f"LIVE MEMORY SIZE: {len(live_memory)}"
    )

    print(
        f"IMPORTANT EVENTS: {len(important_events)}"
    )

    print()

    # =====================================
    # SIMULATED STREAM DELAY
    # =====================================

    time.sleep(0.05)

# =====================================
# SAVE LIVE MEMORY
# =====================================

live_df = pd.DataFrame(
    live_memory
)

important_df = pd.DataFrame(
    important_events
)

live_df.to_parquet(
    "live_stream_memory.parquet"
)

important_df.to_parquet(
    "important_event_memory.parquet"
)

# =====================================
# FINAL SUMMARY
# =====================================

print("=" * 50)

print("STREAM COMPLETE")

print("=" * 50)

print()

print(
    f"TOTAL LIVE STATES: {len(live_df)}"
)

print(
    f"IMPORTANT EVENTS: {len(important_df)}"
)

print()

print("MEMORIES SAVED:")

print(
    "live_stream_memory.parquet"
)

print(
    "important_event_memory.parquet"
)

print()
