import pandas as pd

print()
print("BEHAVIORAL RUNTIME ORCHESTRATOR")
print()

# =====================================
# LOAD
# =====================================

observer = pd.read_parquet(
    "behavioral_observer_state.parquet"
)

execution = pd.read_parquet(
    "behavioral_execution_state.parquet"
)

sequence = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

# =====================================
# LATEST
# =====================================

latest_observer = (
    observer.iloc[-1]
)

latest_execution = (
    execution.iloc[-1]
)

latest_sequence = (
    sequence.iloc[-1]
)

# =====================================
# EXTRACT
# =====================================

trade_bias = (
    latest_execution[
        "trade_bias"
    ]
)

execution_state = (
    latest_execution[
        "execution_state"
    ]
)

execution_confidence = (
    latest_execution[
        "execution_confidence"
    ]
)

dominant_behavior = (
    latest_execution[
        "dominant_behavior"
    ]
)

persistence = (
    latest_execution[
        "persistence"
    ]
)

# =====================================
# DEFAULT ACTION
# =====================================

final_action = (
    "STANDBY"
)

participation_state = (
    "NO_PARTICIPATION"
)

# =====================================
# LONG PARTICIPATION
# =====================================

if (

    trade_bias == (
        "MEAN_REVERSION_LONG"
    )

    and

    execution_confidence >= 0.6

    and

    persistence >= 2

):

    final_action = (
        "PREPARE_LONG"
    )

    participation_state = (
        "CONVICTION_BUILDING"
    )

# =====================================
# DEFENSIVE PARTICIPATION
# =====================================

if (

    trade_bias == (
        "DEFENSIVE_LONG"
    )

    and

    execution_confidence >= 0.6

):

    final_action = (
        "PASSIVE_LONG_MONITOR"
    )

    participation_state = (
        "DEFENSIVE_PARTICIPATION"
    )

# =====================================
# NO TRADE
# =====================================

if (

    trade_bias == (
        "NO_TRADE"
    )

):

    final_action = (
        "AVOID_PARTICIPATION"
    )

    participation_state = (
        "ROTATIONAL_ENVIRONMENT"
    )

# =====================================
# OUTPUT
# =====================================

print(
    "FINAL ACTION:"
)

print(
    final_action
)

print()

print(
    "PARTICIPATION STATE:"
)

print(
    participation_state
)

print()

# =====================================
# SAVE
# =====================================

row = pd.DataFrame([{

    "final_action":
        final_action,

    "participation_state":
        participation_state,

    "execution_confidence":
        execution_confidence,

    "trade_bias":
        trade_bias,

    "dominant_behavior":
        dominant_behavior

}])

row.to_parquet(
    "behavioral_runtime_state.parquet"
)
