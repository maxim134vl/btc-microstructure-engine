import time
import pandas as pd
from datetime import datetime

print("\nBEHAVIORAL OBSERVER AGENT STARTED\n")

while True:

    try:

        print("\n================================")
        print("BEHAVIORAL OBSERVER")
        print(datetime.utcnow())
        print("================================\n")

        # LOAD DATA

        regime = pd.read_parquet("regime_history.parquet")
        narrative = pd.read_parquet("market_narratives.parquet")
        inventory = pd.read_parquet("inventory_states.parquet")
        reaction = pd.read_parquet("volume_reactions.parquet")
        acceptance = pd.read_parquet("acceptance_states.parquet")
        vacuum = pd.read_parquet("liquidity_vacuums.parquet")
        initiative = pd.read_parquet("initiative_memory.parquet")

        # CORE STATES

        regime_state = regime.iloc[-1]["regime"]
        narrative_state = narrative.iloc[-1]["narrative"]
        inventory_state = inventory.iloc[-1]["inventory_state"]
        reaction_state = reaction.iloc[-1]["reaction"]
        acceptance_state = acceptance.iloc[-1]["state"]
        liquidity_state = vacuum.iloc[-1]["vacuum_state"]

        # INITIATIVE MEMORY

        latest_initiative = initiative.iloc[-1]

        recent_initiatives = initiative.tail(5)

        latest_direction = latest_initiative["direction"]
        latest_state = latest_initiative["state"]

        observations = []

        # CORE MARKET CONTEXT

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

        # CURRENT INITIATIVE INTERPRETATION

        if latest_state == "TESTED":

            observations.append(
                f"{latest_direction.lower()} initiative successfully passed market retest."
            )

            observations.append(
                "Responsive participation reappeared during interaction with the initiative zone."
            )

            observations.append(
                "Auction continuation suggests initiative control remains active."
            )

        elif latest_state == "DEFENDED":

            observations.append(
                f"{latest_direction.lower()} initiative continues defending its origin zone."
            )

            observations.append(
                "Persistent participation continues supporting directional continuation."
            )

        elif latest_state == "ABSORBED":

            observations.append(
                f"{latest_direction.lower()} initiative appears absorbed by opposing liquidity."
            )

            observations.append(
                "Aggressive participation fails to generate meaningful directional expansion."
            )

        elif latest_state == "REJECTED":

            observations.append(
                f"{latest_direction.lower()} initiative appears rejected by the market."
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

        elif latest_state == "FAILED":

            observations.append(
                f"{latest_direction.lower()} initiative lost control of its origin zone."
            )

            observations.append(
                "Previous directional conviction appears weakened."
            )

        # HISTORICAL PATTERN MEMORY

        rejected_buys = 0
        rejected_sells = 0

        tested_buys = 0
        tested_sells = 0

        failed_buys = 0
        failed_sells = 0

        for _, row in recent_initiatives.iterrows():

            direction = row["direction"]
            state = row["state"]

            if direction == "BUY":

                if state == "REJECTED":
                    rejected_buys += 1

                elif state == "TESTED":
                    tested_buys += 1

                elif state == "FAILED":
                    failed_buys += 1

            elif direction == "SELL":

                if state == "REJECTED":
                    rejected_sells += 1

                elif state == "TESTED":
                    tested_sells += 1

                elif state == "FAILED":
                    failed_sells += 1

        # SEQUENCE INTERPRETATION

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

        if failed_buys >= 2:

            observations.append(
                "Repeated failed buy initiatives suggest deteriorating buyer conviction."
            )

        if failed_sells >= 2:

            observations.append(
                "Repeated failed sell initiatives suggest deteriorating seller conviction."
            )

        # ACCEPTANCE CONTEXT

        if "FAILED" in acceptance_state:

            observations.append(
                "Failed acceptance suggests inability to sustain auction beyond local value."
            )

        # LIQUIDITY CONTEXT

        if "VACUUM" in liquidity_state:

            observations.append(
                "Liquidity conditions remain fragile and vulnerable to impulsive expansion."
            )

        # INVENTORY CONTEXT

        if "BALANCED" in inventory_state:

            observations.append(
                "Positioning remains balanced with no strong trapped inventory signals."
            )

        # OUTPUT

        for obs in observations:

            print(f"- {obs}")

        time.sleep(60)

    except Exception as e:

        print("\nERROR")
        print(e)

        time.sleep(10)
