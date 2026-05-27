import pandas as pd

# =====================================
# LOAD DATA
# =====================================

states = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

response = pd.read_parquet(
    "volume_response_state.parquet"
)

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# DEBUG
# =====================================

print()
print(
    "STATE COLUMNS:"
)

print(
    states.columns
)

print()

print(
    "RESPONSE COLUMNS:"
)

print(
    response.columns
)

print()

# =====================================
# PREPARE
# =====================================

states = states.reset_index(drop=True)
response = response.reset_index(drop=True)

min_len = min(
    len(states),
    len(response)
)

states = states.tail(min_len)
response = response.tail(min_len)

data = pd.concat(
    [
        states,
        response
    ],
    axis=1
)

print()
print(
    "MERGED COLUMNS:"
)

print(
    data.columns
)

print()

# =====================================
# FILTER
# =====================================

if "volume_class" not in data.columns:

    print(
        "NO VOLUME_CLASS FOUND"
    )

    exit()

data = data[
    data["sequence"]
    ==
    "EXHAUSTION_SEQUENCE"
]

print()
print(
    "TOTAL EXHAUSTION STATES:",
    len(data)
)

print()

print(
    "AVAILABLE VOLUME CLASSES:"
)

print(
    data["volume_class"]
    .value_counts()
)

print()
