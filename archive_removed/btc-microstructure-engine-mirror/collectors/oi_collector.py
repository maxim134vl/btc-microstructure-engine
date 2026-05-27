import requests
import pandas as pd
import time
import os

from datetime import datetime

# ---------------------------------
# CONFIG
# ---------------------------------

PARQUET_FILE = (
    "oi_history.parquet"
)

SLEEP_INTERVAL = 10

# ---------------------------------
# LOAD HISTORY
# ---------------------------------

if os.path.exists(
    PARQUET_FILE
):

    history = pd.read_parquet(
        PARQUET_FILE
    )

    history = history.to_dict(
        'records'
    )

    print()
    print(
        "LOADED EXISTING OI HISTORY:",
        len(history)
    )

else:

    history = []

print()
print("STARTING OI COLLECTOR")

# ---------------------------------
# LOOP
# ---------------------------------

while True:

    try:

        # ---------------------------------
        # API
        # ---------------------------------

        url = (

            "https://fapi.binance.com/"
            "futures/data/openInterestHist"
        )

        params = {

            "symbol": "BTCUSDT",

            "period": "5m",

            "limit": 1
        }

        response = requests.get(

            url,

            params=params,

            timeout=10
        )

        data = response.json()

        # ---------------------------------
        # VALIDATION
        # ---------------------------------

        if not isinstance(
            data,
            list
        ):

            print()
            print("API ERROR")

            print(data)

            time.sleep(
                SLEEP_INTERVAL
            )

            continue

        if len(data) == 0:

            time.sleep(
                SLEEP_INTERVAL
            )

            continue

        row = data[0]

        # ---------------------------------
        # RECORD
        # ---------------------------------

        record = {

            'timestamp':
                datetime.utcnow(),

            'open_interest':
                float(
                    row[
                        'sumOpenInterest'
                    ]
                ),

            'open_interest_value':
                float(
                    row[
                        'sumOpenInterestValue'
                    ]
                )
        }

        history.append(
            record
        )

        # ---------------------------------
        # DATAFRAME
        # ---------------------------------

        df = pd.DataFrame(
            history
        )

        # ---------------------------------
        # REMOVE DUPLICATES
        # ---------------------------------

        df = df.drop_duplicates()

        # ---------------------------------
        # SAVE
        # ---------------------------------

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
            "TOTAL ROWS:",
            len(df)
        )

        print(
            "OPEN INTEREST:",
            round(
                record[
                    'open_interest'
                ],
                2
            )
        )

        print(
            "OI VALUE:",
            round(
                record[
                    'open_interest_value'
                ],
                2
            )
        )

        # ---------------------------------
        # SLEEP
        # ---------------------------------

        time.sleep(
            SLEEP_INTERVAL
        )

    except Exception as e:

        print()
        print("ERROR")

        print(e)

        time.sleep(
            SLEEP_INTERVAL
        )
