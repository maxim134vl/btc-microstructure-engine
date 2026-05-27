import pandas as pd

print("\nDEBUG ABSORPTION LOGIC\n")

initiative = pd.read_parquet("initiative_memory.parquet")
flow = pd.read_parquet("multi_exchange_flow.parquet")

latest_initiative = initiative.iloc[-1]

recent = flow.tail(20)

delta = recent["delta"].sum()

volume_value = (
    recent["buy_volume"].sum()
    +
    recent["sell_volume"].sum()
)

price_change = recent["price_change"].sum()

direction = latest_initiative["direction"]

print("LATEST INITIATIVE")
print(latest_initiative)

print("\nFLOW CONTEXT")
print(f"DELTA: {round(delta, 2)}")
print(f"VOLUME: {round(volume_value, 2)}")
print(f"PRICE CHANGE: {round(price_change, 2)}")

print("\nINTERPRETATION")

# BUY INITIATIVE ABSORPTION

if direction == "BUY":

    if delta > 0 and volume_value > 25:

        if abs(price_change) < 10:

            print(
                "Buy initiative appears absorbed. "
                "Aggressive buying fails to generate meaningful price expansion."
            )

        else:

            print(
                "Buy initiative still generating directional response."
            )

# SELL INITIATIVE ABSORPTION

elif direction == "SELL":

    if delta < 0 and volume_value > 25:

        if abs(price_change) < 10:

            print(
                "Sell initiative appears absorbed. "
                "Aggressive selling fails to generate meaningful downside continuation."
            )

        else:

            print(
                "Sell initiative still generating directional response."
            )
