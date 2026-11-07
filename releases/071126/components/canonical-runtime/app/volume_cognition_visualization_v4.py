import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from matplotlib.lines import Line2D
from matplotlib.patches import Patch

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

df = df.sort_values(
    "timestamp"
)

# =====================================
# LAST WINDOW
# =====================================

df = df.tail(120).copy()

# =====================================
# FIGURE
# =====================================

fig, (ax1, ax2) = plt.subplots(

    2,
    1,

    figsize=(24, 14),

    sharex=True,

    gridspec_kw={
        "height_ratios": [4, 1]
    }

)

# =====================================
# TABLE DATA
# =====================================

table_rows = []

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

    bullish = close_price >= open_price

    candle_color = (
        "#00c853"
        if bullish
        else "#d50000"
    )

    # =================================
    # HIGH AVERAGE BACKGROUND
    # =================================

    if volume_class == "high_average":

        ax1.axvspan(

            ts - candle_width,

            ts + candle_width,

            color="darkblue",

            alpha=0.08,

            zorder=0

        )

    # =================================
    # WICK
    # =================================

    ax1.plot(

        [ts, ts],

        [low_price, high_price],

        color=candle_color,

        linewidth=1.2,

        zorder=2

    )

    # =================================
    # BODY
    # =================================

    lower = min(
        open_price,
        close_price
    )

    height = abs(
        close_price - open_price
    )

    ax1.add_patch(

        plt.Rectangle(

            (
                ts - candle_width / 2,
                lower
            ),

            candle_width,

            max(height, 1),

            facecolor=candle_color,

            edgecolor=candle_color,

            linewidth=1,

            zorder=3

        )

    )

    # =================================
    # CLIMAX
    # =================================

    if volume_class == "climax":

        climax_price = high_price

        ax1.scatter(

            ts,

            climax_price,

            s=260,

            color="yellow",

            edgecolors="black",

            linewidths=1.5,

            zorder=5

        )

        ax1.hlines(

            climax_price,

            ts - 0.015,

            ts + 0.015,

            colors="yellow",

            linewidth=2

        )

        ax1.text(

            ts,

            climax_price + 15,

            f"C {round(climax_price, 0)}",

            fontsize=9,

            color="yellow",

            ha="center",

            fontweight="bold"

        )

        table_rows.append({

            "timestamp":
                row["timestamp"],

            "price":
                round(climax_price, 2),

            "class":
                "climax"

        })

    # =================================
    # STOPPING
    # =================================

    if volume_class == "stopping":

        stopping_price = low_price

        ax1.scatter(

            ts,

            stopping_price,

            s=260,

            color="blue",

            edgecolors="black",

            linewidths=1.5,

            zorder=5

        )

        ax1.hlines(

            stopping_price,

            ts - 0.015,

            ts + 0.015,

            colors="blue",

            linewidth=2

        )

        ax1.text(

            ts,

            stopping_price - 15,

            f"S {round(stopping_price, 0)}",

            fontsize=9,

            color="blue",

            ha="center",

            fontweight="bold"

        )

        table_rows.append({

            "timestamp":
                row["timestamp"],

            "price":
                round(stopping_price, 2),

            "class":
                "stopping"

        })

# =====================================
# VOLUME PANEL
# =====================================

volume_colors = []

for _, row in df.iterrows():

    bullish = row["close"] >= row["open"]

    volume_colors.append(

        "#00c853"
        if bullish
        else "#d50000"

    )

ax2.bar(

    df["timestamp"],

    df["volume"],

    color=volume_colors,

    width=0.01,

    alpha=0.8

)

# =====================================
# LEGEND
# =====================================

legend_elements = [

    Patch(

        facecolor="darkblue",

        alpha=0.08,

        label="High Average Volume"

    ),

    Line2D(

        [0],
        [0],

        marker='o',

        color='w',

        label='Climax Volume',

        markerfacecolor='yellow',

        markeredgecolor='black',

        markersize=12

    ),

    Line2D(

        [0],
        [0],

        marker='o',

        color='w',

        label='Stopping Volume',

        markerfacecolor='blue',

        markeredgecolor='black',

        markersize=12

    ),

    Line2D(

        [0],
        [0],

        color='#00c853',

        lw=4,

        label='Bullish Candle'

    ),

    Line2D(

        [0],
        [0],

        color='#d50000',

        lw=4,

        label='Bearish Candle'

    )

]

ax1.legend(

    handles=legend_elements,

    loc='upper left',

    fontsize=11

)

# =====================================
# STYLE
# =====================================

ax1.set_title(

    "Volume Cognition Visualization",

    fontsize=20

)

ax1.set_ylabel(
    "Price"
)

ax2.set_ylabel(
    "Volume"
)

ax1.grid(alpha=0.2)
ax2.grid(alpha=0.2)

ax2.xaxis.set_major_formatter(

    mdates.DateFormatter(
        '%m-%d %H:%M'
    )

)

plt.xticks(rotation=45)

plt.tight_layout()

# =====================================
# SAVE IMAGE
# =====================================

plt.savefig(

    "volume_cognition_visualization_v4.png",

    dpi=300

)

# =====================================
# SAVE TABLE
# =====================================

table_df = pd.DataFrame(
    table_rows
)

table_df.to_csv(

    "volume_cognition_levels.csv",

    index=False

)

# =====================================
# DONE
# =====================================

print()
print(
    "VISUALIZATION SAVED:"
)

print(
    "volume_cognition_visualization_v4.png"
)

print()

print(
    "TABLE SAVED:"
)

print(
    "volume_cognition_levels.csv"
)

print()

plt.show()
