import pandas as pd
import time

from datetime import datetime

print()
print("LIVE EVENT LOGGER")
print()

# ====================================
# SAFE PARQUET READER
# ====================================

def safe_read_parquet(path):

    while True:

        try:

            df = pd.read_parquet(path)

            return df

        except Exception:

            print(
                f"PARQUET BUSY: {path}"
            )

            time.sleep(1)

# ====================================
# MAIN LOOP
# ====================================

while True:

    try:

        print("================================")
        print(datetime.utcnow())
        print("================================")
        print()

        # ====================================
        # LOAD DATA
        # ====================================

        divergence = safe_read_parquet(
            "divergence_signals.parquet"
        )

        narratives = safe_read_parquet(
            "market_narratives.parquet"
        )

        regimes = safe_read_parquet(
            "regime_history.parquet"
        )

        inventory = safe_read_parquet(
            "inventory_states.parquet"
        )

        reactions = safe_read_parquet(
            "volume_reactions.parquet"
        )

        acceptance = safe_read_parquet(
            "acceptance_states.parquet"
        )

        vacuums = safe_read_parquet(
            "liquidity_vacuums.parquet"
        )

        # ====================================
        # LATEST SNAPSHOTS
        # ====================================

        latest_divergence = divergence.iloc[-1]

        latest_narrative = narratives.iloc[-1]

        latest_regime = regimes.iloc[-1]

        latest_inventory = inventory.iloc[-1]

        latest_reaction = reactions.iloc[-1]

        latest_acceptance = acceptance.iloc[-1]

        latest_vacuum = vacuums.iloc[-1]

        # ====================================
        # OUTPUT
        # ====================================

        print("CURRENT MARKET STATE")
        print()

        print(
            "REGIME:",
            latest_regime.get(
                'regime'
            )
        )

        print(
            "NARRATIVE:",
            latest_narrative.get(
                'narrative'
            )
        )

        print(
            "INVENTORY:",
            latest_inventory.get(
                'inventory_state'
            )
        )

        print(
            "REACTION:",
            latest_reaction.get(
                'reaction'
            )
        )

        print(
            "ACCEPTANCE:",
            latest_acceptance.get(
                'state'
            )
        )

        print(
            "VACUUM:",
            latest_vacuum.get(
                'vacuum_state'
            )
        )

        print(
            "SYNC BULLISH:",
            latest_divergence.get(
                'sync_bullish'
            )
        )

        print(
            "SYNC BEARISH:",
            latest_divergence.get(
                'sync_bearish'
            )
        )

        print(
            "HYPER AGGRESSION:",
            latest_divergence.get(
                'hyper_aggression'
            )
        )

        print()

        print(
            "EVENT LOGGER UPDATED"
        )

        print()

        # ====================================
        # WAIT
        # ====================================

        time.sleep(60)

    except Exception as e:

        print("ERROR")
        print(type(e).__name__)
        print(e)
        print()

        time.sleep(5)
