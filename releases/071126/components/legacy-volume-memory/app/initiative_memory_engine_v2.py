import time
import pandas as pd
from datetime import datetime

print("\nINITIATIVE MEMORY ENGINE STARTED\n")

initiative_memory = []

while True:

    try:

        flow = pd.read_parquet("multi_exchange_flow.parquet")

        latest = flow.iloc[-1]

        price = latest["price"]
        delta = latest["total_delta"]
        volume_value = latest["total_volume"]

        print("\n================================")
        print("INITIATIVE MEMORY ENGINE")
        print(datetime.utcnow())
        print("================================\n")

        # DETECT NEW INITIATIVE

        if abs(delta) > 100 and volume_value > 50:

            direction = "BUY" if delta > 0 else "SELL"

            zone_low = round(price - 25, 2)
            zone_high = round(price + 25, 2)

            initiative = {
                "timestamp": datetime.utcnow(),
                "direction": direction,
                "zone_low": zone_low,
                "zone_high": zone_high,
                "origin_price": price,
                "delta": delta,
                "volume": volume_value,
                "state": "ACTIVE"
            }

            initiative_memory.append(initiative)

            print(f"NEW {direction} INITIATIVE DETECTED")
            print(f"ZONE: {zone_low} - {zone_high}")

        # CHECK REVISITS

        for initiative in initiative_memory:

            if initiative["state"] == "FAILED":
                continue

            inside_zone = (
                price >= initiative["zone_low"]
                and
                price <= initiative["zone_high"]
            )

            if inside_zone:

                if initiative["direction"] == "BUY":

                    if delta > 0:

                        initiative["state"] = "DEFENDED"

                        print("\nBUY INITIATIVE DEFENDED")
                        print(f"ZONE: {initiative['zone_low']} - {initiative['zone_high']}")

                    elif delta < -50:

                        initiative["state"] = "FAILED"

                        print("\nBUY INITIATIVE FAILED")
                        print(f"ZONE LOST: {initiative['zone_low']} - {initiative['zone_high']}")

                elif initiative["direction"] == "SELL":

                    if delta < 0:

                        initiative["state"] = "DEFENDED"

                        print("\nSELL INITIATIVE DEFENDED")
                        print(f"ZONE: {initiative['zone_low']} - {initiative['zone_high']}")

                    elif delta > 50:

                        initiative["state"] = "FAILED"

                        print("\nSELL INITIATIVE FAILED")
                        print(f"ZONE LOST: {initiative['zone_low']} - {initiative['zone_high']}")

        # SAVE MEMORY

        memory_df = pd.DataFrame(initiative_memory)

        memory_df.to_parquet(
            "initiative_memory.parquet",
            index=False
        )

        print(f"\nACTIVE INITIATIVES: {len(memory_df)}")

        time.sleep(60)

    except Exception as e:

        print("\nERROR")
        print(e)

        time.sleep(10)
