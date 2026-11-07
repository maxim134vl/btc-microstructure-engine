import pandas as pd
import numpy as np

print("\nEVENT RELATIONSHIP ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

df = pd.read_parquet(
    "behavioral_scoring_memory.parquet"
)

df = df.dropna().copy()

# =====================================
# STORAGE
# =====================================

events = []

relationships = []

# =====================================
# FIND CORE EVENTS
# =====================================

for i in range(len(df)):

    row = df.iloc[i]

    timestamp = df.index[i]

    # =====================================
    # STOPPING EVENT
    # =====================================

    stopping_condition = (

        row["volume_class"] == "stopping"

        and

        row["lower_rejection_score"] > 0.4

        and

        row["spread_score"] > 1

    )

    if stopping_condition:

        event = {

            "event_type": "stopping",

            "timestamp": timestamp,

            "zone_low": row["low"],

            "zone_high": min(
                row["open"],
                row["close"]
            ),

            "close": row["close"],

            "volume_score": row["volume_score"],

            "spread_score": row["spread_score"]

        }

        events.append(event)

    # =====================================
    # CLIMAX EVENT
    # =====================================

    climax_condition = (

        row["volume_class"] == "climax"

        and

        row["spread_score"] > 1.5

    )

    if climax_condition:

        event = {

            "event_type": "climax",

            "timestamp": timestamp,

            "zone_low": row["low"],

            "zone_high": row["high"],

            "close": row["close"]

        }

        events.append(event)

# =====================================
# RELATIONSHIP ANALYSIS
# =====================================

for event in events:

    future_df = df.loc[
        df.index > event["timestamp"]
    ].head(10)

    for future_index, future_row in future_df.iterrows():

        # =====================================
        # REVISIT
        # =====================================

        revisit = (

            future_row["low"]

            <=

            event["zone_high"]

            and

            future_row["low"]

            >=

            event["zone_low"]

        )

        if not revisit:

            continue

        # =====================================
        # DEFENSE
        # =====================================

        successful_defense = (

            future_row["close_position"] > 0.6

            and

            future_row["lower_rejection_score"] > 0.2

        )

        # =====================================
        # FAILED DEFENSE
        # =====================================

        failed_defense = (

            future_row["close"]

            <

            event["zone_low"]

        )

        # =====================================
        # LOW PARTICIPATION TEST
        # =====================================

        low_volume_test = (

            future_row["volume_class"]

            ==

            "low_small"

        )

        # =====================================
        # BUILD RELATIONSHIP
        # =====================================

        relationship = {

            "origin_event": event["event_type"],

            "origin_timestamp": event["timestamp"],

            "test_timestamp": future_index,

            "revisit": revisit,

            "successful_defense": successful_defense,

            "failed_defense": failed_defense,

            "low_volume_test": low_volume_test,

            "zone_low": event["zone_low"],

            "zone_high": event["zone_high"]

        }

        relationships.append(
            relationship
        )

# =====================================
# SAVE
# =====================================

events_df = pd.DataFrame(events)

relationships_df = pd.DataFrame(
    relationships
)

events_df.to_parquet(
    "behavioral_events_memory.parquet"
)

relationships_df.to_parquet(
    "behavioral_relationships_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("EVENTS FOUND")

print("=" * 50)

print()

if len(events_df) > 0:

    print(events_df.tail())

else:

    print("NO EVENTS FOUND")

print()

print("=" * 50)

print("RELATIONSHIPS FOUND")

print("=" * 50)

print()

if len(relationships_df) > 0:

    print(relationships_df.tail(20))

else:

    print("NO RELATIONSHIPS FOUND")

print()

print("MEMORY SAVED:")

print(
    "behavioral_events_memory.parquet"
)

print(
    "behavioral_relationships_memory.parquet"
)

print()
