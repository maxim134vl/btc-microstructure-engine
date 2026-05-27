import pandas as pd
import mplfinance as mpf

print("\nBUY STRUCTURE REPLAY STARTED\n")

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

buy_zones = []

# =====================================
# VISUAL EVENTS
# =====================================

origin_points = []

retest_points = []

confirmation_points = []

failed_points = []

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
    # BUY IMPULSE
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
            "confirmed": False,
            "failed": False
        }

        buy_zones.append(
            zone
        )

        origin_points.append(
            (timestamp, close)
        )

    # =====================================
    # STEP 2
    # RETEST
    # =====================================

    for zone in buy_zones:

        age_minutes = (
            timestamp - zone["timestamp"]
        ).total_seconds() / 60

        if age_minutes < 30:

            continue

        inside_zone = (
            low <= zone["zone_high"]
            and
            high >= zone["zone_low"]
        )

        if not inside_zone:

            continue

        # =====================================
        # FAILED DEFENSE
        # =====================================

        if close < zone["zone_low"]:

            zone["failed"] = True

            failed_points.append(
                (timestamp, close)
            )

            continue

        # =====================================
        # RETEST DETECTED
        # =====================================

        if (
            low >= zone["zone_low"]
            and
            close > zone["origin_price"]
        ):

            zone["retested"] = True

            retest_points.append(
                (timestamp, close)
            )

        # =====================================
        # CONFIRMATION
        # =====================================

        if (
            zone["retested"]
            and
            close > zone["zone_high"]
            and
            price_change > 10
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

failed_series = build_series(
    failed_points
)

# =====================================
# PLOTS
# =====================================

apds = [

    mpf.make_addplot(
        origin_series,
        type='scatter',
        marker='^',
        markersize=60
    ),

    mpf.make_addplot(
        retest_series,
        type='scatter',
        marker='o',
        markersize=90
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
# CHART
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

ax.legend(
    loc='upper left',
    fontsize=12
)

mpf.show()
