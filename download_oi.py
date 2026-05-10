import requests
import pandas as pd
import time

symbol = "BTCUSDT"

url = "https://fapi.binance.com/futures/data/openInterestHist"

all_data = []

end_time = None

for _ in range(20):

    params = {
        "symbol": symbol,
        "period": "15m",
        "limit": 500
    }

    if end_time is not None:
        params["endTime"] = end_time

    try:

        response = requests.get(
            url,
            params=params
        )

        data = response.json()

        # ---------------------------------
        # API ERROR
        # ---------------------------------

        if not isinstance(data, list):

            print("API ERROR")
            print(data)

            break

        if len(data) == 0:
            break

        all_data.extend(data)

        print(
            f"Downloaded OI rows: {len(all_data)}"
        )

        oldest_timestamp = int(
            data[0]['timestamp']
        )

        end_time = oldest_timestamp - 1

        time.sleep(0.2)

    except Exception as e:

        print(e)

        time.sleep(5)

# ---------------------------------
# DATAFRAME
# ---------------------------------

df = pd.DataFrame(all_data)

# REMOVE DUPLICATES

df = df.drop_duplicates()

# SORT

df = df.sort_values('timestamp')

# TIMESTAMP

df['timestamp'] = pd.to_datetime(
    df['timestamp'],
    unit='ms'
)

# FLOAT

df['sumOpenInterest'] = (
    df['sumOpenInterest']
    .astype(float)
)

# ---------------------------------
# SAVE
# ---------------------------------

df.to_parquet('btc_oi.parquet')

print()
print(df.head())

print()
print("OI DOWNLOAD DONE")
