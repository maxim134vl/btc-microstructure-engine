import pandas as pd

print()
print("BEHAVIORAL BROKER BRIDGE")
print()

# =====================================
# LOAD RUNTIME
# =====================================

runtime = pd.read_parquet(
    "behavioral_runtime_state.parquet"
)

latest = runtime.iloc[-1]

# =====================================
# EXTRACT
# =====================================

final_action = (
    latest[
        "final_action"
    ]
)

participation_state = (
    latest[
        "participation_state"
    ]
)

# =====================================
# DEFAULT
# =====================================

broker_action = (
    "NO_ACTION"
)

exposure_state = (
    "FLAT"
)

# =====================================
# LONG PREPARATION
# =====================================

if (

    final_action == (
        "PREPARE_LONG"
    )

):

    broker_action = (
        "ARM_LONG_EXECUTION"
    )

    exposure_state = (
        "LONG_PREPARATION"
    )

# =====================================
# PASSIVE PARTICIPATION
# =====================================

if (

    final_action == (
        "PASSIVE_LONG_MONITOR"
    )

):

    broker_action = (
        "MONITOR_LONG_SETUP"
    )

    exposure_state = (
        "PASSIVE_MONITORING"
    )

# =====================================
# NO PARTICIPATION
# =====================================

if (

    final_action == (
        "AVOID_PARTICIPATION"
    )

):

    broker_action = (
        "MAINTAIN_FLAT"
    )

    exposure_state = (
        "NO_EXPOSURE"
    )

# =====================================
# OUTPUT
# =====================================

print(
    "BROKER ACTION:"
)

print(
    broker_action
)

print()

print(
    "EXPOSURE STATE:"
)

print(
    exposure_state
)

print()

# =====================================
# SAVE
# =====================================

row = pd.DataFrame([{

    "broker_action":
        broker_action,

    "exposure_state":
        exposure_state,

    "final_action":
        final_action,

    "participation_state":
        participation_state

}])

row.to_parquet(
    "behavioral_broker_state.parquet"
)
