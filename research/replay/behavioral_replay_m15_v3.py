import pandas as pd
import mplfinance as mpf

print("\nBEHAVIORAL REPLAY V3 STARTED\n")

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
    "15min",
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

candidate_zones = []

confirmed_zones = []

# =====================================
# VISUAL EVENTS
# =====================================

candidate_points = []

test_points = []

confirmed_points = []

rejected_points = []

# =====================================
# REPLAY LOOP
# =====================================

for i in range(len(ohlc)):

    row = ohlc.iloc[i]

    timestamp = ohlc.index[i]

    delta = row["Delta"]

    price = row["Close"]

    price_change = row["PriceChange"]

    volume_value = (
        row["BuyVolume"]
        +
        row["SellVolume"]
    )

    # =====================================
    # STEP 1
    # SIGNIFICANT VOLUME + REACTION
    # =====================================

    if (
        abs(delta) > 70
        and
        abs(price_change) > 15
    ):

        direction = (
            "BUY"
            if delta > 0
            else "SELL"
        )

        zone = {
            "timestamp": timestamp,
            "direction": direction,
            "origin_price": price,
            "zone_low": price - 25,
            "zone_high": price + 25,
            "tested": False,
            "confirmed": False
        }

        candidate_zones.append(
            zone
        )

        candidate_points.append(
            (timestamp, price)
        )

    # =====================================
    # STEP 2
    # PRICE RETURNS TO ZONE
    # =====================================

    for zone in candidate_zones:

        inside_zone = (
            price >= zone["zone_low"]
            and
            price <= zone["zone_high"]
        )

        if not inside_zone:

            continue

        age_minutes = (
            timestamp - zone["timestamp"]
        ).total_seconds() / 60

        if age_minutes < 30:

            continue

        # =====================================
        # BUY STRUCTURE
        # =====================================

        if zone["direction"] == "BUY":

            # RETEST

            if (
                delta > 40
                and
                price_change > 10
            ):

                zone["tested"] = True

                test_points.append(
                    (timestamp, price)
                )

            # CONFIRMATION

            if (
                zone["tested"]
                and
                price_change > 20
            ):

                zone["confirmed"] = True

                confirmed_points.append(
                    (timestamp, price)
                )

                confirmed_zones.append(
                    zone
                )

            # REJECTION

            elif price_change < -25:

                rejected_points.append(
                    (timestamp, price)
                )

        # =====================================
        # SELL STRUCTURE
        # =====================================

        elif zone["direction"] == "SELL":

            # RETEST

            if (
                delta < -40
                and
                price_change < -10
            ):

                zone["tested"] = True

                test_points.append(
                    (timestamp, price)
                )

            # CONFIRMATION

            if (
                zone["tested"]
                and
                price_change < -20
            ):

                zone["confirmed"] = True

                confirmed_points.append(
                    (timestamp, price)
                )

                confirmed_zones.append(
                    zone
                )

            # REJECTION

            elif price_change > 25:

                rejected_points.append(
                    (timestamp, price)
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

candidate_series = build_series(
    candidate_points
)

test_series = build_series(
    test_points
)

confirmed_series = build_series(
    confirmed_points
)

rejected_series = build_series(
    rejected_points
)

# =====================================
# PLOTS
# =====================================

apds = [

    mpf.make_addplot(
        candidate_series,
        type='scatter',
        marker='^',
        markersize=50
    ),

    mpf.make_addplot(
        test_series,
        type='scatter',
        marker='o',
        markersize=90
    ),

    mpf.make_addplot(
        confirmed_series,
        type='scatter',
        marker='s',
        markersize=120
    ),

    mpf.make_addplot(
        rejected_series,
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
    label='Кандидат'
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
    label='Отмена'
)

ax.legend(
    loc='upper left',
    fontsize=12
)

mpf.show()
