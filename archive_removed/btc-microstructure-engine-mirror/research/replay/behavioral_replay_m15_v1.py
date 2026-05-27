import pandas as pd
import mplfinance as mpf

print("\nBEHAVIORAL REPLAY M15 STARTED\n")

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
# BUILD M15 OHLC
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
# VISUAL EVENTS
# =====================================

initiative_points = []

test_points = []

defended_points = []

absorbed_points = []

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

        initiative_points.append(
            (timestamp, price)
        )

    # =====================================
    # STATE EVOLUTION
    # =====================================

    for initiative in initiative_memory:

        inside_zone = (
            price >= initiative["zone_low"]
            and
            price <= initiative["zone_high"]
        )

        if not inside_zone:

            continue

        age_minutes = (
            timestamp - initiative["timestamp"]
        ).total_seconds() / 60

        if age_minutes < 15:

            continue

        # =====================================
        # BUY LOGIC
        # =====================================

        if initiative["direction"] == "BUY":

            # TEST

            if (
                delta > 50
                and
                price_change > 15
            ):

                initiative["state"] = "TEST"

                initiative["tests"] += 1

                test_points.append(
                    (timestamp, price)
                )

            # DEFENSE

            if (
                initiative["tests"] >= 2
                and
                delta > 50
                and
                price_change > 10
            ):

                initiative["state"] = "DEFENDED"

                defended_points.append(
                    (timestamp, price)
                )

            # ABSORPTION

            elif (
                delta > 0
                and
                abs(price_change) < 5
            ):

                initiative["state"] = "ABSORBED"

                absorbed_points.append(
                    (timestamp, price)
                )

            # REJECTION

            elif price_change < -25:

                initiative["state"] = "REJECTED"

                rejected_points.append(
                    (timestamp, price)
                )

        # =====================================
        # SELL LOGIC
        # =====================================

        elif initiative["direction"] == "SELL":

            # TEST

            if (
                delta < -50
                and
                price_change < -15
            ):

                initiative["state"] = "TEST"

                initiative["tests"] += 1

                test_points.append(
                    (timestamp, price)
                )

            # DEFENSE

            if (
                initiative["tests"] >= 2
                and
                delta < -50
                and
                price_change < -10
            ):

                initiative["state"] = "DEFENDED"

                defended_points.append(
                    (timestamp, price)
                )

            # ABSORPTION

            elif (
                delta < 0
                and
                abs(price_change) < 5
            ):

                initiative["state"] = "ABSORBED"

                absorbed_points.append(
                    (timestamp, price)
                )

            # REJECTION

            elif price_change > 25:

                initiative["state"] = "REJECTED"

                rejected_points.append(
                    (timestamp, price)
                )

# =====================================
# SERIES BUILDER
# =====================================

def build_series(points):

    s = pd.Series(
        index=ohlc.index,
        dtype=float
    )

    for ts, price in points:

        s.loc[ts] = price

    return s

initiative_series = build_series(
    initiative_points
)

test_series = build_series(
    test_points
)

defended_series = build_series(
    defended_points
)

absorbed_series = build_series(
    absorbed_points
)

rejected_series = build_series(
    rejected_points
)

# =====================================
# PLOTS
# =====================================

apds = [

    mpf.make_addplot(
        initiative_series,
        type='scatter',
        marker='^',
        markersize=70
    ),

    mpf.make_addplot(
        test_series,
        type='scatter',
        marker='o',
        markersize=90
    ),

    mpf.make_addplot(
        defended_series,
        type='scatter',
        marker='s',
        markersize=110
    ),

    mpf.make_addplot(
        absorbed_series,
        type='scatter',
        marker='D',
        markersize=70
    ),

    mpf.make_addplot(
        rejected_series,
        type='scatter',
        marker='x',
        markersize=140
    )

]

# =====================================
# CHART
# =====================================

mpf.plot(
    ohlc,
    type='candle',
    style='charles',
    title='Поведенческий Replay Аукциона',
    volume=False,
    addplot=apds,
    figsize=(20, 12),
    tight_layout=True
)

print("\n================================")
print("ЛЕГЕНДА")
print("================================\n")

print("▲ = Инициатива")
print("○ = Тест")
print("■ = Защита")
print("◆ = Поглощение")
print("✖ = Ложный пробой / rejection")
