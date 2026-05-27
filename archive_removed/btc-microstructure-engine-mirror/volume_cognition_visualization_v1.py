import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

# =====================================
# LOAD DATA
# =====================================

volume = pd.read_parquet(
    "historical_volume_cognition.parquet"
)

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# MERGE
# =====================================

df = candles.merge(
    volume[
        [
            "timestamp",
            "volume_class"
        ]
    ],
    on="timestamp",
    how="left"
)

# =====================================
# PREPARE
# =====================================

df["timestamp"] = pd.to_datetime(
    df["timestamp"]
)

df = df.sort_values("timestamp")

# =====================================
# PLOT
# =====================================

fig, ax = plt.subplots(
    figsize=(22, 10)
)

# =====================================
# DRAW CANDLES
# =====================================

candle_width = 0.008

for _, row in df.iterrows():

    ts = mdates.date2num(
        row["timestamp"]
    )

    open_price = row["open"]
    close_price = row["close"]
    high_price = row["high"]
    low_price = row["low"]

    volume_class = row["volume_class"]

    # ================================
    # CANDLE COLOR
    # ================================

    bullish = close_price >= open_price

    candle_color = (
        "green"
        if bullish
        else "red"
    )

    # ================================
    # HIGH AVERAGE OUTLINE
    # ================================

    edge_color = "black"
    edge_width = 1

    if volume_class == "high_average":

        edge_color = "darkblue"
        edge_width = 2.5

    # ================================
    # WICK
    # ================================

    ax.plot(
        [ts, ts],
        [low_price, high_price],
        color=edge_color,
        linewidth=edge_width
    )

    # ================================
    # BODY
    # ================================

    lower = min(
        open_price,
        close_price
    )

    body_height = abs(
        close_price - open_price
    )

    rect = Rectangle(

        (
            ts - candle_width / 2,
            lower
        ),

        candle_width,

        max(body_height, 1),

        facecolor=candle_color,

        edgecolor=edge_color,

        linewidth=edge_width
    )

    ax.add_patch(rect)

    # ================================
    # CLIMAX MARKER
    # ================================

    if volume_class == "climax":

        ax.scatter(

            ts,

            high_price + 20,

            color="yellow",

            s=120,

            marker="o",

            edgecolors="black",

            zorder=5

        )

    # ================================
    # STOPPING MARKER
    # ================================

    if volume_class == "stopping":

        ax.scatter(

            ts,

            low_price - 20,

            color="blue",

            s=120,

            marker="o",

            edgecolors="black",

            zorder=5

        )

# =====================================
# STYLE
# =====================================

ax.set_title(
    "Volume Cognition Visualization",
    fontsize=18
)

ax.set_xlabel("Time")
ax.set_ylabel("Price")

ax.grid(True)

ax.xaxis.set_major_formatter(
    mdates.DateFormatter('%m-%d %H:%M')
)

plt.xticks(rotation=45)

plt.tight_layout()

# =====================================
# SAVE
# =====================================

plt.savefig(
    "volume_cognition_visualization.png",
    dpi=300
)

print()
print(
    "VISUALIZATION SAVED"
)

print(
    "volume_cognition_visualization.png"
)

print()

plt.show()
