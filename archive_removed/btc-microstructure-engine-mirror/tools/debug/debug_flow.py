import pandas as pd

df = pd.read_parquet("multi_exchange_flow.parquet")

print(df.columns)
print(df.tail())
