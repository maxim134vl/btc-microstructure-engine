import pandas as pd

print("\nDEBUG DEFENDED BRANCH\n")

memory = pd.read_parquet(
    "initiative_memory.parquet"
)

latest = memory.iloc[-1]

state = latest["state"]

direction = latest["direction"]

print(f"STATE: {state}")

print(f"DIRECTION: {direction}")

print("\nCHECKS\n")

print(state == "DEFENDED")

if state == "DEFENDED":

    print(
        f"{direction.lower()} initiative continues defending its origin zone."
    )

    print(
        "Persistent participation continues supporting directional continuation."
    )
