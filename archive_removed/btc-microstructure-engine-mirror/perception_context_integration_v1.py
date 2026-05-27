import pandas as pd

print("\nPERCEPTION CONTEXT INTEGRATION STARTED\n")

# =====================================
# LOAD OLD CONTEXT STATES
# =====================================

inventory = pd.read_parquet(
    "inventory_states.parquet"
)

acceptance = pd.read_parquet(
    "acceptance_states.parquet"
)

reactions = pd.read_parquet(
    "volume_reactions.parquet"
)

# =====================================
# LOAD NEW PERCEPTION
# =====================================

tests = pd.read_parquet(
    "test_recognition_memory.parquet"
)

liquidity = pd.read_parquet(
    "defended_liquidity_memory.parquet"
)

geometry = pd.read_parquet(
    "candle_geometry_v2_memory.parquet"
)

localization = pd.read_parquet(
    "volume_localization_v2_memory.parquet"
)

temporal = pd.read_parquet(
    "temporal_context_memory.parquet"
)

# =====================================
# LAST STATES
# =====================================

last_inventory = inventory.iloc[-1]
last_acceptance = acceptance.iloc[-1]
last_reaction = reactions.iloc[-1]

last_test = tests.iloc[-1]
last_liquidity = liquidity.iloc[-1]

last_geometry = geometry.iloc[-1]
last_localization = localization.iloc[-1]
last_temporal = temporal.iloc[-1]

# =====================================
# CONTEXT MODIFIERS
# =====================================

inventory_modifier = "NEUTRAL"

acceptance_modifier = "NEUTRAL"

reaction_modifier = "NEUTRAL"

context_confidence = 0

# =====================================
# DEFENDED TEST
# =====================================

if last_test["successful_test"]:

    inventory_modifier = (
        "DEFENDED_LIQUIDITY_PRESENT"
    )

    acceptance_modifier = (
        "ACCEPTANCE_HOLDING"
    )

# =====================================
# FAILED TEST
# =====================================

if last_test["failed_test"]:

    inventory_modifier = (
        "LIQUIDITY_FAILED"
    )

    acceptance_modifier = (
        "ACCEPTANCE_BREAKING"
    )

# =====================================
# STRUCTURE CONTEXT
# =====================================

if last_geometry[
    "structure_label"
] == "potential_absorption":

    inventory_modifier = (
        "POTENTIAL_ABSORPTION"
    )

    context_confidence += 1

if last_geometry[
    "structure_label"
] == "potential_distribution":

    inventory_modifier = (
        "POTENTIAL_DISTRIBUTION"
    )

    context_confidence += 1

# =====================================
# LOCALIZED AUCTION
# =====================================

if last_localization[
    "behavior"
] == "localized_absorption":

    acceptance_modifier = (
        "LOCALIZED_ABSORPTION"
    )

    context_confidence += 2

if last_localization[
    "behavior"
] == "localized_distribution":

    acceptance_modifier = (
        "LOCALIZED_DISTRIBUTION"
    )

    context_confidence += 1

# =====================================
# TEMPORAL ESCALATION
# =====================================

if last_temporal[
    "event_state"
] == "FAILED_LIQUIDITY_CASCADE":

    context_confidence += 2

# =====================================
# PERSISTENT PRESSURE
# =====================================

if last_temporal[
    "bearish_persistence"
] >= 3:

    context_confidence += 1

if last_temporal[
    "failure_persistence"
] >= 3:

    context_confidence += 1

# =====================================
# BROKEN LIQUIDITY
# =====================================

if last_liquidity["broken"]:

    reaction_modifier = (
        "REJECTION_FAILED"
    )

# =====================================
# BUILD OUTPUT
# =====================================

integration = pd.DataFrame([{

    "timestamp":
        last_test["timestamp"],

    "inventory_state":
        last_inventory["inventory_state"],

    "inventory_modifier":
        inventory_modifier,

    "acceptance_state":
        last_acceptance["state"],

    "acceptance_modifier":
        acceptance_modifier,

    "reaction_type":
        last_reaction["reaction"],

    "reaction_modifier":
        reaction_modifier,

    "context_confidence":
        context_confidence

}])

# =====================================
# SAVE
# =====================================

integration.to_parquet(
    "perception_context_integration.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("PERCEPTION CONTEXT")

print("=" * 50)

print()

print(integration)

print()

print(
    "perception_context_integration.parquet SAVED"
)

print()
