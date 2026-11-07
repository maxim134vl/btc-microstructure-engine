import pandas as pd

# =====================================
# LOAD DATA
# =====================================

states = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

states = states.reset_index(drop=True)

# =====================================
# FILTER EXHAUSTION
# =====================================

exhaustion_idx = states[
    states["sequence"]
    ==
    "EXHAUSTION_SEQUENCE"
].index

print()
print(
    "TOTAL EXHAUSTION STATES:",
    len(exhaustion_idx)
)

transitions = []

# =====================================
# NEXT STATE ANALYSIS
# =====================================

for idx in exhaustion_idx:

    next_idx = idx + 1

    if next_idx >= len(states):
        continue

    next_state = states.iloc[next_idx][
        "sequence"
    ]

    transitions.append(
        next_state
    )

# =====================================
# RESULTS
# =====================================

transitions = pd.Series(transitions)

print()
print(
    "POST EXHAUSTION TRANSITIONS:"
)

print()

print(
    transitions.value_counts(
        normalize=True
    ) * 100
)

print()
