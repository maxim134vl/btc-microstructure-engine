import pandas as pd

files = {
    "regime": "regime_history.parquet",
    "narrative": "market_narratives.parquet",
    "inventory": "inventory_states.parquet",
    "reaction": "volume_reactions.parquet",
    "acceptance": "acceptance_states.parquet",
    "vacuum": "liquidity_vacuums.parquet"
}

for name, file in files.items():

    print("\n====================")
    print(name.upper())
    print("====================")

    df = pd.read_parquet(file)

    print(df.columns)
