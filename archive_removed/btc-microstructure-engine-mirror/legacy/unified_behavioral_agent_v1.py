import time
import pandas as pd
from datetime import datetime

print("\nUNIFIED BEHAVIORAL AGENT STARTED\n")

initiative_memory = []

while True:

    try:

        print("\n================================")
        print("UNIFIED BEHAVIORAL AGENT")
        print(datetime.utcnow())
        print("================================\n")

        # ================================
        # LOAD DATA
        # ================================

        flow = pd.read_parquet("multi_exchange_flow.parquet")

        regime = pd.read_parquet("regime_history.parquet")

        narrative = pd.read_parquet("market_narratives.parquet")

        inventory = pd.read_parquet("inventory_states.parquet")

        reaction = pd.read_parquet("volume_reactions.parquet")

        acceptance = pd.read_parquet("acceptance_states.parquet")

        vacuum = pd.read_parquet("liquidity_vacuums.parquet")

        # ================================
        # FLOW CONTEXT
        # ================================

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

        # ================================
        # CORE STATES
        # ================================

        regime_state = regime.iloc[-1]["regime"]

        narrative_state = narrative.iloc[-1]["narrative"]

        inventory_state = inventory.iloc[-1]["inventory_state"]

        reaction_state = reaction.iloc[-1]["reaction"]

        acceptance_state = acceptance.iloc[-1]["state"]

        liquidity_state = vacuum.iloc[-1]["vacuum_state"]

        # ================================
        # DETECT NEW INITIATIVE
        # ================================

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

        # ================================
        # INITIATIVE STATE TRANSITIONS
        # ================================

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

                # cooldown against self-test

                if seconds_alive < 180:

                    continue

                # ====================
                # BUY INITIATIVE
                # ====================

                if initiative["direction"] == "BUY":

                    # rejection

                    if price_change < -20:

                        initiative["state"] = "REJECTED"

                    # successful retest

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

                    # healthy defense

                    elif (
                        delta > 0
                        and
                        price_change > 10
                    ):

                        initiative["state"] = "DEFENDED"

                    # absorption

                    elif (
                        delta > 0
                        and
                        abs(price_change) < 10
                    ):

                        initiative["state"] = "ABSORBED"

                    # failure

                    elif delta < -50:

                        initiative["state"] = "FAILED"

                # ====================
                # SELL INITIATIVE
                # ====================

                elif initiative["direction"] == "SELL":

                    # rejection

                    if price_change > 20:

                        initiative["state"] = "REJECTED"

                    # successful retest

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

                    # healthy defense

                    elif (
                        delta < 0
                        and
                        price_change < -10
                    ):

                        initiative["state"] = "DEFENDED"

                    # absorption

                    elif (
                        delta < 0
                        and
                        abs(price_change) < 10
                    ):

                        initiative["state"] = "ABSORBED"

                    # failure

                    elif delta > 50:

                        initiative["state"] = "FAILED"

        # ================================
        # SAVE MEMORY
        # ================================

        memory_df = pd.DataFrame(initiative_memory)

        memory_df.to_parquet(
            "initiative_memory.parquet",
            index=False
        )

        # ================================
        # OBSERVER COGNITION
        # ================================

        observations = []

        observations.append(
            f"Market regime remains {regime_state.lower().replace('_', ' ')}."
        )

        observations.append(
            f"Narrative context reflects {narrative_state.lower().replace('_', ' ')}."
        )

        observations.append(
            f"Inventory conditions appear {inventory_state.lower().replace('_', ' ')}."
        )

        observations.append(
            f"Volume reaction remains {reaction_state.lower().replace('_', ' ')}."
        )

        observations.append(
            f"Acceptance conditions indicate {acceptance_state.lower().replace('_', ' ')}."
        )

        observations.append(
            f"Liquidity environment remains {liquidity_state.lower().replace('_', ' ')}."
        )

        # ================================
        # CURRENT INITIATIVE
        # ================================

        if len(initiative_memory) > 0:

            latest = initiative_memory[-1]

            direction = latest["direction"]

            state = latest["state"]

            tests = latest["successful_tests"]

            if state == "TESTED":

                observations.append(
                    f"{direction.lower()} initiative successfully passed market retest."
                )

                observations.append(
                    "Responsive participation reappeared during interaction with the initiative zone."
                )

                observations.append(
                    "Auction continuation suggests initiative control remains active."
                )

                if tests >= 2:

                    observations.append(
                        "Repeated successful retests suggest growing structural support or resistance."
                    )

            elif state == "DEFENDED":

                observations.append(
                    f"{direction.lower()} initiative continues defending its origin zone."
                )

                observations.append(
                    "Persistent participation continues supporting directional continuation."
                )

            elif state == "ABSORBED":

                observations.append(
                    f"{direction.lower()} initiative appears absorbed by opposing liquidity."
                )

                observations.append(
                    "Aggressive participation fails to generate meaningful directional expansion."
                )

            elif state == "REJECTED":

                observations.append(
                    f"{direction.lower()} initiative appears rejected by the market."
                )

                observations.append(
                    "Aggressive participation failed to sustain directional continuation."
                )

                observations.append(
                    "Market response suggests breakout participants may be trapped."
                )

                observations.append(
                    "Auction failed to maintain acceptance beyond the initiative zone."
                )

            elif state == "FAILED":

                observations.append(
                    f"{direction.lower()} initiative lost control of its origin zone."
                )

                observations.append(
                    "Previous directional conviction appears weakened."
                )

        # ================================
        # HISTORICAL PATTERNS
        # ================================

        recent_initiatives = initiative_memory[-5:]

        rejected_buys = 0
        rejected_sells = 0

        tested_buys = 0
        tested_sells = 0

        for initiative in recent_initiatives:

            direction = initiative["direction"]

            state = initiative["state"]

            if direction == "BUY" and state == "REJECTED":

                rejected_buys += 1

            elif direction == "SELL" and state == "REJECTED":

                rejected_sells += 1

            elif direction == "BUY" and state == "TESTED":

                tested_buys += 1

            elif direction == "SELL" and state == "TESTED":

                tested_sells += 1

        if rejected_buys >= 2:

            observations.append(
                "Repeated rejected buy initiatives suggest weakening upside continuation."
            )

        if rejected_sells >= 2:

            observations.append(
                "Repeated rejected sell initiatives suggest sellers struggle to maintain downside control."
            )

        if tested_buys >= 2:

            observations.append(
                "Repeated successful buy retests suggest growing structural support."
            )

        if tested_sells >= 2:

            observations.append(
                "Repeated successful sell retests suggest strengthening downside acceptance."
            )

        # ================================
        # CONTEXTUAL LAYERS
        # ================================

        if "FAILED" in acceptance_state:

            observations.append(
                "Failed acceptance suggests inability to sustain auction beyond local value."
            )

        if "VACUUM" in liquidity_state:

            observations.append(
                "Liquidity conditions remain fragile and vulnerable to impulsive expansion."
            )

        if "BALANCED" in inventory_state:

            observations.append(
                "Positioning remains balanced with no strong trapped inventory signals."
            )

        # ================================
        # OUTPUT
        # ================================

        for obs in observations:

            print(f"- {obs}")

        time.sleep(60)

    except Exception as e:

        print("\nERROR")
        print(e)

        time.sleep(10)
