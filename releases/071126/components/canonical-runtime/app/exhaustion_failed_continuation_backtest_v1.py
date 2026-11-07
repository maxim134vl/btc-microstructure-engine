import pandas as pd

# =====================================
# LOAD DATA
# =====================================

states = pd.read_parquet(
    "behavioral_sequence_memory.parquet"
)

candles = pd.read_parquet(
    "candle_structure_memory.parquet"
)

candles = candles.reset_index()

# =====================================
# FIND FAILED CONTINUATION WINDOWS
# =====================================

failed = states[
    states["sequence"]
    ==
    "FAILED_CONTINUATION_SEQUENCE"
].copy()

exhaustion = states[
    states["sequence"]
    ==
    "EXHAUSTION_SEQUENCE"
].copy()

# =====================================
# MATCH CONTEXT
# =====================================

matched = []

for _, fail_row in failed.iterrows():

    fail_time = pd.to_datetime(
        fail_row["timestamp"]
    )

    nearby = exhaustion[

        (
            pd.to_datetime(
                exhaustion["timestamp"]
            )

            >=

            fail_time - pd.Timedelta(minutes=30)
        )

        &

        (
            pd.to_datetime(
                exhaustion["timestamp"]
            )

            <=

            fail_time + pd.Timedelta(minutes=30)
        )

    ]

    if len(nearby) > 0:

        matched.append(
            fail_row
        )

matched = pd.DataFrame(matched)

print()
print(
    "TOTAL MATCHED STATES:",
    len(matched)
)

results = []

# =====================================
# ANALYZE OUTCOME
# =====================================

for _, row in matched.iterrows():

    timestamp = pd.to_datetime(
        row["timestamp"]
    )

    future = candles[
        candles["timestamp"] > timestamp
    ].head(5)

    if len(future) < 5:
        continue

    start_price = future.iloc[0]["close"]

    end_price = future.iloc[-1]["close"]

    move = (
        end_price
        -
        start_price
    )

    results.append(move)

# =====================================
# RESULTS
# =====================================

results = pd.Series(results)

if len(results) == 0:

    print()
    print(
        "NO VALID FUTURE WINDOWS"
    )

else:

    positive = (
        results > 0
    ).mean()

    negative = (
        results < 0
    ).mean()

    print()
    print(
        "UP CONTINUATION RATE:",
        round(positive * 100, 2),
        "%"
    )

    print(
        "DOWN / REVERSAL RATE:",
        round(negative * 100, 2),
        "%"
    )

    print()
    print(
        "AVERAGE MOVE:",
        round(results.mean(), 2)
    )

print()
