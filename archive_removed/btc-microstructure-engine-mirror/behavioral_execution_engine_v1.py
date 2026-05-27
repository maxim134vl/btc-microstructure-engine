import pandas as pd

print()
print("BEHAVIORAL EXECUTION ENGINE")
print()

# =====================================
# LOAD DATA
# =====================================

observer = pd.read_parquet(
    "behavioral_observer_state.parquet"
)

sequence_memory = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

# =====================================
# LATEST STATE
# =====================================

latest = observer.iloc[-1]

latest_sequence = (
    sequence_memory.iloc[-1]
)

# =====================================
# EXTRACT
# =====================================

dominant_behavior = (
    latest[
        "dominant_behavior"
    ]
)

market_phase = (
    latest[
        "market_phase"
    ]
)

sequence = (
    latest_sequence[
        "sequence"
    ]
)

persistence = (
    latest_sequence[
        "persistence"
    ]
)

# =====================================
# DEFAULT
# =====================================

trade_bias = (
    "NEUTRAL"
)

execution_state = (
    "NO_PARTICIPATION"
)

execution_confidence = 0.0

# =====================================
# EXHAUSTION LOGIC
# =====================================

if (

    dominant_behavior == (
        "EXHAUSTION"
    )

    and

    persistence >= 2

):

    trade_bias = (
        "MEAN_REVERSION_LONG"
    )

    execution_confidence = 0.75

    execution_state = (
        "HIGH_REVERSAL_PROBABILITY"
    )

# =====================================
# ABSORPTION LOGIC
# =====================================

if (

    dominant_behavior == (
        "ABSORPTION"
    )

):

    trade_bias = (
        "DEFENSIVE_LONG"
    )

    execution_confidence = 0.65

    execution_state = (
        "PASSIVE_SUPPORT_DETECTED"
    )

# =====================================
# FAILED CONTINUATION
# =====================================

if (

    sequence == (
        "FAILED_CONTINUATION_SEQUENCE"
    )

):

    trade_bias = (
        "NO_TRADE"
    )

    execution_confidence = 0.10

    execution_state = (
        "DIRECTIONAL_CONVICTION_WEAK"
    )

# =====================================
# BALANCED AUCTION
# =====================================

if (

    market_phase == (
        "BALANCED_AUCTION"
    )

    and

    dominant_behavior == (
        "EXHAUSTION"
    )

):

    execution_state = (
        "MEAN_REVERSION_ENVIRONMENT"
    )

    execution_confidence -= 0.15

# =====================================
# EXECUTION FILTERING
# =====================================

if execution_confidence < 0.5:

    trade_bias = (
        "NO_TRADE"
    )

    execution_state = (
        "LOW_CONVICTION_ENVIRONMENT"
    )

# -------------------------------------

if (

    market_phase == (
        "BALANCED_AUCTION"
    )

    and

    persistence < 2

):

    trade_bias = (
        "NO_TRADE"
    )

    execution_state = (
        "ROTATIONAL_UNCERTAINTY"
    )

# =====================================
# OUTPUT
# =====================================

print(
    "TRADE BIAS:"
)

print(
    trade_bias
)

print()

print(
    "EXECUTION CONFIDENCE:"
)

print(
    round(
        execution_confidence,
        2
    )
)

print()

print(
    "EXECUTION STATE:"
)

print(
    execution_state
)

print()

# =====================================
# SAVE
# =====================================

row = pd.DataFrame([{

    "trade_bias":
        trade_bias,

    "execution_state":
        execution_state,

    "execution_confidence":
        execution_confidence,

    "dominant_behavior":
        dominant_behavior,

    "sequence":
        sequence,

    "persistence":
        persistence

}])

row.to_parquet(
    "behavioral_execution_state.parquet"
)
