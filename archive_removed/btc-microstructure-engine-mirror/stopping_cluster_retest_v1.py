import pandas as pd
import mplfinance as mpf

print("\nSTOPPING CLUSTER RETEST STARTED\n")

# =====================================
# LOAD DATA
# =====================================

flow = pd.read_parquet(
    "multi_exchange_flow.parquet"
)

flow["timestamp"] = pd.to_datetime(
    flow["timestamp"]
)

flow = flow.sort_values("timestamp")

# =====================================
# BUILD OHLC
# =====================================

ohlc = flow.resample(
    "1h",
    on="timestamp"
).agg({
    "avg_price": [
        "first",
        "max",
        "min",
        "last"
    ],
    "delta": "sum",
    "buy_volume": "sum",
    "sell_volume": "sum",
    "price_change": "sum"
})

ohlc.columns = [
    "Open",
    "High",
    "Low",
    "Close",
    "Delta",
    "BuyVolume",
    "SellVolume",
    "PriceChange"
]

ohlc = ohlc.dropna()

# =====================================
# MEMORY
# =====================================

zones = []

# =====================================
# VISUALS
# =====================================

origin_points = []

retest_points = []

connections = []

# =====================================
# REPLAY LOOP
# =====================================

for i in range(1, len(ohlc)):

    row = ohlc.iloc[i]

    prev = ohlc.iloc[i - 1]

    timestamp = ohlc.index[i]

    open_price = row["Open"]

    close = row["Close"]

    low = row["Low"]

    high = row["High"]

    delta = row["Delta"]

    price_change = row["PriceChange"]

    body = abs(close - open_price)

    lower_wick = (
        min(open_price, close)
        -
        low
    )

    # =====================================
    # STEP 1
    # STOPPING CLUSTER
    # =====================================

    stopping_event = (

        prev["PriceChange"] < -20

        and

        delta > 50

        and

        price_change > 10

        and

        lower_wick > body

    )

    if stopping_event:

        zone = {

            "timestamp": timestamp,

            "zone_low": low,

            "zone_high": (
                low
                +
                lower_wick
            ),

            "origin_price": close
        }

        zones.append(
            zone
        )

        origin_points.append(
            (timestamp, low)
        )

    # =====================================
    # STEP 2
    # STOPPING RETEST
    # =====================================

    for zone in zones:

        age_hours = (
            timestamp - zone["timestamp"]
        ).total_seconds() / 3600

        if age_hours < 1:

            continue

        # =====================================
        # SAME AUCTION AREA
        # =====================================

        same_area = (

            low <= zone["zone_high"]

            and

            low >= (
                zone["zone_low"]
                - 15
            )

        )

        if not same_area:

            continue

        # =====================================
        # RETEST STOPPING BEHAVIOR
        # =====================================

        retest_stopping = (

            delta > 20

            and

            price_change > 5

            and

            lower_wick > body

            and

            close > zone["zone_low"]

        )

        if retest_stopping:

            retest_points.append(
                (timestamp, low)
            )

            connections.append({

                "x1": zone["timestamp"],
                "y1": zone["zone_low"],

                "x2": timestamp,
                "y2": low
            })

# =====================================
# SERIES
# =====================================

def build_series(points):

    s = pd.Series(
        index=ohlc.index,
        dtype=float
    )

    for ts, price in points:

        s.loc[ts] = price

    return s

origin_series = build_series(
    origin_points
)

retest_series = build_series(
    retest_points
)

# =====================================
# PLOTS
# =====================================

apds = [

    mpf.make_addplot(
        origin_series,
        type='scatter',
        marker='^',
        markersize=120,
        color='blue'
    ),

    mpf.make_addplot(
        retest_series,
        type='scatter',
        marker='o',
        markersize=120,
        color='orange'
    )

]

# =====================================
# FIGURE
# =====================================

fig, axlist = mpf.plot(
    ohlc,
    type='candle',
    style='charles',
    volume=False,
    addplot=apds,
    figsize=(20, 12),
    tight_layout=True,
    returnfig=True
)

ax = axlist[0]

# =====================================
# CONNECTIONS
# =====================================

for c in connections:

    ax.plot(

        [c["x1"], c["x2"]],

        [c["y1"], c["y2"]],

        color='lime',

        linewidth=2.5

    )

# =====================================
# LEGEND
# =====================================

ax.plot(
    [],
    [],
    marker='^',
    linestyle='None',
    markersize=10,
    color='blue',
    label='Stopping Cluster'
)

ax.plot(
    [],
    [],
    marker='o',
    linestyle='None',
    markersize=10,
    color='orange',
    label='Successful Retest'
)

ax.plot(
    [],
    [],
    color='lime',
    linewidth=2,
    label='Behavioral Connection'
)

ax.legend(
    loc='upper left',
    fontsize=12
)

mpf.show()
