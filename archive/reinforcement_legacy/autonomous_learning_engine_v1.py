import pandas as pd
import numpy as np
import os

print("\nAUTONOMOUS LEARNING ENGINE STARTED\n")

# =====================================
# LOAD MEMORY
# =====================================

memory_df = pd.read_parquet(
    "incremental_memory.parquet"
)

# =====================================
# LEARNING STORAGE
# =====================================

learning_rows = []

# =====================================
# PATTERN WEIGHTS
# =====================================

weights = {

    "continuation_intent": 1.0,

    "breakout_failure": 1.0,

    "liquidity_sweep": 1.0,

    "inventory_transfer": 1.0,

    "exhaustion_intent": 1.0

}

# =====================================
# LOOP
# =====================================

for i in range(len(memory_df) - 1):

    current = memory_df.iloc[i]

    future = memory_df.iloc[i + 1]

    current_intent = current["intent"]

    current_instability = current[
        "instability_score"
    ]

    current_maturity = current[
        "maturity_score"
    ]

    future_instability = future[
        "instability_score"
    ]

    # =====================================
    # OUTCOME
    # =====================================

    outcome = "neutral"

    reward = 0

    # continuation stabilized

    if (

        current_intent
        == "continuation_intent"

        and

        future_instability
        <
        current_instability

    ):

        outcome = "successful_continuation"

        reward = 1

    # breakout failed harder

    elif (

        current_intent
        == "breakout_failure"

        and

        future_instability
        >
        current_instability

    ):

        outcome = "confirmed_failure"

        reward = 1

    # exhaustion reduced volatility

    elif (

        current_intent
        == "exhaustion_intent"

        and

        future_instability
        <
        current_instability

    ):

        outcome = "successful_exhaustion"

        reward = 1

    else:

        reward = -0.2

    # =====================================
    # UPDATE WEIGHTS
    # =====================================

    if current_intent in weights:

        weights[current_intent] += (
            reward * 0.05
        )

        weights[current_intent] = max(
            0.1,
            weights[current_intent]
        )

    # =====================================
    # SAVE
    # =====================================

    row = {

        "timestamp": current["timestamp"],

        "intent": current_intent,

        "outcome": outcome,

        "reward": reward,

        "updated_weight": weights.get(
            current_intent,
            1
        ),

        "instability_before": current_instability,

        "instability_after": future_instability

    }

    learning_rows.append(row)

# =====================================
# BUILD DF
# =====================================

learning_df = pd.DataFrame(
    learning_rows
)

# =====================================
# SAVE
# =====================================

learning_df.to_parquet(
    "autonomous_learning_memory.parquet"
)

weights_df = pd.DataFrame([weights])

weights_df.to_parquet(
    "behavior_weights.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("LEARNING SUMMARY")

print("=" * 50)

print()

print("FINAL WEIGHTS:")

print(weights)

print()

print("LAST 20 LEARNING EVENTS:")

print(

    learning_df.tail(20)

)

print()

print("MEMORY SAVED:")

print(
    "autonomous_learning_memory.parquet"
)

print(
    "behavior_weights.parquet"
)

print()
