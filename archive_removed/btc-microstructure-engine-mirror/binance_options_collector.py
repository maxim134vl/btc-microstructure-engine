import requests
import pandas as pd
import time

from datetime import datetime

# =================================
# START
# =================================

print()
print(
    "BINANCE OPTIONS UNIVERSE COLLECTOR"
)
print()

# =================================
# LOOP
# =================================

while True:

    try:

        # =================================
        # EXCHANGE INFO
        # =================================

        exchange_url = (

            "https://eapi.binance.com"
            "/eapi/v1/exchangeInfo"
        )

        exchange_response = requests.get(

            exchange_url,

            timeout=30
        )

        exchange_data = (

            exchange_response.json()
        )

        option_symbols = []

        for item in exchange_data['optionSymbols']:

            try:

                symbol = str(
                    item.get(
                        'symbol',
                        ''
                    )
                )

                if not symbol.startswith("BTC"):

                    continue

                option_symbols.append({

                    'symbol':
                        symbol,

                    'expiration':
                        str(
                            item.get(
                                'expiryDate',
                                ''
                            )
                        ),

                    'strike':
                        float(
                            item.get(
                                'strikePrice',
                                0
                            )
                        ),

                    'type':
                        str(
                            item.get(
                                'side',
                                ''
                            )
                        )
                })

            except:

                continue

        # =================================
        # LIVE TICKERS
        # =================================

        ticker_url = (

            "https://eapi.binance.com"
            "/eapi/v1/ticker"
        )

        ticker_response = requests.get(

            ticker_url,

            timeout=30
        )

        ticker_data = (

            ticker_response.json()
        )

        ticker_map = {}

        for t in ticker_data:

            try:

                ticker_map[
                    str(
                        t.get(
                            'symbol',
                            ''
                        )
                    )
                ] = t

            except:

                continue

        # =================================
        # BUILD ROWS
        # =================================

        rows = []

        for opt in option_symbols:

            try:

                symbol = opt['symbol']

                ticker = ticker_map.get(
                    symbol,
                    {}
                )

                rows.append({

                    'timestamp':
                        str(
                            datetime.utcnow()
                        ),

                    'symbol':
                        symbol,

                    'expiration':
                        str(
                            opt['expiration']
                        ),

                    'strike':
                        float(
                            opt['strike']
                        ),

                    'type':
                        str(
                            opt['type']
                        ),

                    'volume':
                        float(
                            ticker.get(
                                'volume',
                                0
                            )
                        ),

                    'quote_volume':
                        float(
                            ticker.get(
                                'quoteVolume',
                                0
                            )
                        ),

                    'last_price':
                        float(
                            ticker.get(
                                'lastPrice',
                                0
                            )
                        ),

                    'bid':
                        float(
                            ticker.get(
                                'bidPrice',
                                0
                            )
                        ),

                    'ask':
                        float(
                            ticker.get(
                                'askPrice',
                                0
                            )
                        ),

                    'underlying':
                        float(
                            ticker.get(
                                'underlyingPrice',
                                0
                            )
                        )
                })

            except:

                continue

        # =================================
        # DATAFRAME
        # =================================

        new_data = pd.DataFrame(rows)

        # =================================
        # LOAD OLD
        # =================================

        try:

            old = pd.read_parquet(
                "binance_options.parquet"
            )

            combined = pd.concat([

                old,

                new_data
            ])

        except:

            combined = new_data

        # =================================
        # SAVE
        # =================================

        combined.to_parquet(
            "binance_options.parquet"
        )

        # =================================
        # METRICS
        # =================================

        total_volume = (

            new_data[
                'volume'
            ]
            .sum()
        )

        avg_underlying = (

            new_data[
                'underlying'
            ]
            .replace(0, pd.NA)
            .dropna()
            .mean()
        )

        # =================================
        # OUTPUT
        # =================================

        print("================================")
        print(
            datetime.utcnow()
        )
        print("================================")

        print()

        print(
            "TOTAL BTC OPTIONS:",
            len(new_data)
        )

        print(
            "TOTAL DATA ROWS:",
            len(combined)
        )

        print()

        print(
            "TOTAL VOLUME:",
            round(
                total_volume,
                2
            )
        )

        print(
            "BTC PRICE:",
            round(
                avg_underlying,
                2
            )
        )

        print()

        print(
            "UPDATED SUCCESSFULLY"
        )

        print()

        # =================================
        # WAIT
        # =================================

        time.sleep(300)

    except Exception as e:

        print()
        print("ERROR")
        print(type(e).__name__)
        print(e)
        print()

        time.sleep(60)
