import pandas as pd

print("\nDEBUG UNIFIED EXECUTION\n")

memory_df = pd.read_parquet(
    "initiative_memory.parquet"
)

print("MEMORY SIZE:")
print(len(memory_df))

print("\nCHECK GATE:\n")

print(len(memory_df) > 0)

if len(memory_df) > 0:

    print("\nENTERED INITIATIVE BLOCK\n")

    latest = memory_df.iloc[-1]

    print("LATEST INITIATIVE:\n")

    print(latest)

    direction = latest["direction"]

    state = latest["state"]

    print("\nSTATE CHECKS:\n")

    print("TESTED:", state == "TESTED")

    print("DEFENDED:", state == "DEFENDED")

    print("ABSORBED:", state == "ABSORBED")

    print("REJECTED:", state == "REJECTED")

    print("FAILED:", state == "FAILED")

    print("\nEXPECTED OUTPUT:\n")

    if state == "DEFENDED":

        print(
            f"{direction.lower()} initiative continues defending its origin zone."
        )

        print(
            "Persistent participation continues supporting directional continuation."
        )
