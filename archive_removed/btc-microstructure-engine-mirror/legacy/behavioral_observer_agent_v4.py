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

        # EXTRACT STATES

        regime_state = regime.iloc[-1]["regime"]
        narrative_state = narrative.iloc[-1]["narrative"]
        inventory_state = inventory.iloc[-1]["inventory_state"]
        reaction_state = reaction.iloc[-1]["reaction"]
        acceptance_state = acceptance.iloc[-1]["state"]
        liquidity_state = vacuum.iloc[-1]["vacuum_state"]

        latest_initiative = initiative.iloc[-1]

        initiative_direction = latest_initiative["direction"]
        initiative_state = latest_initiative["state"]

        # BUILD OBSERVATIONS

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

        # INITIATIVE INTERPRETATION

        if initiative_state == "DEFENDED":

            observations.append(
                f"{initiative_direction.lower()} initiative continues defending its origin zone."
            )

            if initiative_direction == "BUY":

                observations.append(
                    "Persistent buyer response suggests continuation of upside participation."
                )

            elif initiative_direction == "SELL":

                observations.append(
                    "Persistent seller response suggests continuation of downside control."
                )

        elif initiative_state == "ABSORBED":

            observations.append(
                f"{initiative_direction.lower()} initiative appears absorbed by opposing liquidity."
            )

            observations.append(
                "Aggressive participation fails to generate meaningful directional expansion."
            )

        elif initiative_state == "REJECTED":

            observations.append(
                f"{initiative_direction.lower()} initiative appears rejected by the market."
            )

            observations.append(
                "Aggressive participation fails to produce directional continuation."
            )

            observations.append(
                "Market response suggests opposing liquidity absorbs initiative pressure."
            )

        elif initiative_state == "FAILED":

            observations.append(
                f"{initiative_direction.lower()} initiative lost control of its origin zone."
            )

            observations.append(
                "Previous directional conviction appears weakened."
            )

        # CONTEXTUAL INTERPRETATION

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

        # PRINT OUTPUT

        for obs in observations:

            print(f"- {obs}")

        # WAIT

        time.sleep(60)

    except Exception as e:

        print("\nERROR")
        print(e)

        time.sleep(10)
