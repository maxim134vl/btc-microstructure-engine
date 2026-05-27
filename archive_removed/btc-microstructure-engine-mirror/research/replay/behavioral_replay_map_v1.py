import pandas as pd
import mplfinance as mpf

print("\nBEHAVIORAL REPLAY MAP STARTED\n")

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
    "price_change": "sum",
    "efficiency": "mean"
})

ohlc.columns = [
    "Open",
    "High",
    "Low",
    "Close",
    "Delta",
    "BuyVolume",
    "SellVolume",
    "PriceChange",
    "Efficiency"
]

ohlc = ohlc.dropna()

# =====================================
# MEMORY
# =====================================

initiative_memory = []

# =====================================
# SIGNAL STORAGE
# =====================================

buy_initiatives = []

sell_initiatives = []

tested_points = []

rejected_points = []

absorbed_points = []

defended_points = []

# =====================================
# REPLAY LOOP
# =====================================

for i in range(len(ohlc)):

    row = ohlc.iloc[i]

    timestamp = ohlc.index[i]

    delta = row["Delta"]

    price = row["Close"]

    price_change = row["PriceChange"]

    efficiency = row["Efficiency"]

    volume_value = (
        row["BuyVolume"]
        +
        row["SellVolume"]
    )

    # =====================================
    # INITIATIVE DETECTION
    # =====================================

    if abs(delta) > 70:

        direction = (
            "BUY"
            if delta > 0
            else "SELL"
        )

        initiative = {
            "timestamp": timestamp,
            "direction": direction,
            "origin_price": price,
            "zone_low": price - 25,
            "zone_high": price + 25,
            "state": "ACTIVE",
            "tests": 0
        }

        initiative_memory.append(
            initiative
        )

        if direction == "BUY":

            buy_initiatives.append(
                (timestamp, price)
            )

        else:

            sell_initiatives.append(
                (timestamp, price)
            )

    # =====================================
    # STATE TRANSITIONS
    # =====================================

    for initiative in initiative_memory:

        inside_zone = (
            price >= initiative["zone_low"]
            and
            price <= initiative["zone_high"]
        )

        if not inside_zone:

            continue

        hours_alive = (
            timestamp - initiative["timestamp"]
        ).total_seconds() / 3600

        if hours_alive < 1:

            continue

        # =====================================
        # BUY LOGIC
        # =====================================

        if initiative["direction"] == "BUY":

            # REJECTION

            if price_change < -50:

                initiative["state"] = "REJECTED"

                rejected_points.append(
                    (timestamp, price)
                )

            # SUCCESSFUL TEST

            elif (
                delta > 50
                and
                price_change > 20
            ):

                initiative["state"] = "TESTED"

                initiative["tests"] += 1

                tested_points.append(
                    (timestamp, price)
                )

            # ABSORPTION

            elif (
                delta > 0
                and
                abs(price_change) < 10
            ):

                initiative["state"] = "ABSORBED"

                absorbed_points.append(
                    (timestamp, price)
                )

            # DEFENDED

            elif (
                delta > 0
                and
                price_change > 10
            ):

                initiative["state"] = "DEFENDED"

                defended_points.append(
                    (timestamp, price)
                )

        # =====================================
        # SELL LOGIC
        # =====================================

        elif initiative["direction"] == "SELL":

            # REJECTION

            if price_change > 50:

                initiative["state"] = "REJECTED"

                rejected_points.append(
                    (timestamp, price)
                )

            # SUCCESSFUL TEST

            elif (
                delta < -50
                and
                price_change < -20
            ):

                initiative["state"] = "TESTED"

                initiative["tests"] += 1

                tested_points.append(
                    (timestamp, price)
                )

            # ABSORPTION

            elif (
                delta < 0
                and
                abs(price_change) < 10
            ):

                initiative["state"] = "ABSORBED"

                absorbed_points.append(
                    (timestamp, price)
                )

            # DEFENDED

            elif (
                delta < 0
                and
                price_change < -10
            ):

                initiative["state"] = "DEFENDED"

                defended_points.append(
                    (timestamp, price)
                )

# =====================================
# BUILD SIGNAL SERIES
# =====================================

def build_series(points):

    s = pd.Series(
        index=ohlc.index,
        dtype=float
    )

    for ts, price in points:

        s.loc[ts] = price

    return s

buy_series = build_series(
    buy_initiatives
)

sell_series = build_series(
    sell_initiatives
)

tested_series = build_series(
    tested_points
)

rejected_series = build_series(
    rejected_points
)

absorbed_series = build_series(
    absorbed_points
)

defended_series = build_series(
    defended_points
)

# =====================================
# PLOTS
# =====================================

apds = [

    mpf.make_addplot(
        buy_series,
        type='scatter',
        marker='^',
        markersize=120,
        label='BUY INITIATIVE'
    ),

    mpf.make_addplot(
        sell_series,
        type='scatter',
        marker='v',
        markersize=120,
        label='SELL INITIATIVE'
    ),

    mpf.make_addplot(
        tested_series,
        type='scatter',
        marker='o',
        markersize=90,
        label='SUCCESSFUL TEST'
    ),

    mpf.make_addplot(
        rejected_series,
        type='scatter',
        marker='x',
        markersize=140,
        label='REJECTION'
    ),

    mpf.make_addplot(
        absorbed_series,
        type='scatter',
        marker='D',
        markersize=80,
        label='ABSORPTION'
    ),

    mpf.make_addplot(
        defended_series,
        type='scatter',
        marker='s',
        markersize=80,
        label='DEFENDED'
    )

]

# =====================================
# SHOW CHART
# =====================================

mpf.plot(
    ohlc,
    type='candle',
    style='charles',
    title='Behavioral Auction Replay',
    volume=False,
    addplot=apds,
    figsize=(20, 11),
    tight_layout=True
)

print("\nREPLAY COMPLETE\n")
