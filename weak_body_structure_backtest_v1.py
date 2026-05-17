import pandas as pd

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# BODY EFFICIENCY
# =====================================

candles["body_ratio"] = (

    candles["body"]

    /

    (
        candles["spread"]
        + 1e-9
    )

)

# =====================================
# FILTER
# =====================================

filtered = candles[

    (candles["body_ratio"] < 0.25)

    &

    (candles["spread_zscore"] > 1)

].copy()

print()
print(
    "TOTAL WEAK BODY STATES:",
    len(filtered)
)

# =====================================
# TEST
# =====================================

horizons = [
    5,
    10,
    20
]

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

    down_rate = (
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
        "DOWN RATE:",
        round(down_rate * 100, 2),
        "%"
    )

    print(
        "AVERAGE MOVE:",
        round(results.mean(), 2)
    )

print()
