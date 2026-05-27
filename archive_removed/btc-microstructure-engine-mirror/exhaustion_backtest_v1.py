import pandas as pd

# =====================================
# LOAD DATA
# =====================================

states = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# FILTER EXHAUSTION
# =====================================

exhaustion = states[
    states["sequence"]
    ==
    "EXHAUSTION_SEQUENCE"
].copy()

print()
print(
    "TOTAL EXHAUSTION SEQUENCES:",
    len(exhaustion)
)

results = []

# =====================================
# ANALYZE OUTCOME
# =====================================

for _, row in exhaustion.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    future = candles[
        candles["timestamp"] > timestamp
    ].head(5)

    if len(future) < 5:
        continue

    start_price = future.iloc[0]["close"]

    end_price = future.iloc[-1]["close"]

    move = (
        end_price
        -
        start_price
    )

    results.append(move)

# =====================================
# RESULTS
# =====================================

results = pd.Series(results)

if len(results) == 0:

    print()
    print(
        "NO VALID FUTURE WINDOWS"
    )

else:

    positive = (
        results > 0
    ).mean()

    negative = (
        results < 0
    ).mean()

    print()
    print(
        "UP CONTINUATION RATE:",
        round(positive * 100, 2),
        "%"
    )

    print(
        "DOWN / REVERSAL RATE:",
        round(negative * 100, 2),
        "%"
    )

    print()
    print(
        "AVERAGE MOVE:",
        round(results.mean(), 2)
    )

print()
