import requests
import pandas as pd
from datetime import datetime

print("\nHISTORICAL BOOTSTRAP LOADER STARTED\n")

# =====================================
# SETTINGS
# =====================================

symbol = "BTCUSDT"

interval = "15m"

limit = 1000

url = (
    "https://api.binance.com/api/v3/klines"
)

# =====================================
# REQUEST
# =====================================

params = {

    "symbol": symbol,

    "interval": interval,

    "limit": limit

}

response = requests.get(
    url,
    params=params
)

data = response.json()

# =====================================
# PARSE
# =====================================

rows = []

for k in data:

    rows.append({

        "timestamp":
            datetime.fromtimestamp(
                k[0] / 1000
            ),

        "open":
            float(k[1]),

        "high":
            float(k[2]),

        "low":
            float(k[3]),

        "close":
            float(k[4]),

        "volume":
            float(k[5])

    })

df = pd.DataFrame(rows)

# =====================================
# SAVE
# =====================================

df.to_parquet(
    "live_market_feed.parquet"
)

# =====================================
# DEBUG
# =====================================

print("=" * 50)

print("BOOTSTRAP COMPLETE")

print("=" * 50)

print()

print(
    f"CANDLES LOADED: {len(df)}"
)

print()

print(df.tail(5))

print()

print("MEMORY SAVED:")

print(
    "live_market_feed.parquet"
)

print()
