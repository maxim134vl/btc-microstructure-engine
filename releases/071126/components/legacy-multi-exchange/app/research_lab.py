import time
import os
import pandas as pd
import numpy as np

# =================================
# LOAD DATA
# =================================
while True:

    os.system('clear')
print()
print("LOADING DATA")
print()

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

# =================================
# ALIGN
# =================================

min_len = min(

    len(flow),

    len(oi),

    len(book)
)

flow = flow.tail(min_len)

oi = oi.tail(min_len)

book = book.tail(min_len)

# =================================
# FEATURES
# =================================

print("BUILDING FEATURES")
print()

# DELTA

flow['delta_smooth'] = (

    flow['delta']
    .rolling(50)
    .mean()
)

# VOL

returns = (

    flow['avg_price']
    .pct_change()
)

flow['volatility'] = (

    returns
    .rolling(50)
    .std()
)

# OI

oi['oi_change'] = (

    oi['open_interest']
    .diff()
)

# IMBALANCE

book['imbalance_smooth'] = (

    book['imbalance']
    .rolling(50)
    .mean()
)

# =================================
# BASIC SUMMARY
# =================================

print("================================")
print("DATA SUMMARY")
print("================================")
print()

print(
    "FLOW ROWS:",
    len(flow)
)

print(
    "OI ROWS:",
    len(oi)
)

print(
    "BOOK ROWS:",
    len(book)
)

print(
    "EVENTS:",
    len(events)
)

print()

# =================================
# REGIME SNAPSHOT
# =================================

print("================================")
print("CURRENT MARKET STATE")
print("================================")
print()

latest_price = (
    flow.iloc[-1][
        'avg_price'
    ]
)

latest_delta = (
    flow.iloc[-1][
        'delta_smooth'
    ]
)

latest_vol = (
    flow.iloc[-1][
        'volatility'
    ]
)

latest_oi = (
    oi.iloc[-1][
        'oi_change'
    ]
)

latest_imbalance = (
    book.iloc[-1][
        'imbalance_smooth'
    ]
)

print(
    "PRICE:",
    round(
        latest_price,
        2
    )
)

print(
    "DELTA PRESSURE:",
    round(
        latest_delta,
        2
    )
)

print(
    "VOLATILITY:",
    round(
        latest_vol,
        8
    )
)

print(
    "OI CHANGE:",
    round(
        latest_oi,
        2
    )
)

print(
    "IMBALANCE:",
    round(
        latest_imbalance,
        4
    )
)

print()

# =================================
# EVENT COUNTS
# =================================

print("================================")
print("EVENT DISTRIBUTION")
print("================================")
print()

event_counts = (

    events['event']
    .value_counts()
)

print(
    event_counts
)

print()

# =================================
# OI SURPRISE
# =================================

WINDOW = 200

oi['oi_z'] = (

    (
        oi['oi_change']
        -
        oi['oi_change']
        .rolling(WINDOW)
        .mean()
    )

    /

    oi['oi_change']
    .rolling(WINDOW)
    .std()
)

latest_oi_z = abs(

    oi.iloc[-1][
        'oi_z'
    ]
)

print("================================")
print("OI SURPRISE")
print("================================")
print()

print(
    "CURRENT OI Z-SCORE:",
    round(
        latest_oi_z,
        2
    )
)

if latest_oi_z > 5:

    print()
    print(
        "EXTREME LEVERAGE ANOMALY DETECTED"
    )

elif latest_oi_z > 3:

    print()
    print(
        "ELEVATED LEVERAGE ACTIVITY"
    )

else:

    print()
    print(
        "NORMAL LEVERAGE REGIME"
    )

print()

# =================================
# STATE INTERPRETATION
# =================================

print("================================")
print("INTERPRETATION")
print("================================")
print()

if latest_vol < 0.0001:

    print(
        "- Low volatility regime"
    )

else:

    print(
        "- Elevated volatility regime"
    )

if abs(latest_imbalance) > 0.2:

    print(
        "- Persistent liquidity imbalance"
    )

if abs(latest_delta) > 50:

    print(
        "- Aggressive directional pressure"
    )

if latest_oi_z > 5:

    print(
        "- Abnormal leverage positioning"
    )

print()
# =================================
# REGIME CLASSIFICATION
# =================================

print("================================")
print("MARKET REGIME")
print("================================")
print()

market_state = "UNDEFINED"

# QUIET COMPRESSION

if (

    latest_vol < 0.00001

    and

    abs(latest_delta) < 10
):

    market_state = (
        "QUIET_COMPRESSION"
    )

# PASSIVE IMBALANCE

elif (

    latest_vol < 0.00001

    and

    abs(latest_imbalance) > 0.1
):

    market_state = (
        "PASSIVE_IMBALANCE"
    )

# LEVERAGE BUILDUP

elif (

    latest_oi_z > 5

    and

    latest_vol < 0.00005
):

    market_state = (
        "LEVERAGE_BUILDUP"
    )

# VOL EXPANSION

elif (

    latest_vol > 0.00005

    and

    abs(latest_delta) > 50
):

    market_state = (
        "VOLATILITY_EXPANSION"
    )

# AGGRESSIVE TREND

elif (

    abs(latest_delta) > 100
):

    market_state = (
        "AGGRESSIVE_TREND"
    )

print(
    "CURRENT STATE:",
    market_state
)

print()
print(
    "RESEARCH LAB COMPLETE"
)
print()
print("UPDATING IN 60 SECONDS...")
print()

time.sleep(60)
