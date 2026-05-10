import ccxt
import pandas as pd
import time

exchange = ccxt.binance()

symbol = 'BTC/USDT'
timeframe = '15m'

all_data = []

since = exchange.parse8601('2020-01-01T00:00:00Z')

while True:

    try:

        bars = exchange.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            since=since,
            limit=1000
        )

        if len(bars) == 0:
            break

        all_data.extend(bars)

        since = bars[-1][0] + 1

        print(f"Downloaded candles: {len(all_data)}")

        time.sleep(0.2)

    except Exception as e:
        print(e)
        time.sleep(5)

df = pd.DataFrame(
    all_data,
    columns=[
        'timestamp',
        'open',
        'high',
        'low',
        'close',
        'volume'
    ]
)

df['timestamp'] = pd.to_datetime(
    df['timestamp'],
    unit='ms'
)

df.to_parquet('btc_15m.parquet')

print(df.head())
print("DONE")
