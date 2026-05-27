import pandas as pd

print("\nDEBUG INITIATIVE AGENT\n")

initiative = pd.read_parquet("initiative_memory.parquet")

print("\nLAST INITIATIVE\n")

latest = initiative.iloc[-1]

print(latest)

print("\nFIELDS\n")

print(initiative.columns)

print("\nINTERPRETATION\n")

direction = latest["direction"]
state = latest["state"]

if state == "DEFENDED":

    print(
        f"{direction} initiative continues defending its origin zone."
    )

elif state == "FAILED":

    print(
        f"{direction} initiative lost control of its origin zone."
    )

else:

    print(
        f"{direction} initiative remains active."
    )
