import pandas as pd

print("\nDEBUG CURRENT INITIATIVE\n")

memory = pd.read_parquet(
    "initiative_memory.parquet"
)

latest = memory.iloc[-1]

print(latest)
