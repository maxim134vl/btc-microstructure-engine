import pandas as pd
import matplotlib.pyplot as plt

# ---------------------------------
# LOAD DATA
# ---------------------------------

flow = pd.read_parquet(
    "intraday_flow.parquet"
)

events = pd.read_parquet(
    "market_events.parquet"
)

# ---------------------------------
# LAST WINDOW
# ---------------------------------

flow = flow.tail(500)

# ---------------------------------
# FIGURE
# ---------------------------------

plt.figure(
    figsize=(16, 8)
)

# ---------------------------------
# PRICE
# ---------------------------------

plt.plot(

    flow.index,

    flow['avg_price'],

    label='BTC Price'
)

# ---------------------------------
# DELTA SPIKES
# ---------------------------------

positive = flow[
    flow['delta'] > 100
]

negative = flow[
    flow['delta'] < -100
]

plt.scatter(

    positive.index,

    positive['avg_price'],

    marker='^',

    s=80,

    label='Positive Delta'
)

plt.scatter(

    negative.index,

    negative['avg_price'],

    marker='v',

    s=80,

    label='Negative Delta'
)

# ---------------------------------
# EVENTS
# ---------------------------------

for _, row in events.iterrows():

    try:

        matches = flow[

            flow['timestamp']
            >=
            row['timestamp']
        ]

        if len(matches) == 0:

            continue

        idx = matches.index[0]

        price = matches.iloc[0][
            'avg_price'
        ]

        plt.scatter(

            idx,

            price,

            marker='o',

            s=120
        )

        plt.text(

            idx,

            price,

            row['event'],

            fontsize=8
        )

    except:

        continue

# ---------------------------------
# TITLE
# ---------------------------------

plt.title(
    "MARKET REPLAY"
)

plt.legend()

plt.grid()

# ---------------------------------
# SHOW
# ---------------------------------

plt.show()
