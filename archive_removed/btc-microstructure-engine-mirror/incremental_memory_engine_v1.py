import pandas as pd
import numpy as np
import os

print("\nINCREMENTAL MEMORY ENGINE STARTED\n")

# =====================================
# MEMORY FILES
# =====================================

LIVE_FILE = "live_stream_memory.parquet"

STATE_FILE = "engine_state.parquet"

# =====================================
# LOAD LIVE MEMORY
# =====================================

live_df = pd.read_parquet(
    LIVE_FILE
)

live_df = live_df.sort_values(
    "timestamp"
)

# =====================================
# LOAD ENGINE STATE
# =====================================

if os.path.exists(STATE_FILE):

    state_df = pd.read_parquet(
        STATE_FILE
    )

    last_processed = state_df.iloc[-1][
        "last_timestamp"
    ]

    print(
        f"LAST PROCESSED: {last_processed}"
    )

else:

    last_processed = None

    print(
        "NO PREVIOUS ENGINE STATE"
    )

# =====================================
# FILTER NEW DATA
# =====================================

if last_processed is not None:

    new_data = live_df.loc[
        live_df["timestamp"]
        >
        last_processed
    ].copy()

else:

    new_data = live_df.tail(1).copy()

# =====================================
# CHECK
# =====================================

if len(new_data) == 0:

    print()

    print("NO NEW CANDLES")

    print()

    exit()

# =====================================
# PROCESS NEW CANDLES
# =====================================

incremental_memory = []

important_updates = []

for i in range(len(new_data)):

    row = new_data.iloc[i]

    timestamp = row["timestamp"]

    # =====================================
    # BUILD STATE
    # =====================================

    state = {

        "timestamp": timestamp,

        "intent": row["intent"],

        "intent_strength": row[
            "intent_strength"
        ],

        "market_condition": row[
            "market_condition"
        ],

        "persistent_phase": row[
            "persistent_phase"
        ],

        "maturity_score": row[
            "maturity_score"
        ],

        "instability_score": row[
            "instability_score"
        ]

    }

    # =====================================
    # IMPORTANT UPDATE
    # =====================================

    important = False

    if (

        row["intent_strength"]

        > 1

    ):

        important = True

    if (

        row["instability_score"]

        > 0.5

    ):

        important = True

    if important:

        important_updates.append(
            state
        )

    # =====================================
    # APPEND MEMORY
    # =====================================

    incremental_memory.append(
        state
    )

    # =====================================
    # LIVE OUTPUT
    # =====================================

    print("=" * 50)

    print(f"NEW CANDLE: {timestamp}")

    print()

    print(
        f"INTENT: {state['intent']}"
    )

    print(
        f"MARKET: {state['market_condition']}"
    )

    print(
        f"PHASE: {state['persistent_phase']}"
    )

    print()

    print(
        f"INTENT STRENGTH: {round(state['intent_strength'], 4)}"
    )

    print(
        f"MATURITY: {round(state['maturity_score'], 4)}"
    )

    print(
        f"INSTABILITY: {round(state['instability_score'], 4)}"
    )

    print()

# =====================================
# SAVE NEW ENGINE STATE
# =====================================

new_state = pd.DataFrame([{

    "last_timestamp":

    incremental_memory[-1]["timestamp"]

}])

new_state.to_parquet(
    STATE_FILE
)

# =====================================
# SAVE INCREMENTAL MEMORY
# =====================================

incremental_df = pd.DataFrame(
    incremental_memory
)

incremental_df.to_parquet(
    "incremental_memory.parquet"
)

# =====================================
# SAVE IMPORTANT UPDATES
# =====================================

important_df = pd.DataFrame(
    important_updates
)

important_df.to_parquet(
    "important_incremental_events.parquet"
)

# =====================================
# FINAL SUMMARY
# =====================================

print("=" * 50)

print("INCREMENTAL UPDATE COMPLETE")

print("=" * 50)

print()

print(
    f"NEW STATES: {len(incremental_df)}"
)

print(
    f"IMPORTANT EVENTS: {len(important_df)}"
)

print()

print("MEMORIES SAVED:")

print(
    "incremental_memory.parquet"
)

print(
    "important_incremental_events.parquet"
)

print(
    "engine_state.parquet"
)

print()
