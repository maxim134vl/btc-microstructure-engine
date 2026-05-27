import time
import pandas as pd
from datetime import datetime

print("\nINITIATIVE MEMORY ENGINE STARTED\n")

initiative_memory = []

while True:

    try:

        flow = pd.read_parquet("multi_exchange_flow.parquet")

        recent = flow.tail(20)

        delta = recent["delta"].sum()

        volume_value = (
            recent["buy_volume"].sum()
            +
            recent["sell_volume"].sum()
        )

        price = recent.iloc[-1]["avg_price"]

        price_change = recent["price_change"].sum()

        efficiency = recent["efficiency"].mean()

        print("\n================================")
        print("INITIATIVE MEMORY ENGINE")
        print(datetime.utcnow())
        print("================================\n")

        print(f"PRICE: {round(price, 2)}")
        print(f"DELTA: {round(delta, 2)}")
        print(f"VOLUME: {round(volume_value, 2)}")
        print(f"PRICE CHANGE: {round(price_change, 2)}")
        print(f"EFFICIENCY: {round(efficiency, 2)}")

        # DETECT INITIATIVE

        if abs(delta) > 100 and volume_value > 25:

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
                "state": "ACTIVE",
                "successful_tests": 0
            }

            initiative_memory.append(initiative)

            print(f"\nNEW {direction} INITIATIVE DETECTED")
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

                # RETEST COOLDOWN

                created_at = pd.to_datetime(
                    initiative["timestamp"]
                )

                seconds_alive = (
                    datetime.utcnow() - created_at
                ).total_seconds()

                if seconds_alive < 180:

                    continue

                # BUY INITIATIVE

                if initiative["direction"] == "BUY":

                    # REJECTION

                    if price_change < -20:

                        initiative["state"] = "REJECTED"

                        print("\nBUY INITIATIVE REJECTED")
                        print(
                            "Aggressive buying failed to sustain upside auction."
                        )

                    # SUCCESSFUL TEST

                    elif (
                        delta > 50
                        and
                        volume_value > 100
                        and
                        efficiency > 0
                        and
                        price_change > 20
                    ):

                        initiative["state"] = "TESTED"

                        initiative["successful_tests"] += 1

                        print("\nBUY INITIATIVE SUCCESSFULLY TESTED")
                        print(
                            f"SUCCESSFUL TESTS: {initiative['successful_tests']}"
                        )

                    # HEALTHY DEFENSE

                    elif delta > 0 and price_change > 10:

                        initiative["state"] = "DEFENDED"

                        print("\nBUY INITIATIVE DEFENDED")
                        print(
                            f"ZONE: {initiative['zone_low']} - {initiative['zone_high']}"
                        )

                    # ABSORPTION

                    elif delta > 0 and abs(price_change) < 10:

                        initiative["state"] = "ABSORBED"

                        print("\nBUY INITIATIVE ABSORBED")
                        print(
                            "Aggressive buying fails to produce meaningful upside response."
                        )

                    # FAILURE

                    elif delta < -50:

                        initiative["state"] = "FAILED"

                        print("\nBUY INITIATIVE FAILED")
                        print(
                            f"ZONE LOST: {initiative['zone_low']} - {initiative['zone_high']}"
                        )

                # SELL INITIATIVE

                elif initiative["direction"] == "SELL":

                    # REJECTION

                    if price_change > 20:

                        initiative["state"] = "REJECTED"

                        print("\nSELL INITIATIVE REJECTED")
                        print(
                            "Aggressive selling failed to sustain downside auction."
                        )

                    # SUCCESSFUL TEST

                    elif (
                        delta < -50
                        and
                        volume_value > 100
                        and
                        efficiency < 0
                        and
                        price_change < -20
                    ):

                        initiative["state"] = "TESTED"

                        initiative["successful_tests"] += 1

                        print("\nSELL INITIATIVE SUCCESSFULLY TESTED")
                        print(
                            f"SUCCESSFUL TESTS: {initiative['successful_tests']}"
                        )

                    # HEALTHY DEFENSE

                    elif delta < 0 and price_change < -10:

                        initiative["state"] = "DEFENDED"

                        print("\nSELL INITIATIVE DEFENDED")
                        print(
                            f"ZONE: {initiative['zone_low']} - {initiative['zone_high']}"
                        )

                    # ABSORPTION

                    elif delta < 0 and abs(price_change) < 10:

                        initiative["state"] = "ABSORBED"

                        print("\nSELL INITIATIVE ABSORBED")
                        print(
                            "Aggressive selling fails to produce meaningful downside continuation."
                        )

                    # FAILURE

                    elif delta > 50:

                        initiative["state"] = "FAILED"

                        print("\nSELL INITIATIVE FAILED")
                        print(
                            f"ZONE LOST: {initiative['zone_low']} - {initiative['zone_high']}"
                        )

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
