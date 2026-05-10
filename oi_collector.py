import requests
import pandas as pd
import time
import urllib3

from datetime import datetime

urllib3.disable_warnings()

# ---------------------------------
# CONFIG
# ---------------------------------

SAVE_INTERVAL = 10

PARQUET_FILE = (
    "oi_history.parquet"
)

# ---------------------------------
# STORAGE
# ---------------------------------

snapshots = []

print()
print("OI COLLECTOR STARTED")

# ---------------------------------
# LOOP
# ---------------------------------

while True:

    try:

        # ---------------------------------
        # BINANCE OI
        # ---------------------------------

        url = (
            "https://fapi.binance.com"
            "/fapi/v1/openInterest"
        )

        params = {

            "symbol": "BTCUSDT"
        }

        response = requests.get(
            url,
            params=params,
            timeout=30,
            verify=False
        )

        data = response.json()

        oi = float(
            data['openInterest']
        )

        # ---------------------------------
        # SNAPSHOT
        # ---------------------------------

        snapshot = {

            'timestamp':
                datetime.utcnow(),

            'open_interest':
                oi
        }

        snapshots.append(snapshot)

        # ---------------------------------
        # SAVE
        # ---------------------------------

        df = pd.DataFrame(
            snapshots
        )

        df.to_parquet(
            PARQUET_FILE,
            index=False
        )

        # ---------------------------------
        # PRINT
        # ---------------------------------

        print()
        print("================================")

        print(
            "Snapshots:",
            len(df)
        )

        print(
            "Open Interest:",
            round(oi, 2)
        )

        # ---------------------------------
        # SLEEP
        # ---------------------------------

        time.sleep(SAVE_INTERVAL)

    except Exception as e:

        print()
        print("ERROR")

        print(e)

        time.sleep(SAVE_INTERVAL)
