import pandas as pd
import numpy as np

from storage.path_registry import resolve_read, resolve_write

print("\nHTF STRUCTURE ENGINE STARTED\n")

# =====================================
# LOAD FEED
# =====================================

feed = pd.read_parquet(
    resolve_read("live_market_feed.parquet")
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
# BUILD HTF
# =====================================

aggregation = 4

htf_rows = []

# =====================================
# LOOP
# =====================================

for i in range(

    aggregation,

    len(feed)

):

    window = feed.iloc[

        i - aggregation : i

    ]

    timestamp = window.iloc[-1][
        "timestamp"
    ]

    open_price = float(

        window.iloc[0]["open"]

    )

    high_price = float(

        window["high"].max()

    )

    low_price = float(

        window["low"].min()

    )

    close_price = float(

        window.iloc[-1]["close"]

    )

    volume = float(

        window["volume"].sum()

    )

    # =====================================
    # HTF FEATURES
    # =====================================

    spread = (
        high_price
        -
        low_price
    )

    body = abs(
        close_price
        -
        open_price
    )

    direction = "neutral"

    if close_price > open_price:

        direction = "bullish"

    elif close_price < open_price:

        direction = "bearish"

    # =====================================
    # STRUCTURE
    # =====================================

    structure = "balanced"

    body_ratio = (
        body / spread
    ) if spread > 0 else 0

    if body_ratio > 0.7:

        structure = (
            "directional_expansion"
        )

    elif body_ratio < 0.3:

        structure = (
            "compression_structure"
        )

    # =====================================
    # SAVE
    # =====================================

    htf_rows.append({

        "timestamp":
            timestamp,

        "htf_open":
            open_price,

        "htf_high":
            high_price,

        "htf_low":
            low_price,

        "htf_close":
            close_price,

        "htf_volume":
            volume,

        "htf_spread":
            spread,

        "htf_body":
            body,

        "htf_direction":
            direction,

        "htf_structure":
            structure

    })

# =====================================
# BUILD DF
# =====================================

htf_df = pd.DataFrame(
    htf_rows
)

# =====================================
# SAVE
# =====================================

htf_df.to_parquet(

    resolve_write("htf_structure_memory.parquet"),

    index=False

)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("HTF STRUCTURE DISTRIBUTION")

print("=" * 50)

print()

print(

    htf_df[
        "htf_structure"
    ].value_counts()

)

print()

print(

    htf_df.tail(40)

)

print()

print("MEMORY SAVED:")

print(
    "htf_structure_memory.parquet"
)

print()
