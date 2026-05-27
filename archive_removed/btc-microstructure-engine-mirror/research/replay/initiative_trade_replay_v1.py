import pandas as pd
import matplotlib.pyplot as plt

print("\nINITIATIVE TRADE REPLAY STARTED\n")

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
# RESAMPLE TO 1H
# =====================================

hourly = flow.resample(
    "1h",
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
# POSITION STATE
# =====================================

position = None

trades = []

# =====================================
# CHART DATA
# =====================================

price_points = []

entries = []

exits = []

stops = []

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

        zone_low = price - 25

        zone_high = price + 25

        initiative = {
            "timestamp": timestamp,
            "direction": direction,
            "origin_price": price,
            "zone_low": zone_low,
            "zone_high": zone_high,
            "state": "ACTIVE"
        }

        initiative_memory.append(
            initiative
        )

        # =====================================
        # ENTRY LOGIC
        # =====================================

        if position is None:

            if direction == "BUY":

                stop_price = zone_low - 10

                position = {
                    "side": "LONG",
                    "entry_price": price,
                    "entry_time": timestamp,
                    "stop_price": stop_price
                }

                entries.append(
                    (timestamp, price)
                )

            elif direction == "SELL":

                stop_price = zone_high + 10

                position = {
                    "side": "SHORT",
                    "entry_price": price,
                    "entry_time": timestamp,
                    "stop_price": stop_price
                }

                entries.append(
                    (timestamp, price)
                )

        # =====================================
        # TAKE PROFIT
        # =====================================

        elif position is not None:

            # LONG EXIT

            if (
                position["side"] == "LONG"
                and
                direction == "SELL"
            ):

                pnl = (
                    price
                    -
                    position["entry_price"]
                )

                trades.append({
                    "side": "LONG",
                    "entry": position["entry_price"],
                    "exit": price,
                    "pnl": pnl
                })

                exits.append(
                    (timestamp, price)
                )

                position = None

            # SHORT EXIT

            elif (
                position["side"] == "SHORT"
                and
                direction == "BUY"
            ):

                pnl = (
                    position["entry_price"]
                    -
                    price
                )

                trades.append({
                    "side": "SHORT",
                    "entry": position["entry_price"],
                    "exit": price,
                    "pnl": pnl
                })

                exits.append(
                    (timestamp, price)
                )

                position = None

    # =====================================
    # STOP LOGIC
    # =====================================

    if position is not None:

        # LONG STOP

        if (
            position["side"] == "LONG"
            and
            price <= position["stop_price"]
        ):

            pnl = (
                position["stop_price"]
                -
                position["entry_price"]
            )

            trades.append({
                "side": "LONG",
                "entry": position["entry_price"],
                "exit": position["stop_price"],
                "pnl": pnl
            })

            stops.append(
                (timestamp, position["stop_price"])
            )

            position = None

        # SHORT STOP

        elif (
            position["side"] == "SHORT"
            and
            price >= position["stop_price"]
        ):

            pnl = (
                position["entry_price"]
                -
                position["stop_price"]
            )

            trades.append({
                "side": "SHORT",
                "entry": position["entry_price"],
                "exit": position["stop_price"],
                "pnl": pnl
            })

            stops.append(
                (timestamp, position["stop_price"])
            )

            position = None

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

# ENTRIES

if entries:

    entry_df = pd.DataFrame(
        entries,
        columns=["timestamp", "price"]
    )

    plt.scatter(
        entry_df["timestamp"],
        entry_df["price"],
        marker="^",
        s=120,
        label="ENTRY"
    )

# EXITS

if exits:

    exit_df = pd.DataFrame(
        exits,
        columns=["timestamp", "price"]
    )

    plt.scatter(
        exit_df["timestamp"],
        exit_df["price"],
        marker="o",
        s=120,
        label="TAKE PROFIT"
    )

# STOPS

if stops:

    stop_df = pd.DataFrame(
        stops,
        columns=["timestamp", "price"]
    )

    plt.scatter(
        stop_df["timestamp"],
        stop_df["price"],
        marker="x",
        s=150,
        label="STOP"
    )

# =====================================
# FINALIZE
# =====================================

plt.title(
    "Initiative Trade Replay"
)

plt.xlabel("Time")

plt.ylabel("BTC Price")

plt.legend()

plt.grid(True)

plt.tight_layout()

plt.show()

# =====================================
# RESULTS
# =====================================

print("\n================================")
print("TRADE SUMMARY")
print("================================\n")

if len(trades) == 0:

    print("NO TRADES")

else:

    trades_df = pd.DataFrame(trades)

    total_trades = len(trades_df)

    wins = len(
        trades_df[
            trades_df["pnl"] > 0
        ]
    )

    losses = len(
        trades_df[
            trades_df["pnl"] <= 0
        ]
    )

    total_pnl = trades_df["pnl"].sum()

    avg_pnl = trades_df["pnl"].mean()

    winrate = (
        wins / total_trades
    ) * 100

    print(f"TOTAL TRADES: {total_trades}")

    print(f"WINS: {wins}")

    print(f"LOSSES: {losses}")

    print(f"WINRATE: {winrate:.2f}%")

    print(f"TOTAL PNL: {total_pnl:.2f}")

    print(f"AVG TRADE: {avg_pnl:.2f}")

    print("\nLAST TRADES:\n")

    print(
        trades_df.tail(10)
    )
