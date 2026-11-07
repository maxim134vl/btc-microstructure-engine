import pandas as pd
import matplotlib.pyplot as plt

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

].copy()

# =====================================
# STORAGE
# =====================================

flip_counts = []

# =====================================
# ANALYSIS
# =====================================

for _, row in signals.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    future = candles[
        candles["timestamp"] > timestamp
    ].head(10)

    if len(future) < 10:
        continue

    # ==============================
    # DIRECTION
    # ==============================

    directions = []

    for _, candle in future.iterrows():

        move = (
            candle["close"]
            -
            candle["open"]
        )

        if move > 0:
            directions.append(1)
        else:
            directions.append(-1)

    # ==============================
    # FLIPS
    # ==============================

    flips = 0

    for i in range(1, len(directions)):

        if directions[i] != directions[i - 1]:
            flips += 1

    flip_counts.append(
        flips
    )

# =====================================
# VISUALIZATION
# =====================================

plt.figure(figsize=(16, 8))

plt.plot(

    flip_counts,

    linewidth=2

)

# =====================================
# STYLE
# =====================================

plt.title(

    "Частота смены направленного контроля",

    fontsize=18

)

plt.xlabel(
    "Наблюдения"
)

plt.ylabel(
    "Количество смен направления"
)

plt.grid(True)

# =====================================
# SAVE
# =====================================

plt.savefig(

    "directional_flips_v1.png",

    dpi=300,
    bbox_inches="tight"

)

print()
print(
    "VISUALIZATION SAVED"
)

print(
    "directional_flips_v1.png"
)

print()
