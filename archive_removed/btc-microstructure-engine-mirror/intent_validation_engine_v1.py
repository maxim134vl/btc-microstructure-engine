import pandas as pd
import numpy as np

print("\nINTENT VALIDATION ENGINE STARTED\n")

# =====================================
# LOAD INTERACTIONS
# =====================================

interactions = pd.read_parquet(
    "flow_liquidity_interaction_memory.parquet"
)

# =====================================
# LOAD FEED
# =====================================

feed = pd.read_parquet(
    "live_market_feed.parquet"
)

feed = feed.sort_values(
    "timestamp"
)

feed = feed.drop_duplicates(
    subset=["timestamp"],
    keep="last"
)

feed = feed.reset_index(
    drop=True
)

# =====================================
# FEED MAP
# =====================================

feed_map = {}

for i in range(len(feed)):

    row = feed.iloc[i]

    feed_map[
        row["timestamp"]
    ] = i

# =====================================
# STORAGE
# =====================================

validation_rows = []

# =====================================
# LOOP
# =====================================

lookforward = 4

for _, row in interactions.iterrows():

    timestamp = row["timestamp"]

    interaction_type = row[
        "interaction_type"
    ]

    # =====================================
    # SKIP NEUTRAL
    # =====================================

    if interaction_type == "neutral":

        continue

    # =====================================
    # TIMESTAMP EXISTS
    # =====================================

    if timestamp not in feed_map:

        continue

    current_index = feed_map[
        timestamp
    ]

    future_index = (
        current_index
        +
        lookforward
    )

    if future_index >= len(feed):

        continue

    # =====================================
    # CURRENT PRICE
    # =====================================

    current_close = float(

        feed.iloc[
            current_index
        ]["close"]

    )

    # =====================================
    # FUTURE PRICE
    # =====================================

    future_close = float(

        feed.iloc[
            future_index
        ]["close"]

    )

    future_move = (

        future_close
        -
        current_close

    )

    # =====================================
    # OUTCOME
    # =====================================

    outcome = "neutral"

    # compression

    if (

        interaction_type
        ==
        "compression_inside_liquidity"

    ):

        if abs(future_move) > 250:

            outcome = (
                "expansion_resolved"
            )

    # failed breakout

    elif (

        interaction_type
        ==
        "failed_breakout_behavior"

    ):

        if abs(future_move) < 100:

            outcome = (
                "rejection_confirmed"
            )

    # exhaustion

    elif (

        interaction_type
        ==
        "exhaustion_at_liquidity"

    ):

        if abs(future_move) > 150:

            outcome = (
                "rotation_confirmed"
            )

    # distribution

    elif (

        interaction_type
        ==
        "expansion_into_distribution"

    ):

        if future_move < -150:

            outcome = (
                "distribution_rejection"
            )

    # =====================================
    # SAVE
    # =====================================

    validation_rows.append({

        "timestamp":
            timestamp,

        "interaction_type":
            interaction_type,

        "future_move":
            round(
                future_move,
                2
            ),

        "outcome":
            outcome

    })

# =====================================
# BUILD DF
# =====================================

validation_df = pd.DataFrame(
    validation_rows
)

# =====================================
# SAVE
# =====================================

validation_df.to_parquet(

    "intent_validation_memory.parquet",

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("OUTCOME DISTRIBUTION")

print("=" * 50)

print()

print(

    validation_df[
        "outcome"
    ].value_counts()

)

print()

print(

    validation_df.tail(40)

)

print()

print("MEMORY SAVED:")

print(
    "intent_validation_memory.parquet"
)

print()
