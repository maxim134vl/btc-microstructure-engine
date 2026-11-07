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

max_progressions = []
final_progressions = []

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

    start_price = future.iloc[0]["close"]

    max_move = (

        future["high"].max()

        -
        start_price

    )

    final_move = (

        future.iloc[-1]["close"]

        -
        start_price

    )

    max_progressions.append(
        max_move
    )

    final_progressions.append(
        final_move
    )

# =====================================
# VISUALIZATION
# =====================================

plt.figure(figsize=(16, 8))

plt.plot(

    max_progressions,

    label="Максимальное продолжение",
    linewidth=2

)

plt.plot(

    final_progressions,

    label="Итоговое удержание",
    linewidth=2

)

# =====================================
# STYLE
# =====================================

plt.title(

    "Разрушение удержания продолжения движения",

    fontsize=18

)

plt.xlabel(
    "Наблюдения"
)

plt.ylabel(
    "Движение цены"
)

plt.legend()

plt.grid(True)

# =====================================
# SAVE
# =====================================

plt.savefig(

    "retention_visualization_v1.png",

    dpi=300,
    bbox_inches="tight"

)

print()
print(
    "VISUALIZATION SAVED"
)

print(
    "retention_visualization_v1.png"
)

print()
