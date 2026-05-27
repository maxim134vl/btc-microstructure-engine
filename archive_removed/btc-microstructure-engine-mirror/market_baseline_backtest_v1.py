import pandas as pd

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

print()
print(
    "TOTAL CANDLES:",
    len(candles)
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
# BASELINE TEST
# =====================================

for horizon in horizons:

    results = []

    for i in range(len(candles) - horizon):

        start_price = candles.iloc[i]["close"]

        end_price = candles.iloc[
            i + horizon
        ]["close"]

        move = (
            end_price
            -
            start_price
        )

        results.append(move)

    results = pd.Series(results)

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
        "BASELINE HORIZON:",
        horizon
    )

    print(
        "UP MOVES:",
        round(positive * 100, 2),
        "%"
    )

    print(
        "DOWN MOVES:",
        round(negative * 100, 2),
        "%"
    )

    print(
        "AVERAGE MOVE:",
        round(results.mean(), 2)
    )

print()
