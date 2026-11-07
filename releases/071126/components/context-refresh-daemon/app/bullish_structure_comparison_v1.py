import pandas as pd

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# FUTURE MOVES
# =====================================

rows = []

for i in range(len(candles) - 10):

    current = candles.iloc[i]

    future = candles.iloc[
        i + 1:i + 11
    ]

    start_price = future.iloc[0]["close"]

    end_price = future.iloc[-1]["close"]

    move = (
        end_price
        -
        start_price
    )

    rows.append({

        "volume":
            current["volume"],

        "delta":
            current["delta"],

        "spread":
            current["spread"],

        "body":
            current["body"],

        "upper_wick":
            current["upper_wick"],

        "lower_wick":
            current["lower_wick"],

        "future_move":
            move

    })

# =====================================
# DATAFRAME
# =====================================

df = pd.DataFrame(rows)

# =====================================
# HEALTHY STATES
# =====================================

healthy = df.sort_values(

    "future_move",

    ascending=False

).head(30)

# =====================================
# FAILED STATES
# =====================================

lower_wick_threshold = df[
    "lower_wick"
].quantile(0.8)

upper_wick_threshold = df[
    "upper_wick"
].quantile(0.5)

body_threshold = df[
    "body"
].quantile(0.6)

volume_threshold = df[
    "volume"
].quantile(0.7)

delta_threshold = df[
    "delta"
].quantile(0.7)

failed = df[

    (df["lower_wick"]
     > lower_wick_threshold)

    &

    (df["upper_wick"]
     < upper_wick_threshold)

    &

    (df["body"]
     > body_threshold)

    &

    (df["volume"]
     < volume_threshold)

    &

    (df["delta"]
     < delta_threshold)

].copy()

# =====================================
# COMPARE
# =====================================

metrics = [

    "volume",

    "delta",

    "spread",

    "body",

    "upper_wick",

    "lower_wick"

]

print()

for metric in metrics:

    healthy_value = healthy[
        metric
    ].mean()

    failed_value = failed[
        metric
    ].mean()

    print("=" * 40)
    print(metric.upper())
    print("=" * 40)

    print()

    print(
        "HEALTHY:",
        round(
            healthy_value,
            2
        )
    )

    print(
        "FAILED:",
        round(
            failed_value,
            2
        )
    )

    print()
