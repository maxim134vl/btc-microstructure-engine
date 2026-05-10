import requests
import pandas as pd
import time
from datetime import datetime

# =================================
# STORAGE
# =================================

history = []

print()
print(
    "OPTIONS OI COLLECTOR STARTED"
)
print()

# =================================
# LOOP
# =================================

while True:

    try:

        # =================================
        # GET INSTRUMENTS
        # =================================

        url = (

            "https://www.deribit.com"
            "/api/v2/public/get_instruments"
        )

        params = {

            "currency": "BTC",

            "kind": "option",

            "expired": False
        }

        response = requests.get(

            url,

            params=params,

            timeout=10
        )

        instruments = (

            response.json()
            ['result']
        )

        rows = []

        # =================================
        # LOOP OPTIONS
        # =================================

        for inst in instruments:

            try:

                instrument_name = (
                    inst[
                        'instrument_name'
                    ]
                )

                strike = (
                    inst[
                        'strike'
                    ]
                )

                option_type = (
                    inst[
                        'option_type'
                    ]
                )

                expiration = (
                    inst[
                        'expiration_timestamp'
                    ]
                )

                # =================================
                # BOOK SUMMARY
                # =================================

                summary_url = (

                    "https://www.deribit.com"
                    "/api/v2/public/get_book_summary_by_instrument"
                )

                summary_params = {

                    "instrument_name":
                        instrument_name
                }

                summary_response = requests.get(

                    summary_url,

                    params=summary_params,

                    timeout=10
                )

                summary = (

                    summary_response.json()
                    ['result'][0]
                )

                rows.append({

                    'timestamp':
                        datetime.utcnow(),

                    'instrument':
                        instrument_name,

                    'strike':
                        strike,

                    'type':
                        option_type,

                    'expiration':
                        expiration,

                    'open_interest':
                        summary.get(
                            'open_interest',
                            0
                        ),

                    'volume':
                        summary.get(
                            'volume',
                            0
                        ),

                    'iv':
                        summary.get(
                            'mark_iv',
                            0
                        ),

                    'underlying_price':
                        summary.get(
                            'underlying_price',
                            0
                        )
                })

            except:

                continue

        # =================================
        # DATAFRAME
        # =================================

        df = pd.DataFrame(rows)

        # =================================
        # SAVE
        # =================================

        try:

            old = pd.read_parquet(
                "options_oi.parquet"
            )

            df = pd.concat([

                old,

                df
            ])

        except:

            pass

        df.to_parquet(
            "options_oi.parquet"
        )

        # =================================
        # STATUS
        # =================================

        print("================================")
        print(
            datetime.utcnow()
        )
        print("================================")

        print()

        print(
            "OPTIONS:",
            len(rows)
        )

        print(
            "TOTAL ROWS:",
            len(df)
        )

        print()

        print(
            "UPDATED"
        )

        print()

        # =================================
        # WAIT
        # =================================

        time.sleep(300)

    except Exception as e:

        print()
        print("ERROR")
        print(e)
        print()

        time.sleep(30)
