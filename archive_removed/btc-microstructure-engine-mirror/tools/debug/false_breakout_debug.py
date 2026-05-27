import pandas as pd

print("\nFALSE BREAKOUT DEBUG\n")

initiative = pd.read_parquet("initiative_memory.parquet")
flow = pd.read_parquet("multi_exchange_flow.parquet")

latest = initiative.iloc[-1]

recent = flow.tail(20)

delta = recent["delta"].sum()

price_change = recent["price_change"].sum()

volume_value = (
    recent["buy_volume"].sum()
    +
    recent["sell_volume"].sum()
)

direction = latest["direction"]

print("LATEST INITIATIVE")
print(latest)

print("\nFLOW CONTEXT")
print(f"DELTA: {round(delta, 2)}")
print(f"PRICE CHANGE: {round(price_change, 2)}")
print(f"VOLUME: {round(volume_value, 2)}")

print("\nFALSE BREAKOUT ANALYSIS")

# BUY FALSE BREAKOUT

if direction == "BUY":

    if delta < -100 and price_change < -20:

        print(
            "Bullish breakout appears rejected."
        )

        print(
            "Price failed to sustain auction above initiative zone."
        )

        print(
            "Aggressive selling reclaimed prior breakout area."
        )

# SELL FALSE BREAKOUT

elif direction == "SELL":

    if delta > 100 and price_change > 20:

        print(
            "Bearish breakdown appears rejected."
        )

        print(
            "Price failed to sustain auction below initiative zone."
        )

        print(
            "Aggressive buying reclaimed prior breakdown area."
        )

else:

    print(
        "No false breakout behavior detected."
    )
