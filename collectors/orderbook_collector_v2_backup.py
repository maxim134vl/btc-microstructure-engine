import requests
import pandas as pd
import time
import urllib3
import os

urllib3.disable_warnings()

print()
print("ORDERBOOK COLLECTOR STARTED")

# ---------------------------------
# CONFIG
# ---------------------------------

SAVE_INTERVAL = 5

PARQUET_FILE = (
    "orderbook.parquet"
)

MAX_ROWS = 100000

# ---------------------------------
# HTTP SESSION
# ---------------------------------

session = requests.Session()

# ---------------------------------
# SAFE SAVE
# ---------------------------------

def safe_append_snapshot(snapshot):

    try:

        existing = pd.read_parquet(
            PARQUET_FILE
        )

    except Exception:

        existing = pd.DataFrame()

    new_row = pd.DataFrame(
        [snapshot]
    )

    df = pd.concat(

        [existing, new_row],

        ignore_index=True

    )

    # ---------------------------------
    # CLEANUP
    # ---------------------------------

    df = df.drop_duplicates(
        subset=["timestamp"]
    )

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

# ---------------------------------
# MAIN LOOP
# ---------------------------------

while True:

    try:

        # ---------------------------------
        # API
        # ---------------------------------

        url = (
            "https://fapi.binance.com"
            "/fapi/v1/depth"
        )

        params = {

            "symbol": "BTCUSDT",

            "limit": 20
        }

        response = session.get(

            url,

            params=params,

            timeout=30

        )

        data = response.json()

        # ---------------------------------
        # VALIDATION
        # ---------------------------------

        if "bids" not in data:

            print()
            print("INVALID RESPONSE")
            print(data)

            time.sleep(SAVE_INTERVAL)

            continue

        bids = data["bids"]

        asks = data["asks"]

        if len(bids) == 0:

            print()
            print("EMPTY BIDS")

            time.sleep(SAVE_INTERVAL)

            continue

        if len(asks) == 0:

            print()
            print("EMPTY ASKS")

            time.sleep(SAVE_INTERVAL)

            continue

        # ---------------------------------
        # LIQUIDITY
        # ---------------------------------

        bid_liquidity = 0

        ask_liquidity = 0

        for b in bids:

            bid_liquidity += (

                float(b[0])
                *
                float(b[1])

            )

        for a in asks:

            ask_liquidity += (

                float(a[0])
                *
                float(a[1])

            )

        total = (

            bid_liquidity
            +
            ask_liquidity

        )

        imbalance = 0

        if total > 0:

            imbalance = (

                (
                    bid_liquidity
                    -
                    ask_liquidity
                )

                /

                total
            )

        # ---------------------------------
        # MID PRICE
        # ---------------------------------

        best_bid = float(
            bids[0][0]
        )

        best_ask = float(
            asks[0][0]
        )

        mid_price = (
            best_bid + best_ask
        ) / 2

        # ---------------------------------
        # SNAPSHOT
        # ---------------------------------

        snapshot = {

            "timestamp":
                pd.Timestamp.now().tz_localize(None),

            "bid_liquidity":
                bid_liquidity,

            "ask_liquidity":
                ask_liquidity,

            "imbalance":
                imbalance,

            "mid_price":
                mid_price
        }

        # ---------------------------------
        # VALIDATION
        # ---------------------------------

        values = [

            bid_liquidity,
            ask_liquidity,
            imbalance,
            mid_price

        ]

        if any(pd.isna(values)):

            print()
            print("NAN DETECTED")

            time.sleep(SAVE_INTERVAL)

            continue

        # ---------------------------------
        # SAVE
        # ---------------------------------

        safe_append_snapshot(
            snapshot
        )

        # ---------------------------------
        # DEBUG
        # ---------------------------------

        print()
        print("================================")

        print(
            "Bid Liquidity:",
            round(
                bid_liquidity,
                2
            )
        )

        print(
            "Ask Liquidity:",
            round(
                ask_liquidity,
                2
            )
        )

        print(
            "Imbalance:",
            round(
                imbalance,
                4
            )
        )

        print(
            "Mid Price:",
            round(
                mid_price,
                2
            )
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
