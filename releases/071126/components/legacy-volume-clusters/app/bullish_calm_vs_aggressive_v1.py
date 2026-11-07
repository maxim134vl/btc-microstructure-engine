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

high_volume = candles["volume"].quantile(
    0.7
)

high_delta = candles["delta"].quantile(
    0.7
)

high_spread = candles["spread"].quantile(
    0.7
)

# =====================================
# FUTURE MOVES
# =====================================

calm_moves = []
aggressive_moves = []

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

    # ================================
    # AGGRESSIVE
    # ================================

    aggressive = (

        current["volume"] > high_volume

        and

        current["delta"] > high_delta

        and

        current["spread"] > high_spread

    )

    # ================================
    # SAVE
    # ================================

    if aggressive:

        aggressive_moves.append(move)

    else:

        calm_moves.append(move)

# =====================================
# RESULTS
# =====================================

calm_moves = pd.Series(calm_moves)
aggressive_moves = pd.Series(aggressive_moves)

print()
print("=" * 40)
print("CALM STATES")
print("=" * 40)

print()

print(
    "TOTAL:",
    len(calm_moves)
)

print(
    "UP RATE:",
    round(
        (calm_moves > 0).mean() * 100,
        2
    ),
    "%"
)

print(
    "AVERAGE MOVE:",
    round(
        calm_moves.mean(),
        2
    )
)

print()

print("=" * 40)
print("AGGRESSIVE STATES")
print("=" * 40)

print()

print(
    "TOTAL:",
    len(aggressive_moves)
)

print(
    "UP RATE:",
    round(
        (aggressive_moves > 0).mean() * 100,
        2
    ),
    "%"
)

print(
    "AVERAGE MOVE:",
    round(
        aggressive_moves.mean(),
        2
    )
)

print()
