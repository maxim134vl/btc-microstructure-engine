import pandas as pd
import mplfinance as mpf

print("\nCLEAN STOPPING TEST V2 STARTED\n")

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
    "sell_volume": "sum"
})

ohlc.columns = [
    "Open",
    "High",
    "Low",
    "Close",
    "Delta",
    "BuyVolume",
    "SellVolume"
]

ohlc = ohlc.dropna()

# =====================================
# MEMORY
# =====================================

zones = []

# =====================================
# VISUALS
# =====================================

stopping_points = []

successful_tests = []

failed_tests = []

connections = []

# =====================================
# LOOP
# =====================================

for i in range(len(ohlc)):

    row = ohlc.iloc[i]

    timestamp = ohlc.index[i]

    open_price = row["Open"]

    close = row["Close"]

    low = row["Low"]

    high = row["High"]

    delta = row["Delta"]

    volume = (
        row["BuyVolume"]
        +
        row["SellVolume"]
    )

    body = abs(close - open_price)

    lower_wick = (
        min(open_price, close)
        -
        low
    )

    # =====================================
    # STOPPING VOLUME
    # =====================================

    stopping_volume = (

        lower_wick > body * 1.5

        and

        close > open_price

        and

        delta > 50

    )

    if stopping_volume:

        wick_midpoint = (
            low
            +
            lower_wick * 0.5
        )

        zone = {

            "timestamp": timestamp,

            "zone_low": low,

            "zone_high": wick_midpoint
        }

        zones.append(zone)

        stopping_points.append(
            (timestamp, low)
        )

    # =====================================
    # TESTS
    # =====================================

    for zone in zones:

        age_hours = (
            timestamp - zone["timestamp"]
        ).total_seconds() / 3600

        if age_hours < 1:

            continue

        # =====================================
        # MUST RETURN INTO STOPPING WICK
        # =====================================

        returned_to_zone = (

            low <= zone["zone_high"]

            and

            low >= zone["zone_low"]

        )

        if not returned_to_zone:

            continue

        # =====================================
        # STOPPING REACTION AGAIN
        # =====================================

        test_lower_wick = (
            min(open_price, close)
            -
            low
        )

        successful_reaction = (

            test_lower_wick > body

            and

            close > open_price

            and

            close > zone["zone_low"]

        )

        # =====================================
        # SUCCESSFUL TEST
        # =====================================

        if successful_reaction:

            successful_tests.append(
                (timestamp, low)
            )

            connections.append({

                "x1": zone["timestamp"],
                "y1": zone["zone_low"],

                "x2": timestamp,
                "y2": low
            })

        # =====================================
        # FAILED TEST
        # =====================================

        elif close < zone["zone_low"]:

            failed_tests.append(
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

success_series = build_series(
    successful_tests
)

failed_series = build_series(
    failed_tests
)

# =====================================
# PLOTS
# =====================================

apds = [

    mpf.make_addplot(
        stopping_series,
        type='scatter',
        marker='^',
        markersize=140,
        color='blue'
    ),

    mpf.make_addplot(
        success_series,
        type='scatter',
        marker='o',
        markersize=120,
        color='green'
    ),

    mpf.make_addplot(
        failed_series,
        type='scatter',
        marker='x',
        markersize=140,
        color='red'
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
    label='Stopping Volume'
)

ax.plot(
    [],
    [],
    marker='o',
    linestyle='None',
    markersize=10,
    color='green',
    label='Successful Test'
)

ax.plot(
    [],
    [],
    marker='x',
    linestyle='None',
    markersize=10,
    color='red',
    label='Failed Test'
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
