import pandas as pd

print("\nDEBUG MEMORY FIELDS\n")

memory = pd.read_parquet(
    "initiative_memory.parquet"
)

print(memory.columns)

print("\nLAST ROW:\n")

print(memory.tail(1).T)
