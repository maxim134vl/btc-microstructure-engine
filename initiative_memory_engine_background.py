import time
import pandas as pd
from datetime import datetime

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

        # DETECT INITIATIVE

        if abs(delta) > 70 and volume_value > 50:

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

                    if price_change < -20:

                        initiative["state"] = "REJECTED"

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

                    elif delta > 0 and price_change > 10:

                        initiative["state"] = "DEFENDED"

                    elif delta > 0 and abs(price_change) < 10:

                        initiative["state"] = "ABSORBED"

                    elif delta < -50:

                        initiative["state"] = "FAILED"

                # SELL INITIATIVE

                elif initiative["direction"] == "SELL":

                    if price_change > 20:

                        initiative["state"] = "REJECTED"

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

                    elif delta < 0 and price_change < -10:

                        initiative["state"] = "DEFENDED"

                    elif delta < 0 and abs(price_change) < 10:

                        initiative["state"] = "ABSORBED"

                    elif delta > 50:

                        initiative["state"] = "FAILED"

        # SAVE MEMORY

        memory_df = pd.DataFrame(initiative_memory)

        memory_df.to_parquet(
            "initiative_memory.parquet",
            index=False
        )

        time.sleep(60)

    except Exception:

        time.sleep(10)
