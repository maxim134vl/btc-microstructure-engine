# =====================================
# LEGEND
# =====================================

from matplotlib.lines import Line2D
from matplotlib.patches import Patch

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
