import asyncio
import aiohttp
import pandas as pd
from datetime import datetime

# =================================
# START
# =================================

print()
print(
    "BTC OPTIONS MARKET COLLECTOR"
)
print()

# =================================
# MAIN LOOP
# =================================

async def collect():

    while True:

        try:

            # =================================
            # REQUEST
            # =================================

            url = (

                "https://www.deribit.com"
                "/api/v2/public/get_book_summary_by_currency"
            )

            params = {

                "currency": "BTC",

                "kind": "option"
            }

            timeout = aiohttp.ClientTimeout(
                total=60
            )

            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:

                async with session.get(

                    url,

                    params=params,

                    ssl=False

                ) as response:

                    data = await response.json()

            data = data['result']

            rows = []

            # =================================
            # PARSE
            # =================================

            for item in data:

                try:

                    instrument = item.get(
                        'instrument_name'
                    )

                    parts = instrument.split("-")

                    expiration = None
                    strike = None
                    option_type = None

                    if len(parts) >= 4:

                        expiration = parts[1]

                        strike = float(
                            parts[2]
                        )

                        option_type = (
                            parts[3]
                        )

                    rows.append({

                        'timestamp':
                            datetime.utcnow(),

                        'instrument':
                            instrument,

                        'expiration':
                            expiration,

                        'strike':
                            strike,

                        'type':
                            option_type,

                        'open_interest':
                            item.get(
                                'open_interest',
                                0
                            ),

                        'volume':
                            item.get(
                                'volume',
                                0
                            ),

                        'iv':
                            item.get(
                                'mark_iv',
                                0
                            ),

                        'underlying_price':
                            item.get(
                                'underlying_price',
                                0
                            ),

                        'bid_price':
                            item.get(
                                'bid_price',
                                0
                            ),

                        'ask_price':
                            item.get(
                                'ask_price',
                                0
                            ),

                        'mark_price':
                            item.get(
                                'mark_price',
                                0
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
                    "options_market.parquet"
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
                "options_market.parquet"
            )

            # =================================
            # METRICS
            # =================================

            total_oi = (

                new_data[
                    'open_interest'
                ]
                .sum()
            )

            total_volume = (

                new_data[
                    'volume'
                ]
                .sum()
            )

            avg_iv = (

                new_data[
                    'iv'
                ]
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
                "OPTIONS:",
                len(new_data)
            )

            print(
                "TOTAL ROWS:",
                len(combined)
            )

            print()

            print(
                "TOTAL OI:",
                round(
                    total_oi,
                    2
                )
            )

            print(
                "TOTAL VOLUME:",
                round(
                    total_volume,
                    2
                )
            )

            print(
                "AVG IV:",
                round(
                    avg_iv,
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

            await asyncio.sleep(300)

        except Exception as e:

            print()
            print("ERROR")
            print(type(e).__name__)
            print(e)
            print()

            await asyncio.sleep(60)

# =================================
# RUN
# =================================

asyncio.run(
    collect()
)
