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

    # M15 input timestamps identify the opening of CLOSED 15-minute candles.
    # An HTF bar is available only after all its expected M15 candles exist.
    dataset = dataset.copy()
    dataset["timestamp"] = pd.to_datetime(dataset["timestamp"], errors="raise")
    if dataset["timestamp"].isna().any():
        raise ValueError("COG02_INVALID_M15_TIMESTAMP")
    dataset = dataset.sort_values("timestamp").set_index("timestamp")
    if dataset.index.has_duplicates:
        raise ValueError("COG02_DUPLICATE_M15_TIMESTAMP")

    period = pd.Timedelta(timeframe_map[timeframe])
    m15_period = pd.Timedelta(minutes=15)
    expected_m15 = int(period / m15_period)
    if expected_m15 * m15_period != period:
        raise ValueError("COG02_INVALID_HTF_DURATION")

    complete_buckets = []
    for bucket_open, bars in dataset.groupby(pd.Grouper(freq=timeframe_map[timeframe])):
        expected_index = pd.date_range(bucket_open, periods=expected_m15, freq="15min")
        if len(bars) == expected_m15 and bars.index.equals(expected_index):
            complete_buckets.append(bucket_open)

    aggregated = dataset.resample(timeframe_map[timeframe]).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "delta": "sum",
    })
    aggregated = aggregated.loc[aggregated.index.isin(complete_buckets)].dropna()
    if aggregated.empty:
        raise ValueError("COG02_NO_COMPLETE_HTF_BARS:" + timeframe)
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


if __name__ == "__main__":
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
