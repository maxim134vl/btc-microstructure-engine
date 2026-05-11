import asyncio
import json
import ssl
import time
import websockets
import pandas as pd

from datetime import datetime

SSL_CONTEXT = ssl._create_unverified_context()

print()
print("HYPERLIQUID LIQUIDATION COLLECTOR")
print()

async def collect():

    while True:

        try:

            uri = "wss://api.hyperliquid.xyz/ws"

            async with websockets.connect(

                uri,

                ssl=SSL_CONTEXT,

                ping_interval=20,

                ping_timeout=20

            ) as ws:

                print("CONNECTED")
                print()

                subscribe = {

                    "method": "subscribe",

                    "subscription": {

                        "type": "liquidation"
                    }
                }

                await ws.send(
                    json.dumps(subscribe)
                )

                while True:

                    try:

                        message = await asyncio.wait_for(

                            ws.recv(),

                            timeout=60
                        )

                        data = json.loads(
                            message
                        )

                        # =========================
                        # VALIDATE
                        # =========================

                        if 'channel' not in data:

                            continue

                        if data['channel'] != 'liquidation':

                            continue

                        liquidation = data.get(
                            'data',
                            {}
                        )

                        if len(liquidation) == 0:

                            continue

                        # =========================
                        # EXTRACT
                        # =========================

                        price = float(

                            liquidation.get(
                                'px',
                                0
                            )
                        )

                        size = float(

                            liquidation.get(
                                'sz',
                                0
                            )
                        )

                        snapshot = pd.DataFrame([{

                            'timestamp':
                                datetime.utcnow(),

                            'coin':
                                liquidation.get(
                                    'coin'
                                ),

                            'side':
                                liquidation.get(
                                    'side'
                                ),

                            'price':
                                price,

                            'size':
                                size,

                            'liquidation_value':
                                price * size
                        }])

                        # =========================
                        # SAVE
                        # =========================

                        try:

                            old = pd.read_parquet(
                                "liquidations.parquet"
                            )

                            combined = pd.concat([

                                old,

                                snapshot
                            ])

                        except:

                            combined = snapshot

                        combined.to_parquet(
                            "liquidations.parquet"
                        )

                        # =========================
                        # OUTPUT
                        # =========================

                        print(
                            "LIQUIDATION EVENT"
                        )

                        print()

                        print(

                            snapshot[
                                [

                                    'coin',

                                    'side',

                                    'price',

                                    'size',

                                    'liquidation_value'
                                ]
                            ]
                        )

                        print()

                    except asyncio.TimeoutError:

                        print(
                            "NO LIQUIDATIONS"
                        )

                        print()

                        break

        except Exception as e:

            if "Inactive" in str(e):

                print(
                    "CONNECTION INACTIVE"
                )

                print()

            else:

                print("ERROR")
                print(e)
                print()

        print(
            "RECONNECTING..."
        )

        print()

        time.sleep(5)

asyncio.run(
    collect()
)
