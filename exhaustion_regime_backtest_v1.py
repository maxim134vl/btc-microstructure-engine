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
# MARKET REGIME
# =====================================

candles["regime"] = candles["close"].diff(20)

candles["regime"] = candles["regime"].apply(
    lambda x:
        "BULLISH"
        if x > 0
        else "BEARISH"
)

# =====================================
# FILTER EXHAUSTION
# =====================================

filtered = states[
    states["sequence"]
    ==
    "EXHAUSTION_SEQUENCE"
].copy()

print()
print(
    "TOTAL EXHAUSTION STATES:",
    len(filtered)
)

# =====================================
# TEST BY REGIME
# =====================================

for regime in ["BULLISH", "BEARISH"]:

    results = []

    for _, row in filtered.iterrows():

        timestamp = pd.to_datetime(
            row["timestamp"]
        )

        current = candles[
            candles["timestamp"] <= timestamp
        ]

        if len(current) == 0:
            continue

        current_regime = current.iloc[-1]["regime"]

        if current_regime != regime:
            continue

        future = candles[
            candles["timestamp"] > timestamp
        ].head(20)

        if len(future) < 20:
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
        "REGIME:",
        regime
    )

    print(
        "TOTAL:",
        len(results)
    )

    print(
        "UP CONTINUATION:",
        round(positive * 100, 2),
        "%"
    )

    print(
        "DOWN / REVERSAL:",
        round(negative * 100, 2),
        "%"
    )

    print(
        "AVERAGE MOVE:",
        round(results.mean(), 2)
    )

print()
