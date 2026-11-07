import pandas as pd

from datetime import datetime

STATE_FILE = (
    "runtime_engine_state.parquet"
)

STALE_THRESHOLD = 30

df = pd.read_parquet(
    STATE_FILE
)

latest = (

    df.sort_values(
        "timestamp"
    )

    .groupby("engine")

    .tail(1)

)

print()
print("=" * 60)
print("RUNTIME HEALTHCHECK")
print("=" * 60)

now = datetime.now()

for _, row in latest.iterrows():

    engine = row["engine"]

    status = row["status"]

    duration = row["duration"]

    timestamp = row["timestamp"]

    lag = (
        now - timestamp
    ).total_seconds()

    stale = (
        lag > STALE_THRESHOLD
    )

    if stale:

        state = "STALE"

    else:

        state = "LIVE"

    print()

    print(engine)

    print(
        "STATE:",
        state
    )

    print(
        "STATUS:",
        status
    )

    print(
        "LAST UPDATE:",
        round(lag, 2),
        "sec ago"
    )

    print(
        "DURATION:",
        duration
    )
