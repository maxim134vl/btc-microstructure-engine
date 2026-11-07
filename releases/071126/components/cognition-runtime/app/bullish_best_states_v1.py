import pandas as pd

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# FUTURE PERFORMANCE
# =====================================

future_moves = []

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

    future_moves.append({

        "timestamp":
            current["timestamp"],

        "close":
            current["close"],

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

results = pd.DataFrame(
    future_moves
)

# =====================================
# BEST BULLISH STATES
# =====================================

best = results.sort_values(

    "future_move",

    ascending=False

).head(30)

# =====================================
# ROUND
# =====================================

numeric_cols = [

    "close",

    "volume",

    "delta",

    "spread",

    "body",

    "upper_wick",

    "lower_wick",

    "future_move"

]

best[numeric_cols] = best[
    numeric_cols
].round(2)

# =====================================
# SAVE
# =====================================

best.to_csv(

    "best_bullish_states.csv",

    index=False

)

# =====================================
# SUMMARY
# =====================================

print()
print(
    "BEST BULLISH STATES SAVED"
)

print(
    "best_bullish_states.csv"
)

print()
