import pandas as pd

print("\nTEMPORAL CONTEXT MEMORY STARTED\n")

# =====================================
# LOAD CONTEXT
# =====================================

context = pd.read_parquet(
    "contextual_memory_state.parquet"
)

# =====================================
# LOAD OLD MEMORY
# =====================================

try:

    memory = pd.read_parquet(
        "temporal_context_memory.parquet"
    )

except:

    memory = pd.DataFrame()

previous_event_state = "NONE"

if len(memory) > 0:

    previous_event_state = (
        memory.iloc[-1][
            "event_state"
        ]
    )

# =====================================
# LATEST STATE
# =====================================

latest = context.iloc[-1]

# =====================================
# PREVIOUS MEMORY
# =====================================

if len(memory) > 0:

    previous = memory.iloc[-1]

    bearish_persistence = previous[
        "bearish_persistence"
    ]

    bullish_persistence = previous[
        "bullish_persistence"
    ]

    failure_persistence = previous[
        "failure_persistence"
    ]

    acceptance_breaking_persistence = previous[
        "acceptance_breaking_persistence"
    ]

else:

    bearish_persistence = 0

    bullish_persistence = 0

    failure_persistence = 0

    acceptance_breaking_persistence = 0

previous_decay = 0

if "event_decay_counter" in previous.index:

    previous_decay = (
        previous[
            "event_decay_counter"
        ]
    )

# =====================================
# REGIME
# =====================================

if latest["regime_state"] == "BEARISH_PRESSURE":

    bearish_persistence += 1

else:

    bearish_persistence = max(
        bearish_persistence - 1,
        0
    )

if latest["regime_state"] == "BULLISH_PRESSURE":

    bullish_persistence += 1

else:

    bullish_persistence = max(
        bullish_persistence - 1,
        0
    )

# =====================================
# FAILED LIQUIDITY
# =====================================

if latest[
    "inventory_modifier"
] == "LIQUIDITY_FAILED":

    failure_persistence += 1

else:

    failure_persistence = max(
        failure_persistence - 1,
        0
    )

# =====================================
# ACCEPTANCE BREAKDOWN
# =====================================

if latest[
    "acceptance_modifier"
] == "ACCEPTANCE_BREAKING":

    acceptance_breaking_persistence += 1

else:

    acceptance_breaking_persistence = max(
        acceptance_breaking_persistence - 1,
        0
    )

# =====================================
# ESCALATION STATES
# =====================================

event_state = "NEUTRAL"

event_decay_counter = 0

# =====================================
# BEARISH CASCADE
# =====================================

if (
    failure_persistence >= 3
    and
    acceptance_breaking_persistence >= 3
):

    event_state = (
        "FAILED_LIQUIDITY_CASCADE"
    )

# =====================================
# BEARISH EXHAUSTION
# =====================================

if (

    latest[
        "reaction_state"
    ] == "EXHAUSTION"

    and

    bearish_persistence >= 3

):

    event_state = (
        "BEARISH_EXHAUSTION"
    )

# =====================================
# FAILED CONTINUATION
# =====================================

if (

    bearish_persistence >= 3

    and

    failure_persistence < 3

    and

    acceptance_breaking_persistence < 3

):

    event_state = (
        "FAILED_CONTINUATION"
    )

# =====================================
# STABILIZING AUCTION
# =====================================

if (

    event_state == "FAILED_CONTINUATION"

    and

    latest[
        "reaction_state"
    ] == "EXHAUSTION"

    and

    latest[
        "volume_state"
    ] == "REJECTION_FROM_MEMORY"

):

    event_state = (
        "STABILIZING_AUCTION"
    )

# =====================================
# LINGERING WEAKNESS
# =====================================

if (

    event_state == "NEUTRAL"

    and

    previous_event_state == (
        "FAILED_CONTINUATION"
    )

):

    event_state = (
        "LINGERING_WEAKNESS"
    )

event_decay_counter = (
    previous_decay + 1
)

# =====================================
# STABILIZATION CONFIRMATION
# =====================================

if (

    event_state == (
        "LINGERING_WEAKNESS"
    )

    and

    bearish_persistence <= 2

    and

    failure_persistence == 0

    and

    bullish_persistence >= 1

):

    event_state = (
        "STABILIZING_AUCTION"
    )

# =====================================
# REVERSAL EMERGENCE
# =====================================

if (

    event_decay_counter >= 1

    and

    bullish_persistence >= 2

    and

    bearish_persistence <= 1

    and

    failure_persistence == 0

):

    event_state = (
        "REVERSAL_POTENTIAL"
    )

# =====================================
# DECAY RESET
# =====================================

if event_decay_counter >= 3:

    event_state = "NEUTRAL"

    event_decay_counter = 0

# =====================================
# BULLISH ACCEPTANCE
# =====================================

if (
    bullish_persistence >= 3
):

    event_state = (
        "BULLISH_ACCEPTANCE_SEQUENCE"
    )

# =====================================
# BUILD STATE
# =====================================

state = pd.DataFrame([{

    "timestamp":
        latest["timestamp"],

    "event_state":
        event_state,

    "event_decay_counter":
        event_decay_counter,

    "bearish_persistence":
        bearish_persistence,

    "bullish_persistence":
        bullish_persistence,

    "failure_persistence":
        failure_persistence,

    "acceptance_breaking_persistence":
        acceptance_breaking_persistence

}])

# =====================================
# APPEND
# =====================================

memory = pd.concat([
    memory,
    state
])

memory = memory.tail(500)

# =====================================
# SAVE
# =====================================

memory.to_parquet(
    "temporal_context_memory.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("TEMPORAL MEMORY")

print("=" * 50)

print()

print(memory.tail(20))

print()

print(
    f"CURRENT EVENT STATE: "
    f"{event_state}"
)

print()

print(
    "temporal_context_memory.parquet SAVED"
)

print()
