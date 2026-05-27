import pandas as pd

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# RELATIVE VOLUME
# =====================================

candles["relative_volume"] = (

    candles["volume"]

    /

    candles["volume"]
    .rolling(20)
    .mean()

)

# =====================================
# ABSORPTION FILTER
# =====================================

filtered = candles[

    (candles["relative_volume"] > 2.0)

    &

    (candles["close_position"] > 0.7)

].copy()

print()
print(
    "TOTAL ABSORPTION STATES:",
    len(filtered)
)

# =====================================
# HORIZONS
# =====================================

horizons = [
    5,
    10,
    20
]

# =====================================
# TEST
# =====================================

for horizon in horizons:

    results = []

    for _, row in filtered.iterrows():

        timestamp = pd.to_datetime(
            row["timestamp"]
        )

        future = candles[
            candles["timestamp"] > timestamp
        ].head(horizon)

        if len(future) < horizon:
            continue

        start_price = future.iloc[0]["close"]

        end_price = future.iloc[-1]["close"]

        move = (
            end_price
            -
            start_price
        )

        results.append(move)

    results = pd.Series(results)

    if len(results) == 0:
        continue

    positive = (
        results > 0
    ).mean()

    negative = (
        results < 0
    ).mean()

    print()
    print(
        "=" * 40
    )

    print(
        "HORIZON:",
        horizon
    )

    print(
        "UP CONTINUATION:",
        round(positive * 100, 2),
        "%"
    )

    print(
        "DOWN / DETERIORATION:",
        round(negative * 100, 2),
        "%"
    )

    print(
        "AVERAGE MOVE:",
        round(results.mean(), 2)
    )

print()
