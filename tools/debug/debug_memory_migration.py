import pandas as pd

print("\nDEBUG MEMORY MIGRATION\n")

memory = pd.read_parquet(
    "initiative_memory.parquet"
)

# ADD MISSING COLUMN

if "successful_tests" not in memory.columns:

    memory["successful_tests"] = 0

    print(
        "successful_tests column added."
    )

# SAVE UPDATED MEMORY

memory.to_parquet(
    "initiative_memory.parquet",
    index=False
)

print("\nUPDATED COLUMNS:\n")

print(memory.columns)

print("\nLAST 5 ROWS:\n")

print(
    memory.tail(5)[
        [
            "direction",
            "state",
            "successful_tests"
        ]
    ]
)
