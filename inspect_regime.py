import pandas as pd

df = pd.read_parquet("regime_history.parquet")

print(df.columns)
print(df.head())
print(df.tail())
