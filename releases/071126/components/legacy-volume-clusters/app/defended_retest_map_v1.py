import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt

print("\nDEFENDED RETEST MAP STARTED\n")

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
# VISUAL EVENTS
# =====================================

origin_points = []

retest_points = []

confirmation_points = []

connections = []

# =====================================
# REPLAY LOOP
# =====================================

for i in range(len(ohlc)):

    row = ohlc.iloc[i]

    timestamp = ohlc.index[i]

    delta = row["Delta"]

    close = row["Close"]

    low = row["Low"]

    high = row["High"]

    price_change = row["PriceChange"]

    # =====================================
    # STEP 1
    # ORIGIN INITIATIVE
    # =====================================

    if (
        delta > 70
        and
        price_change > 15
    ):

        zone = {
            "timestamp": timestamp,
            "origin_price": close,
            "zone_low": low,
            "zone_high": high,
            "retested": False,
            "confirmed": False
        }

        zones.append(
            zone
        )

        origin_points.append(
            (timestamp, close)
        )

    # =====================================
    # STEP 2
    # RETEST
    # =====================================

    for zone in zones:

        age_hours = (
            timestamp - zone["timestamp"]
        ).total_seconds() / 3600

        if age_hours < 1:

            continue

        inside_zone = (
            low <= zone["zone_high"]
            and
            high >= zone["zone_low"]
        )

        if not inside_zone:

            continue

        # =====================================
        # RETEST VOLUME
        # =====================================

        if (
            delta > 40
            and
            close >= zone["zone_low"]
        ):

            zone["retested"] = True

            retest_points.append(
                (timestamp, close)
            )

            # CONNECTION

            connections.append({
                "x1": zone["timestamp"],
                "y1": zone["origin_price"],
                "x2": timestamp,
                "y2": close
            })

        # =====================================
        # CONFIRMATION
        # =====================================

        midpoint = (
            zone["zone_low"]
            +
            (
                zone["zone_high"]
                -
                zone["zone_low"]
            ) * 0.5
        )

        if (
            zone["retested"]
            and
            close > midpoint
            and
            price_change > 5
        ):

            zone["confirmed"] = True

            confirmation_points.append(
                (timestamp, close)
            )

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

confirmation_series = build_series(
    confirmation_points
)

# =====================================
# PLOTS
# =====================================

apds = [

    mpf.make_addplot(
        origin_series,
        type='scatter',
        marker='^',
        markersize=70
    ),

    mpf.make_addplot(
        retest_series,
        type='scatter',
        marker='o',
        markersize=100
    ),

    mpf.make_addplot(
        confirmation_series,
        type='scatter',
        marker='s',
        markersize=130
    )

]

# =====================================
# BUILD FIGURE
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
# DRAW CONNECTIONS
# =====================================

for c in connections:

    ax.plot(
        [c["x1"], c["x2"]],
        [c["y1"], c["y2"]],
        linewidth=1.5
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
    label='Инициатива'
)

ax.plot(
    [],
    [],
    marker='o',
    linestyle='None',
    markersize=10,
    label='Тест объема'
)

ax.plot(
    [],
    [],
    marker='s',
    linestyle='None',
    markersize=10,
    label='Подтверждение'
)

ax.plot(
    [],
    [],
    linewidth=2,
    label='Связь инициативы и теста'
)

ax.legend(
    loc='upper left',
    fontsize=12
)

mpf.show()
