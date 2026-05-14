import pandas as pd
from datetime import datetime

print("\nDEBUG RETEST COOLDOWN\n")

initiative = pd.read_parquet("initiative_memory.parquet")

latest = initiative.iloc[-1]

created_at = pd.to_datetime(latest["timestamp"])

now = datetime.utcnow()

seconds_alive = (now - created_at).total_seconds()

print(f"INITIATIVE AGE: {round(seconds_alive, 2)} seconds")

if seconds_alive < 180:

    print(
        "Retest logic blocked. "
        "Initiative too fresh for meaningful retest."
    )

else:

    print(
        "Initiative old enough for retest evaluation."
    )
