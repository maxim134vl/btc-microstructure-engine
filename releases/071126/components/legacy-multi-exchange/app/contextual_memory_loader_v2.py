import pandas as pd

print("\nCONTEXTUAL MEMORY LOADER V2 STARTED\n")

# =====================================
# LOAD FILES
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

integration = pd.read_parquet(
    "perception_context_integration.parquet"
)

temporal = pd.read_parquet(
    "temporal_context_memory.parquet"
)

# =====================================
# SORT
# =====================================

volume_memory = volume_memory.sort_values(
    "timestamp"
)

inventory_states = inventory_states.sort_values(
    "timestamp"
)

acceptance_states = acceptance_states.sort_values(
    "timestamp"
)

regime_history = regime_history.sort_values(
    "timestamp"
)

volume_reactions = volume_reactions.sort_values(
    "timestamp"
)

# =====================================
# LATEST ROWS
# =====================================

latest_volume = volume_memory.iloc[-1]

latest_inventory = inventory_states.iloc[-1]

latest_acceptance = acceptance_states.iloc[-1]

latest_regime = regime_history.iloc[-1]

latest_reaction = volume_reactions.iloc[-1]

latest_integration = integration.iloc[-1]

latest_temporal = temporal.iloc[-1]

# =====================================
# TEMPORAL FEEDBACK
# =====================================

regime_feedback = "STABLE"

if latest_temporal[
    "event_state"
] == "FAILED_LIQUIDITY_CASCADE":

    regime_feedback = (
        "BEARISH_ESCALATION"
    )

# =====================================
# BUILD CONTEXT
# =====================================

context_state = pd.DataFrame({

    "timestamp": [
        latest_regime["timestamp"]
    ],

    "regime_state": [
        latest_regime["regime"]
    ],

    "regime_feedback": [
        regime_feedback
    ],

    "event_state": [
        latest_temporal[
        "event_state"
        ]
    ],
    "inventory_state": [
        latest_inventory["inventory_state"]
    ],

    "inventory_modifier": [
        latest_integration[
            "inventory_modifier"
        ]
    ],

    "acceptance_state": [
        latest_acceptance["state"]
    ],

    "acceptance_modifier": [
        latest_integration[
            "acceptance_modifier"
        ]
    ],

    "volume_state": [
        latest_volume["memory_state"]
    ],

    "reaction_state": [
        latest_reaction["reaction"]
    ],

    "reaction_modifier": [
        latest_integration[
            "reaction_modifier"
        ]
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

print("MARKET STATE SUMMARY")

print()

print(
    f"REGIME STATE: {latest_regime['regime']}"
)

print(
    f"REGIME FEEDBACK: "
    f"{regime_feedback}"
)

print(
    f"EVENT STATE: "
    f"{latest_temporal['event_state']}"
)

print(
    f"INVENTORY: "
    f"{latest_inventory['inventory_state']}"
)

print(
    f"INVENTORY MODIFIER: "
    f"{latest_integration['inventory_modifier']}"
)

print(
    f"ACCEPTANCE: "
    f"{latest_acceptance['state']}"
)

print(
    f"ACCEPTANCE MODIFIER: "
    f"{latest_integration['acceptance_modifier']}"
)

print(
    f"VOLUME MEMORY: "
    f"{latest_volume['memory_state']}"
)

print(
    f"REACTION: "
    f"{latest_reaction['reaction']}"
)

print(
    f"REACTION MODIFIER: "
    f"{latest_integration['reaction_modifier']}"
)

print()

print(
    f"CONTEXT CONFIDENCE: "
    f"{latest_integration['context_confidence']}"
)
