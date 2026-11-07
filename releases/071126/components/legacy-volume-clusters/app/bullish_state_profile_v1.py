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
# TOP BULLISH STATES
# =====================================

top_bullish = df.sort_values(

    "future_move",

    ascending=False

).head(30)

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

    top_value = top_bullish[
        metric
    ].mean()

    baseline = df[
        metric
    ].mean()

    print("=" * 40)
    print(metric.upper())
    print("=" * 40)

    print()

    print(
        "TOP BULLISH:",
        round(top_value, 2)
    )

    print(
        "BASELINE:",
        round(baseline, 2)
    )

    print()
