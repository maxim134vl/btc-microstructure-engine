import pandas as pd
import mplfinance as mpf

print("\nSTOPPING VOLUME REPLAY STARTED\n")

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

stopping_points = []

test_points = []

confirmation_points = []

failed_points = []

connections = []

# =====================================
# REPLAY LOOP
# =====================================

for i in range(1, len(ohlc)):

    row = ohlc.iloc[i]

    prev = ohlc.iloc[i - 1]

    timestamp = ohlc.index[i]

    delta = row["Delta"]

    open_price = row["Open"]

    close = row["Close"]

    low = row["Low"]

    high = row["High"]

    price_change = row["PriceChange"]

    candle_range = high - low

    body_size = abs(close - open_price)

    lower_wick = (
        min(open_price, close)
        -
        low
    )

    # =====================================
    # STEP 1
    # STOPPING VOLUME
    # =====================================

    if (

        # strong negative movement before

        prev["PriceChange"] < -20

        and

        # strong reaction candle

        price_change > 10

        and

        # long lower wick

        lower_wick > body_size

        and

        # significant volume

        delta > 50

    ):

        zone = {

            "timestamp": timestamp,

            "stop_low": low,

            "stop_high": (
                low
                +
                lower_wick
            ),

            "confirmed": False,

            "tested": False
        }

        zones.append(
            zone
        )

        stopping_points.append(
            (timestamp, low)
        )

    # =====================================
    # STEP 2
    # TEST STOPPING ZONE
    # =====================================

    for zone in zones:

        age_hours = (
            timestamp - zone["timestamp"]
        ).total_seconds() / 3600

        if age_hours < 1:

            continue

        # =====================================
        # TEST
        # =====================================

        tested = (

            low <= zone["stop_high"]

            and

            close > zone["stop_low"]

        )

        if tested:

            zone["tested"] = True

            test_points.append(
                (timestamp, close)
            )

            connections.append({

                "x1": zone["timestamp"],
                "y1": zone["stop_low"],

                "x2": timestamp,
                "y2": close
            })

        # =====================================
        # FAILED TEST
        # =====================================

        if close < zone["stop_low"]:

            failed_points.append(
                (timestamp, close)
            )

        # =====================================
        # CONFIRMATION
        # =====================================

        midpoint = (
            zone["stop_low"]
            +
            (
                zone["stop_high"]
                -
                zone["stop_low"]
            ) * 0.5
        )

        if (

            zone["tested"]

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

stopping_series = build_series(
    stopping_points
)

test_series = build_series(
    test_points
)

confirmation_series = build_series(
    confirmation_points
)

failed_series = build_series(
    failed_points
)

# =====================================
# PLOTS
# =====================================

apds = [

    mpf.make_addplot(
        stopping_series,
        type='scatter',
        marker='^',
        markersize=80
    ),

    mpf.make_addplot(
        test_series,
        type='scatter',
        marker='o',
        markersize=100
    ),

    mpf.make_addplot(
        confirmation_series,
        type='scatter',
        marker='s',
        markersize=130
    ),

    mpf.make_addplot(
        failed_series,
        type='scatter',
        marker='x',
        markersize=120
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
# CONNECTIONS
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
    label='Stopping Volume'
)

ax.plot(
    [],
    [],
    marker='o',
    linestyle='None',
    markersize=10,
    label='Тест'
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
    marker='x',
    linestyle='None',
    markersize=10,
    label='Провал'
)

ax.plot(
    [],
    [],
    linewidth=2,
    label='Связь stopping volume и теста'
)

ax.legend(
    loc='upper left',
    fontsize=12
)

mpf.show()
