import asyncio
import websockets
import json
import ssl

ssl_context = ssl._create_unverified_context()

async def main():

    url = (
        "wss://fstream.binance.com/ws/"
        "btcusdt@aggTrade"
    )

    async with websockets.connect(
        url,
        ssl=ssl_context
    ) as ws:

        print("CONNECTED")

        while True:

            msg = await ws.recv()

            data = json.loads(msg)

            print(data)

asyncio.run(main())
