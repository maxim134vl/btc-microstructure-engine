import pandas as pd

print("\nDEBUG MEMORY PERSISTENCE\n")

try:

    memory = pd.read_parquet(
        "initiative_memory.parquet"
    )

    print("INITIATIVES FOUND:")
    print(len(memory))

    print("\nLAST 5 INITIATIVES:\n")

    print(
        memory.tail(5)[
            [
                "direction",
                "state",
                "successful_tests"
            ]
        ]
    )

except Exception as e:

    print("\nERROR")
    print(e)
