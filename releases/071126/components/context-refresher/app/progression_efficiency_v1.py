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

efficiencies = []

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
    # ROTATION
    # ==============================

    rotation = (
        future["spread"]
        .sum()
    )

    # ==============================
    # PROGRESSION
    # ==============================

    progression = abs(

        future.iloc[-1]["close"]

        -

        future.iloc[0]["close"]

    )

    # ==============================
    # EFFICIENCY
    # ==============================

    efficiency = (
        progression
        /
        max(rotation, 1)
    )

    efficiencies.append(
        efficiency
    )

# =====================================
# VISUALIZATION
# =====================================

plt.figure(figsize=(16, 8))

plt.plot(

    efficiencies,

    linewidth=2

)

# =====================================
# STYLE
# =====================================

plt.title(

    "Деградация эффективности продвижения цены",

    fontsize=18

)

plt.xlabel(
    "Наблюдения"
)

plt.ylabel(
    "Эффективность"
)

plt.grid(True)

# =====================================
# SAVE
# =====================================

plt.savefig(

    "progression_efficiency_v1.png",

    dpi=300,
    bbox_inches="tight"

)

print()
print(
    "VISUALIZATION SAVED"
)

print(
    "progression_efficiency_v1.png"
)

print()
