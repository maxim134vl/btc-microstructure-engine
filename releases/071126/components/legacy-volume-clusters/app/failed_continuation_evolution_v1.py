import pandas as pd

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# THRESHOLDS
# =====================================

lower_wick_threshold = candles[
    "lower_wick"
].quantile(0.8)

upper_wick_threshold = candles[
    "upper_wick"
].quantile(0.5)

body_threshold = candles[
    "body"
].quantile(0.6)

volume_threshold = candles[
    "volume"
].quantile(0.7)

delta_threshold = candles[
    "delta"
].quantile(0.7)

# =====================================
# SIGNALS
# =====================================

signals = candles[

    (candles["lower_wick"]
     > lower_wick_threshold)

    &

    (candles["upper_wick"]
     < upper_wick_threshold)

    &

    (candles["body"]
     > body_threshold)

    &

    (candles["volume"]
     < volume_threshold)

    &

    (candles["delta"]
     < delta_threshold)

].copy()

print()
print(
    "TOTAL SIGNALS:",
    len(signals)
)

# =====================================
# STEP ANALYSIS
# =====================================

for step in range(1, 6):

    deltas = []
    spreads = []

    bodies = []

    upper_wicks = []
    lower_wicks = []

    for _, row in signals.iterrows():

        timestamp = pd.to_datetime(
            row["timestamp"]
        )

        future = candles[
            candles["timestamp"] > timestamp
        ].head(step)

        if len(future) < step:
            continue

        candle = future.iloc[-1]

        deltas.append(
            candle["delta"]
        )

        spreads.append(
            candle["spread"]
        )

        bodies.append(
            candle["body"]
        )

        upper_wicks.append(
            candle["upper_wick"]
        )

        lower_wicks.append(
            candle["lower_wick"]
        )

    print()
    print("=" * 40)
    print(
        "STEP",
        step
    )
    print("=" * 40)

    print()

    print(
        "DELTA:",
        round(
            pd.Series(
                deltas
            ).mean(),
            2
        )
    )

    print(
        "SPREAD:",
        round(
            pd.Series(
                spreads
            ).mean(),
            2
        )
    )

    print(
        "BODY:",
        round(
            pd.Series(
                bodies
            ).mean(),
            2
        )
    )

    print(
        "UPPER WICK:",
        round(
            pd.Series(
                upper_wicks
            ).mean(),
            2
        )
    )

    print(
        "LOWER WICK:",
        round(
            pd.Series(
                lower_wicks
            ).mean(),
            2
        )
    )

print()
