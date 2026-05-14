import pandas as pd
import matplotlib.pyplot as plt

print("\nHISTORICAL BEHAVIORAL REPLAY STARTED\n")

# =====================================
# LOAD HISTORICAL FLOW
# =====================================

flow = pd.read_parquet(
    "multi_exchange_flow.parquet"
)

flow["timestamp"] = pd.to_datetime(
    flow["timestamp"]
)

flow = flow.sort_values("timestamp")

# =====================================
# RESAMPLE TO 1H
# =====================================

hourly = flow.resample(
    "1H",
    on="timestamp"
).agg({
    "delta": "sum",
    "buy_volume": "sum",
    "sell_volume": "sum",
    "avg_price": "last",
    "price_change": "sum",
    "efficiency": "mean"
}).dropna()

# =====================================
# MEMORY
# =====================================

initiative_memory = []

# =====================================
# CHART DATA
# =====================================

price_points = []

buy_signals = []

sell_signals = []

tested_points = []

rejected_points = []

# =====================================
# REPLAY LOOP
# =====================================

for i in range(len(hourly)):

    current = hourly.iloc[i]

    timestamp = hourly.index[i]

    delta = current["delta"]

    volume_value = (
        current["buy_volume"]
        +
        current["sell_volume"]
    )

    price = current["avg_price"]

    price_change = current["price_change"]

    efficiency = current["efficiency"]

    price_points.append(
        (timestamp, price)
    )

    # =====================================
    # DETECT INITIATIVE
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
            "successful_tests": 0
        }

        initiative_memory.append(
            initiative
        )

        if direction == "BUY":

            buy_signals.append(
                (timestamp, price)
            )

        else:

            sell_signals.append(
                (timestamp, price)
            )

    # =====================================
    # INITIATIVE STATE ENGINE
    # =====================================

    for initiative in initiative_memory:

        if initiative["state"] == "FAILED":

            continue

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

        # cooldown protection

        if hours_alive < 1:

            continue

        # =================================
        # BUY INITIATIVE
        # =================================

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

                initiative[
                    "successful_tests"
                ] += 1

                tested_points.append(
                    (timestamp, price)
                )

            # FAILURE

            elif delta < -50:

                initiative["state"] = "FAILED"

        # =================================
        # SELL INITIATIVE
        # =================================

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

                initiative[
                    "successful_tests"
                ] += 1

                tested_points.append(
                    (timestamp, price)
                )

            # FAILURE

            elif delta > 50:

                initiative["state"] = "FAILED"

# =====================================
# BUILD CHART
# =====================================

price_df = pd.DataFrame(
    price_points,
    columns=["timestamp", "price"]
)

plt.figure(figsize=(20, 10))

# PRICE

plt.plot(
    price_df["timestamp"],
    price_df["price"],
    linewidth=1.5,
    label="BTC PRICE"
)

# BUY INITIATIVES

if buy_signals:

    buy_df = pd.DataFrame(
        buy_signals,
        columns=["timestamp", "price"]
    )

    plt.scatter(
        buy_df["timestamp"],
        buy_df["price"],
        marker="^",
        s=120,
        label="BUY INITIATIVE"
    )

# SELL INITIATIVES

if sell_signals:

    sell_df = pd.DataFrame(
        sell_signals,
        columns=["timestamp", "price"]
    )

    plt.scatter(
        sell_df["timestamp"],
        sell_df["price"],
        marker="v",
        s=120,
        label="SELL INITIATIVE"
    )

# TESTED

if tested_points:

    tested_df = pd.DataFrame(
        tested_points,
        columns=["timestamp", "price"]
    )

    plt.scatter(
        tested_df["timestamp"],
        tested_df["price"],
        marker="o",
        s=100,
        label="SUCCESSFUL TEST"
    )

# REJECTED

if rejected_points:

    rejected_df = pd.DataFrame(
        rejected_points,
        columns=["timestamp", "price"]
    )

    plt.scatter(
        rejected_df["timestamp"],
        rejected_df["price"],
        marker="x",
        s=140,
        label="REJECTED"
    )

# =====================================
# FINALIZE
# =====================================

plt.title(
    "Behavioral Replay Engine - 1H Replay"
)

plt.xlabel("Time")

plt.ylabel("BTC Price")

plt.legend()

plt.grid(True)

plt.tight_layout()

plt.show()

# =====================================
# SUMMARY
# =====================================

print("\n================================")
print("REPLAY SUMMARY")
print("================================\n")

print(
    f"TOTAL INITIATIVES: {len(initiative_memory)}"
)

buy_count = len([
    x for x in initiative_memory
    if x["direction"] == "BUY"
])

sell_count = len([
    x for x in initiative_memory
    if x["direction"] == "SELL"
])

tested_count = len([
    x for x in initiative_memory
    if x["state"] == "TESTED"
])

rejected_count = len([
    x for x in initiative_memory
    if x["state"] == "REJECTED"
])

failed_count = len([
    x for x in initiative_memory
    if x["state"] == "FAILED"
])

print(f"BUY INITIATIVES: {buy_count}")

print(f"SELL INITIATIVES: {sell_count}")

print(f"SUCCESSFUL TESTS: {tested_count}")

print(f"REJECTIONS: {rejected_count}")

print(f"FAILED INITIATIVES: {failed_count}")
