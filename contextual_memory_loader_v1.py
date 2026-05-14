import pandas as pd

print("\nCONTEXTUAL MEMORY LOADER STARTED\n")

# =====================================
# LOAD MEMORY FILES
# =====================================

volume_memory = pd.read_parquet(
    "volume_memory.parquet"
)

inventory_states = pd.read_parquet(
    "inventory_states.parquet"
)

acceptance_states = pd.read_parquet(
    "acceptance_states.parquet"
)

regime_history = pd.read_parquet(
    "regime_history.parquet"
)

volume_reactions = pd.read_parquet(
    "volume_reactions.parquet"
)

# =====================================
# LATEST CONTEXT
# =====================================

latest_volume_memory = (
    volume_memory
    .sort_values("timestamp")
    .tail(1)
)

latest_inventory = (
    inventory_states
    .sort_values("timestamp")
    .tail(1)
)


latest_regime = (
    regime_history
    .sort_values("timestamp")
    .tail(1)
)

latest_reaction = (
    volume_reactions
    .sort_values("timestamp")
    .tail(1)
)

# =====================================
# BUILD CONTEXT STATE
# =====================================

context_state = pd.DataFrame({

    "timestamp": [

        latest_regime.iloc[0]["timestamp"]

    ],

    "regime": [

        latest_regime.iloc[0]["regime"]

    ],

    "inventory_state": [

        latest_inventory.iloc[0]["inventory_state"]

    ],

    "acceptance_state": [

        latest_acceptance.iloc[0]["acceptance_state"]

    ],

    "volume_behavior": [

        latest_volume_memory.iloc[0]["behavior"]

    ],

    "reaction_type": [

        latest_reaction.iloc[0]["reaction_type"]

    ]

})

# =====================================
# SAVE
# =====================================

context_state.to_parquet(

    "contextual_memory_state.parquet",

    index=False

)

# =====================================
# OUTPUT
# =====================================

print("=" * 60)

print("UNIFIED CONTEXT STATE")

print("=" * 60)

print()

print(context_state)

print()

print("MEMORY SAVED:")
print("contextual_memory_state.parquet")
