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

step_spreads = {
    i: [] for i in range(10)
}

step_bodies = {
    i: [] for i in range(10)
}

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

    for i in range(10):

        step_spreads[i].append(
            future.iloc[i]["spread"]
        )

        step_bodies[i].append(
            future.iloc[i]["body"]
        )

# =====================================
# AVERAGES
# =====================================

avg_spreads = []
avg_bodies = []

for i in range(10):

    avg_spreads.append(

        pd.Series(
            step_spreads[i]
        ).mean()

    )

    avg_bodies.append(

        pd.Series(
            step_bodies[i]
        ).mean()

    )

# =====================================
# VISUALIZATION
# =====================================

plt.figure(figsize=(16, 8))

plt.plot(

    avg_spreads,

    label="Средний диапазон",
    linewidth=2

)

plt.plot(

    avg_bodies,

    label="Среднее тело свечи",
    linewidth=2

)

# =====================================
# STYLE
# =====================================

plt.title(

    "Структурная деградация продолжения движения",

    fontsize=18

)

plt.xlabel(
    "Шаги после сигнала"
)

plt.ylabel(
    "Размер структуры"
)

plt.legend()

plt.grid(True)

# =====================================
# SAVE
# =====================================

plt.savefig(

    "continuation_structure_v1.png",

    dpi=300,
    bbox_inches="tight"

)

print()
print(
    "VISUALIZATION SAVED"
)

print(
    "continuation_structure_v1.png"
)

print()
