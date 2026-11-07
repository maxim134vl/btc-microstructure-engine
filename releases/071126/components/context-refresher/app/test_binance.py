import websocket
import json

def on_message(ws, message):

    data = json.loads(message)

    print(data)

socket = "wss://fstream.binance.com/ws/btcusdt@aggTrade"

ws = websocket.WebSocketApp(
    socket,
    on_message=on_message
)

print("STARTING")

ws.run_forever()
