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
# SMOOTHING
# ---------------------------------

flow['delta_smooth'] = (

    flow['delta']
    .rolling(50)
    .mean()
)

book['imbalance_smooth'] = (

    book['imbalance']
    .rolling(50)
    .mean()
)

oi['oi_smooth'] = (

    oi['open_interest']
    .rolling(20)
    .mean()
)

oi['oi_acceleration'] = (

    oi['oi_smooth']
    .diff()
)

# ---------------------------------
# VOL
# ---------------------------------

returns = (

    flow['avg_price']
    .pct_change()
)

volatility = (

    returns
    .rolling(50)
    .std()
)

# ---------------------------------
# Z-SCORES
# ---------------------------------

flow['delta_z'] = (

    (
        flow['delta_smooth']
        -
        flow['delta_smooth'].mean()
    )

    /

    flow['delta_smooth'].std()
)

book['imbalance_z'] = (

    (
        book['imbalance_smooth']
        -
        book['imbalance_smooth'].mean()
    )

    /

    book['imbalance_smooth'].std()
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

# =================================
# SMOOTHED DELTA
# =================================

axes[1].plot(

    flow.index,

    flow['delta_smooth']
)

axes[1].axhline(
    0,
    linestyle='--'
)

axes[1].set_title(
    "SMOOTHED DELTA PRESSURE"
)

# =================================
# OI ACCELERATION
# =================================

axes[2].plot(

    oi.index,

    oi['oi_acceleration']
)

axes[2].axhline(
    0,
    linestyle='--'
)

axes[2].set_title(
    "OI ACCELERATION"
)

# =================================
# IMBALANCE
# =================================

axes[3].plot(

    book.index,

    book['imbalance_smooth']
)

axes[3].axhline(
    0,
    linestyle='--'
)

axes[3].set_title(
    "SMOOTHED ORDERBOOK IMBALANCE"
)

# =================================
# VOLATILITY
# =================================

axes[4].plot(

    volatility.index,

    volatility
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
