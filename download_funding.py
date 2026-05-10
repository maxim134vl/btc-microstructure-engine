import requests
import pandas as pd
import time

symbol = "BTCUSDT"

url = "https://fapi.binance.com/fapi/v1/fundingRate"

all_data = []

start_time = int(
    pd.Timestamp("2023-01-01").timestamp() * 1000
)

while True:

    params = {
        "symbol": symbol,
        "limit": 1000,
        "startTime": start_time
    }

    try:

        response = requests.get(
            url,
            params=params
        )

        data = response.json()

        if not isinstance(data, list):

            print("API ERROR")
            print(data)

            break

        if len(data) == 0:
            break

        all_data.extend(data)

        print(
            f"Downloaded funding rows: {len(all_data)}"
        )

        last_time = int(data[-1]['fundingTime'])

        start_time = last_time + 1

        time.sleep(0.2)

    except Exception as e:

        print(e)

        time.sleep(5)

# ---------------------------------
# DATAFRAME
# ---------------------------------

df = pd.DataFrame(all_data)

df['fundingTime'] = pd.to_datetime(
    df['fundingTime'],
    unit='ms'
)

df['fundingRate'] = (
    df['fundingRate']
    .astype(float)
)

# ---------------------------------
# SAVE
# ---------------------------------

df.to_parquet('btc_funding.parquet')

print(df.head())

print()
print("FUNDING DOWNLOAD DONE")
