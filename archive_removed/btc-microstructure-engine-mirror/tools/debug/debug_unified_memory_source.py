import pandas as pd

print("\nDEBUG UNIFIED MEMORY SOURCE\n")

# RUNTIME MEMORY SIMULATION

runtime_memory = []

print("RUNTIME MEMORY SIZE:")
print(len(runtime_memory))

# PARQUET MEMORY

memory_df = pd.read_parquet(
    "initiative_memory.parquet"
)

print("\nPARQUET MEMORY SIZE:")
print(len(memory_df))

latest = memory_df.iloc[-1]

print("\nLATEST PARQUET INITIATIVE:\n")

print(latest)

print("\nEXPECTED NARRATIVE:\n")

state = latest["state"]

direction = latest["direction"]

if state == "DEFENDED":

    print(
        f"{direction.lower()} initiative continues defending its origin zone."
    )

    print(
        "Persistent participation continues supporting directional continuation."
    )
