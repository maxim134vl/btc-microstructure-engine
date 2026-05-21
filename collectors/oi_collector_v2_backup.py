import requests
import pandas as pd
import time
import os

# ---------------------------------
# CONFIG
# ---------------------------------

PARQUET_FILE = (
    "oi_history.parquet"
)

SLEEP_INTERVAL = 10

MAX_ROWS = 100000

print()
print("STARTING OI COLLECTOR")

# ---------------------------------
# HTTP SESSION
# ---------------------------------

session = requests.Session()

# ---------------------------------
# SAFE SAVE
# ---------------------------------

def safe_append_record(record):

    try:

        existing = pd.read_parquet(
            PARQUET_FILE
        )

    except Exception:

        existing = pd.DataFrame()

    new_row = pd.DataFrame(
        [record]
    )

    df = pd.concat(

        [existing, new_row],

        ignore_index=True

    )

    # ---------------------------------
    # CLEANUP
    # ---------------------------------

    df = df.drop_duplicates()

    df = df.sort_values(
        "timestamp"
    )

    # ---------------------------------
    # LIMIT DATASET
    # ---------------------------------

    if len(df) > MAX_ROWS:

        df = df.iloc[-MAX_ROWS:]

    # ---------------------------------
    # ATOMIC WRITE
    # ---------------------------------

    temp_file = (
        PARQUET_FILE + ".tmp"
    )

    df.to_parquet(

        temp_file,

        index=False
    )

    os.replace(
        temp_file,
        PARQUET_FILE
    )

    return df

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

        response = session.get(

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

            print()
            print("EMPTY RESPONSE")

            time.sleep(
                SLEEP_INTERVAL
            )

            continue

        row = data[0]

        # ---------------------------------
        # RECORD
        # ---------------------------------

        record = {

            "timestamp":
                pd.Timestamp.now().tz_localize(None),

            "open_interest":
                float(
                    row[
                        "sumOpenInterest"
                    ]
                ),

            "open_interest_value":
                float(
                    row[
                        "sumOpenInterestValue"
                    ]
                )
        }

        # ---------------------------------
        # VALIDATION
        # ---------------------------------

        values = [

            record["open_interest"],

            record["open_interest_value"]

        ]

        if any(pd.isna(values)):

            print()
            print("NAN DETECTED")

            time.sleep(
                SLEEP_INTERVAL
            )

            continue

        # ---------------------------------
        # SAVE
        # ---------------------------------

        df = safe_append_record(
            record
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
                    "open_interest"
                ],
                2
            )
        )

        print(
            "OI VALUE:",
            round(
                record[
                    "open_interest_value"
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

        print(type(e).__name__)
        print(e)

        time.sleep(
            SLEEP_INTERVAL
        )
