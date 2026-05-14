import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ---------------------------------
# LOAD
# ---------------------------------

flow = pd.read_parquet(
    "intraday_flow.parquet"
)

oi = pd.read_parquet(
    "oi_history.parquet"
)

book = pd.read_parquet(
    "orderbook.parquet"
)

events = pd.read_parquet(
    "market_events.parquet"
)

# ---------------------------------
# ALIGN
# ---------------------------------

min_len = min(

    len(flow),

    len(oi),

    len(book)
)

flow = flow.tail(min_len)

oi = oi.tail(min_len)

book = book.tail(min_len)

# ---------------------------------
# VOLATILITY
# ---------------------------------

returns = (

    flow['avg_price']
    .pct_change()
    .fillna(0)
)

realized_vol = (

    returns
    .rolling(50)
    .std()
)

# ---------------------------------
# FIGURE
# ---------------------------------

fig, axes = plt.subplots(

    5,

    1,

    figsize=(18, 14),

    sharex=True
)

# =================================
# PRICE
# =================================

axes[0].plot(

    flow.index,

    flow['avg_price']
)

axes[0].set_title(
    "BTC PRICE"
)

# EVENTS

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

        axes[0].scatter(

            idx,

            price,

            s=80
        )

    except:

        continue

# =================================
# DELTA
# =================================

axes[1].bar(

    flow.index,

    flow['delta']
)

axes[1].set_title(
    "DELTA"
)

# =================================
# OI
# =================================

axes[2].plot(

    oi.index,

    oi['open_interest']
)

axes[2].set_title(
    "OPEN INTEREST"
)

# =================================
# IMBALANCE
# =================================

axes[3].plot(

    book.index,

    book['imbalance']
)

axes[3].axhline(
    0,
    linestyle='--'
)

axes[3].set_title(
    "ORDERBOOK IMBALANCE"
)

# =================================
# VOLATILITY
# =================================

axes[4].plot(

    realized_vol.index,

    realized_vol
)

axes[4].set_title(
    "REALIZED VOLATILITY"
)

# ---------------------------------
# LAYOUT
# ---------------------------------

plt.tight_layout()

# ---------------------------------
# SHOW
# ---------------------------------

plt.show()
