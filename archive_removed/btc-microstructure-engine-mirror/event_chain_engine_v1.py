import pandas as pd
import numpy as np

print("\nEVENT CHAIN ENGINE STARTED\n")

# =====================================
# LOAD DATA
# =====================================

zones = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
)

tests = pd.read_parquet(
    "test_recognition_memory.parquet"
)

geometry = pd.read_parquet(
    "candle_geometry_v2_memory.parquet"
)

# =====================================
# STORAGE
# =====================================

chains = []

chain_id = 0

active_chain = None

# =====================================
# LOOP
# =====================================

for i in range(len(zones)):

    zone = zones.iloc[i]

    timestamp = zone["timestamp"]

    behavior = zone["behavior"]

    zone_low = zone["zone_low"]

    zone_high = zone["zone_high"]

    # =====================================
    # MATCH TEST
    # =====================================

    related_test = tests[

        tests["timestamp"]
        ==
        timestamp

    ]

    successful = False
    failed = False

    if len(related_test) > 0:

        successful = bool(
            related_test[
                "successful_test"
            ].iloc[0]
        )

        failed = bool(
            related_test[
                "failed_test"
            ].iloc[0]
        )

    # =====================================
    # EVENT TYPE
    # =====================================

    event_type = "neutral"

    if behavior == "localized_absorption":

        event_type = "absorption"

    elif behavior == "localized_distribution":

        event_type = "distribution"

    # successful defense

    if successful:

        event_type = (
            "successful_test"
        )

    # failed defense

    if failed:

        event_type = (
            "failed_test"
        )

    # =====================================
    # FIRST CHAIN
    # =====================================

    if active_chain is None:

        active_chain = {

            "chain_id": chain_id,

            "start_time": timestamp,

            "end_time": timestamp,

            "events": [event_type],

            "zone_low": zone_low,

            "zone_high": zone_high,

            "strength": 1

        }

        continue

    # =====================================
    # DISTANCE
    # =====================================

    cluster_overlap = (

        zone_low
        <= active_chain["zone_high"]

        and

        zone_high
        >= active_chain["zone_low"]

    )

    # =====================================
    # CONTINUE CHAIN
    # =====================================

    if cluster_overlap:

        active_chain["events"].append(
            event_type
        )

        active_chain["end_time"] = (
            timestamp
        )

        active_chain["zone_low"] = min(

            active_chain["zone_low"],
            zone_low

        )

        active_chain["zone_high"] = max(

            active_chain["zone_high"],
            zone_high

        )

        active_chain["strength"] += 1

    # =====================================
    # CLOSE CHAIN
    # =====================================

    else:

        chains.append(
            active_chain
        )

        chain_id += 1

        active_chain = {

            "chain_id": chain_id,

            "start_time": timestamp,

            "end_time": timestamp,

            "events": [event_type],

            "zone_low": zone_low,

            "zone_high": zone_high,

            "strength": 1

        }

# =====================================
# FINAL SAVE
# =====================================

if active_chain is not None:

    chains.append(
        active_chain
    )

# =====================================
# BUILD DF
# =====================================

chains_df = pd.DataFrame(
    chains
)

# =====================================
# CHAIN CLASSIFICATION
# =====================================

chain_types = []

for _, row in chains_df.iterrows():

    events = row["events"]

    chain_type = "neutral"

    # defended accumulation

    if (

        "absorption" in events

        and

        "successful_test" in events

    ):

        chain_type = (
            "defended_accumulation"
        )

    # weakening structure

    elif (

        "failed_test" in events

        and

        len(events) >= 3

    ):

        chain_type = (
            "weakening_structure"
        )

    # defended distribution

    elif (

        "distribution" in events

        and

        "successful_test" in events

    ):

        chain_type = (
            "defended_distribution"
        )

    chain_types.append(
        chain_type
    )

chains_df["chain_type"] = chain_types

# =====================================
# SAVE
# =====================================

chains_df.to_parquet(
    "event_chains_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("EVENT CHAIN DEBUG")

print("=" * 50)

print()

print(
    chains_df[
        [

            "chain_id",

            "strength",

            "chain_type",

            "events"

        ]

    ]
    .tail(40)

)

print()

print("CHAIN DISTRIBUTION:")

print(
    chains_df[
        "chain_type"
    ].value_counts()
)

print()

print("MEMORY SAVED:")

print(
    "event_chains_memory.parquet"
)

print()
