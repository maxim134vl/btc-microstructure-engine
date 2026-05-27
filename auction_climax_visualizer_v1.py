import pandas as pd
import matplotlib.pyplot as plt

# =====================================
# LOAD DATA
# =====================================

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.tail(140)

# =====================================
# WINDOW
# =====================================

candles = candles.reset_index(drop=True)

# =====================================
# FIGURE
# =====================================

plt.figure(
    figsize=(18, 9)
)

# =====================================
# CANDLES
# =====================================

for i, (_, row) in enumerate(
    candles.iterrows()
):

    # =====================================
    # COLOR
    # =====================================

    if row["close"] >= row["open"]:

        color = "lime"

    else:

        color = "red"

    # =====================================
    # WICK
    # =====================================

    plt.plot(

        [i, i],

        [
            row["low"],
            row["high"]
        ],

        color="#444444",

        linewidth=0.5,

        zorder=1

    )

    # =====================================
    # BODY
    # =====================================

    body_low = min(

        row["open"],
        row["close"]

    )

    body_high = max(

        row["open"],
        row["close"]

    )

    plt.gca().add_patch(

        plt.Rectangle(

            (
                i - 0.28,
                body_low
            ),

            0.56,

            max(
                body_high - body_low,
                0.5
            ),

            fill=False,

            edgecolor="#666666",

            linewidth=0.7,

            zorder=2

        )

    )

    # =====================================
    # HOLLOW BODY
    # =====================================

# =====================================
# TIMESTAMP INDEX MAP
# =====================================

timestamp_to_index = {

    ts: idx

    for idx, ts in enumerate(
        candles["timestamp"]
    )

}

# =====================================
# LOAD DISTRIBUTION
# =====================================

distribution = pd.read_parquet(
    "internal_volume_distribution.parquet"
)

distribution = distribution[
    distribution["timestamp"].isin(
        candles["timestamp"]
    )
]

# =====================================
# NORMALIZE VOLUME
# =====================================

distribution[
    "normalized_volume"
] = (

    distribution[
        "estimated_volume"
    ]

    /

    distribution[
        "estimated_volume"
    ].max()

)

# =====================================
# EXECUTION HEATMAP
# =====================================

for _, row in distribution.iterrows():

    candle_index = candles.index[
        candles["timestamp"]
        ==
        row["timestamp"]
    ][0]

    intensity = (

        row[
            "normalized_volume"
        ]
    )

    # =====================================
    # EVENT COLOR
    # =====================================

    if row[
        "auction_event_type"
    ] == "SELLING_CLIMAX":

        base_color = (1, 0, 0)

    elif row[
        "auction_event_type"
    ] == "BUYING_CLIMAX":

        base_color = (0, 1, 0)

    elif row[
        "auction_event_type"
    ] == "STOPPING_VOLUME":

        base_color = (1, 1, 0)

    else:

        base_color = (0, 0.7, 1)

    # =====================================
    # ALPHA
    # =====================================

    alpha = (
        0.15
        +
        intensity * 0.85
    )

    # =====================================
    # WIDTH
    # =====================================

    band_width = (
        4
        +
        intensity * 12
    )

    # =====================================
    # DRAW
    # =====================================

    plt.fill_between(

        [

            candle_index - 0.40,

            candle_index + 0.40

        ],

        row["price_level"] - band_width,

        row["price_level"] + band_width,

        color=(
            base_color[0],
            base_color[1],
            base_color[2],
            alpha
        ),

        linewidth=0

    )

# =====================================
# EVENT MARKERS
# =====================================

event_points = distribution.groupby(

    [
        "timestamp",
        "auction_event_type"
    ]

).agg({

    "price_level": "mean"

}).reset_index()

for _, row in event_points.iterrows():

    candle_index = candles.index[
        candles["timestamp"]
        ==
        row["timestamp"]
    ][0]

    if row[
        "auction_event_type"
    ] == "SELLING_CLIMAX":

        marker = "v"
        color = "red"

    elif row[
        "auction_event_type"
    ] == "BUYING_CLIMAX":

        marker = "^"
        color = "lime"

    elif row[
        "auction_event_type"
    ] == "STOPPING_VOLUME":

        marker = "s"
        color = "yellow"

    else:

        marker = "o"
        color = "cyan"

    plt.scatter(

        candle_index,

        row["price_level"],

        color=color,

        marker=marker,

        s=120,

        edgecolors="white",

        linewidths=1.2,

        zorder=10

    )

# =====================================
# STYLE
# =====================================

plt.title(
    "AUCTION INTERNAL EXECUTION MAP",
    color="white",
    fontsize=18
)

plt.grid(
    alpha=0.15
)

plt.gca().set_facecolor(
    "black"
)

plt.gcf().patch.set_facecolor(
    "black"
)

plt.xticks(
    color="white"
)

plt.yticks(
    color="white"
)

# =====================================
# SHOW
# =====================================

from matplotlib.lines import Line2D

legend_elements = [

    Line2D(
        [0],
        [0],
        color='red',
        lw=4,
        label='SELLING_CLIMAX'
    ),

    Line2D(
        [0],
        [0],
        color='lime',
        lw=4,
        label='BUYING_CLIMAX'
    ),

    Line2D(
        [0],
        [0],
        color='yellow',
        lw=4,
        label='STOPPING_VOLUME'
    ),

    Line2D(
        [0],
        [0],
        color='cyan',
        lw=4,
        label='HIGH_AVERAGE_VOLUME'
    )

]

plt.legend(

    handles=legend_elements,

    facecolor='black',

    edgecolor='white',

    labelcolor='white'

)

plt.show()
