import ccxt
import pandas as pd

exchange = ccxt.binance({

    "options": {
        "defaultType": "future"
    }

})

symbol = "BTC/USDT"
timeframe = "5m"

bars = exchange.fetch_ohlcv(

    symbol,
    timeframe=timeframe,
    limit=1500

)

df = pd.DataFrame(

    bars,

    columns=[

        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume"

    ]

)

df["timestamp"] = pd.to_datetime(
    df["timestamp"],
    unit="ms"
)

df.to_parquet(
    "btc_5m.parquet"
)

print()
print("BTC 5M SAVED")
print("btc_5m.parquet")
print()
