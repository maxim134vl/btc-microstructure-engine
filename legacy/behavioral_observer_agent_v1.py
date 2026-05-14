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

        # -------------------------
        # LOAD DATA
        # -------------------------

        regime = pd.read_parquet("regime_history.parquet")
        narrative = pd.read_parquet("market_narratives.parquet")
        inventory = pd.read_parquet("inventory_states.parquet")
        reaction = pd.read_parquet("volume_reactions.parquet")
        acceptance = pd.read_parquet("acceptance_states.parquet")
        vacuum = pd.read_parquet("liquidity_vacuums.parquet")

        # -------------------------
        # EXTRACT STATES
        # -------------------------

        regime_state = regime.iloc[-1]["regime"]
        narrative_state = narrative.iloc[-1]["narrative"]
        inventory_state = inventory.iloc[-1]["inventory_state"]
        reaction_state = reaction.iloc[-1]["reaction"]
        acceptance_state = acceptance.iloc[-1]["acceptance_state"]
        liquidity_state = vacuum.iloc[-1]["vacuum_state"]

        # -------------------------
        # OBSERVATIONS
        # -------------------------

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

        # -------------------------
        # CONTEXTUAL INTERPRETATION
        # -------------------------

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

        if "BULLISH" in regime_state and "NEUTRAL" in reaction_state:
            observations.append(
                "Directional pressure lacks strong participation confirmation."
            )

        if "BEARISH" in regime_state and "NEUTRAL" in reaction_state:
            observations.append(
                "Bearish pressure remains weak and lacks aggressive continuation."
            )

        # -------------------------
        # PRINT OUTPUT
        # -------------------------

        for obs in observations:
            print(f"- {obs}")

        # -------------------------
        # WAIT
        # -------------------------

        time.sleep(60)

    except Exception as e:

        print("\nERROR")
        print(e)

        time.sleep(10)
