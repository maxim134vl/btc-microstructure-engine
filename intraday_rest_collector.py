import requests
import pandas as pd
import time
import os

from datetime import datetime

# ---------------------------------
# CONFIG
# ---------------------------------

PARQUET_FILE = (
    "intraday_flow.parquet"
)

SLEEP_INTERVAL = 5

# ---------------------------------
# LOAD EXISTING DATA
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
        "LOADED EXISTING HISTORY:",
        len(history)
    )

else:

    history = []

# ---------------------------------
# LAST TRADE ID
# ---------------------------------

last_trade_id = None

print()
print(
    "STARTING INTRADAY COLLECTOR"
)

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
            "fapi/v1/aggTrades"
        )

        params = {

            "symbol": "BTCUSDT",

            "limit": 1000
        }

        response = requests.get(

            url,

            params=params,

            timeout=10
        )

        trades = response.json()

        # ---------------------------------
        # VALIDATION
        # ---------------------------------

        if not isinstance(
            trades,
            list
        ):

            print()
            print("API ERROR")

            print(trades)

            time.sleep(
                SLEEP_INTERVAL
            )

            continue

        # ---------------------------------
        # PROCESS
        # ---------------------------------

        new_rows = 0

        for trade in trades:

            trade_id = trade['a']

            # SKIP OLD

            if (

                last_trade_id
                is not None

                and

                trade_id
                <=
                last_trade_id
            ):

                continue

            price = float(
                trade['p']
            )

            qty = float(
                trade['q']
            )

            side = (

                -1
                if trade['m']
                else 1
            )

            delta = (
                qty * side
            )

            # ---------------------------------
            # STORE
            # ---------------------------------

            history.append({

                'timestamp':
                    datetime.utcnow(),

                'price':
                    price,

                'qty':
                    qty,

                'side':
                    side,

                'delta':
                    delta,

                'avg_price':
                    price,

                'price_change':
                    0,

                'efficiency':
                    0
            })

            new_rows += 1

        # ---------------------------------
        # UPDATE LAST ID
        # ---------------------------------

        if len(trades) > 0:

            last_trade_id = (
                trades[-1]['a']
            )

        # ---------------------------------
        # DATAFRAME
        # ---------------------------------

        df = pd.DataFrame(
            history
        )

        # ---------------------------------
        # CALCULATIONS
        # ---------------------------------

        if len(df) > 2:

            df['price_change'] = (

                df['avg_price']
                .diff()
            )

            rolling_delta = (

                df['delta']
                .rolling(20)
                .sum()
            )

            rolling_move = (

                df['price_change']
                .rolling(20)
                .sum()
            )

            df['efficiency'] = (

                rolling_move
                /
                rolling_delta.abs()
            )

            df['efficiency'] = (

                df['efficiency']
                .fillna(0)
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
            "NEW ROWS:",
            new_rows
        )

        print(
            "LAST PRICE:",
            round(
                df.iloc[-1][
                    'avg_price'
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
