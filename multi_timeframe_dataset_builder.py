import pandas as pd
import numpy as np
from auction_climax_engine_v1 import process_auction_climax

def aggregate_behavioral_timeframe(
    dataset,
    timeframe
):

    timeframe_map = {

        "M30": "30min",

        "H1": "1h",

        "H4": "4h",

        "D1": "1D"

    }

    dataset["timestamp"] = pd.to_datetime(
        dataset["timestamp"]
    )

    dataset = dataset.set_index(
        "timestamp"
    )

    aggregated = dataset.resample(
        timeframe_map[timeframe]
    ).agg({

        "open": "first",

        "high": "max",

        "low": "min",

        "close": "last",

        "volume": "sum",

        "delta": "sum"

    })

    aggregated = aggregated.dropna()

    aggregated = aggregated.reset_index()

    # =====================================
    # REBUILD BEHAVIORAL FEATURES
    # =====================================

    aggregated[
        "spread"
    ] = (

        aggregated["high"]
        -
        aggregated["low"]

    )

    aggregated[
        "body"
    ] = (

        aggregated["close"]
        -
        aggregated["open"]

    ).abs()

    aggregated[
        "upper_wick"
    ] = (

        aggregated["high"]
        -
        aggregated[
            [
                "open",
                "close"
            ]
        ].max(axis=1)

    )

    aggregated[
        "lower_wick"
    ] = (

        aggregated[
            [
                "open",
                "close"
            ]
        ].min(axis=1)

        -
        aggregated["low"]

    )

    aggregated[
        "candle_type"
    ] = np.where(

        aggregated["close"]
        >=
        aggregated["open"],

        "bullish",

        "bearish"

    )

    return aggregated

dataset = pd.read_parquet(
    "research_master_dataset.parquet"
)

# =====================================
# M15
# =====================================

m15_result = process_auction_climax(
    dataset=dataset.copy(),
    timeframe="M15"
)

# =====================================
# M30
# =====================================

m30_dataset = aggregate_behavioral_timeframe(
    dataset.copy(),
    "M30"
)

m30_result = process_auction_climax(
    dataset=m30_dataset,
    timeframe="M30"
)

# =====================================
# H1
# =====================================

h1_dataset = aggregate_behavioral_timeframe(
    dataset.copy(),
    "H1"
)

h1_result = process_auction_climax(
    dataset=h1_dataset,
    timeframe="H1"
)

# =====================================
# H4
# =====================================

h4_dataset = aggregate_behavioral_timeframe(
    dataset.copy(),
    "H4"
)

h4_result = process_auction_climax(
    dataset=h4_dataset,
    timeframe="H4"
)

# =====================================
# OUTPUT
# =====================================

print()
print("M15 EVENTS")
print()

print(
    m15_result[
        "auction_states"
    ][[
        "timestamp",
        "auction_event_type",
        "event_strength"
    ]].tail(10)
)

print()
print("M30 EVENTS")
print()

print(
    m30_result[
        "auction_states"
    ][[
        "timestamp",
        "auction_event_type",
        "event_strength"
    ]].tail(10)
)

print()
print("H1 EVENTS")
print()

print(
    h1_result[
        "auction_states"
    ][[
        "timestamp",
        "auction_event_type",
        "event_strength"
    ]].tail(10)
)

print()
print("H4 EVENTS")
print()

print(
    h4_result[
        "auction_states"
    ][[
        "timestamp",
        "auction_event_type",
        "event_strength"
    ]].tail(10)
)
