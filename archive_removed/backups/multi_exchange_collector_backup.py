import requests
import pandas as pd
import numpy as np
import time

from datetime import datetime

# =================================
# START
# =================================

print()
print(
    "MULTI EXCHANGE COLLECTOR"
)
print()

# =================================
# SNAPSHOT BUILDER
# =================================

def build_snapshot(
    rows,
    exchange
):

    if len(rows) == 0:

        return None

    df = pd.DataFrame(rows)

    buy_volume = (

        df[
            df['side']
            ==
            'Buy'
        ][
            'size'
        ]
        .sum()
    )

    sell_volume = (

        df[
            df['side']
            ==
            'Sell'
        ][
            'size'
        ]
        .sum()
    )

    delta = (

        buy_volume

        -

        sell_volume
    )

    avg_price = (

        df[
            'price'
        ]
        .mean()
    )

    price_change = (

        df[
            'price'
        ]
        .iloc[-1]

        -

        df[
            'price'
        ]
        .iloc[0]
    )

    total_volume = (

        buy_volume

        +

        sell_volume
    )

    efficiency = (

        abs(
            price_change
        )

        /

        (
            total_volume
            +
            1
        )
    )

    snapshot = pd.DataFrame([{

        'timestamp':
            datetime.utcnow(),

        'exchange':
            exchange,

        'buy_volume':
            buy_volume,

        'sell_volume':
            sell_volume,

        'delta':
            delta,

        'trade_count':
            len(df),

        'avg_price':
            avg_price,

        'price_change':
            price_change,

        'efficiency':
            efficiency
    }])

    return snapshot

# =================================
# BINANCE
# =================================

def collect_binance():

    try:

        url = (

            "https://fapi.binance.com"
            "/fapi/v1/trades"
            "?symbol=BTCUSDT"
            "&limit=1000"
        )

        r = requests.get(
            url,
            timeout=20
        )

        trades = r.json()

        rows = []

        for t in trades:

            side = 'Buy'

            if t['isBuyerMaker']:

                side = 'Sell'

            rows.append({

                'price':
                    float(
                        t['price']
                    ),

                'size':
                    float(
                        t['qty']
                    ),

                'side':
                    side
            })

        return build_snapshot(
            rows,
            'BINANCE'
        )

    except:

        return None

# =================================
# BYBIT
# =================================

def collect_bybit():

    try:

        url = (

            "https://api.bybit.com"
            "/v5/market/recent-trade"
            "?category=linear"
            "&symbol=BTCUSDT"
            "&limit=1000"
        )

        r = requests.get(
            url,
            timeout=20
        )

        data = r.json()

        trades = data[
            'result'
        ][
            'list'
        ]

        rows = []

        for t in trades:

            rows.append({

                'price':
                    float(
                        t['price']
                    ),

                'size':
                    float(
                        t['size']
                    ),

                'side':
                    t['side']
            })

        return build_snapshot(
            rows,
            'BYBIT'
        )

    except:

        return None

# =================================
# HYPERLIQUID
# =================================

def collect_hyperliquid():

    try:

        url = (
            "https://api.hyperliquid.xyz/info"
        )

        payload = {

            "type":
                "recentTrades",

            "coin":
                "BTC"
        }

        r = requests.post(

            url,

            json=payload,

            timeout=20
        )

        trades = r.json()

        rows = []

        for t in trades:

            side = 'Buy'

            if t.get('side') == 'A':

                side = 'Sell'

            rows.append({

                'price':
                    float(
                        t['px']
                    ),

                'size':
                    float(
                        t['sz']
                    ),

                'side':
                    side
            })

        return build_snapshot(
            rows,
            'HYPERLIQUID'
        )

    except:

        return None

# =================================
# HUOBI
# =================================

def collect_huobi():

    try:

        url = (

            "https://api.hbdm.com"
            "/swap-ex/market/history/trade"
            "?contract_code=BTC-USDT"
            "&size=50"
        )

        r = requests.get(
            url,
            timeout=20
        )

        data = r.json()

        rows = []

        for batch in data['data']:

            for t in batch['data']:

                rows.append({

                    'price':
                        float(
                            t['price']
                        ),

                    'size':
                        float(
                            t['amount']
                        ),

                    'side':
                        'Buy'
                        if
                        t['direction']
                        ==
                        'buy'
                        else
                        'Sell'
                })

        return build_snapshot(
            rows,
            'HUOBI'
        )

    except:

        return None

# =================================
# LOOP
# =================================

while True:

    try:

        snapshots = []

        for fn in [

            collect_binance,

            collect_bybit,

            collect_hyperliquid,

            collect_huobi
        ]:

            result = fn()

            if result is not None:

                snapshots.append(
                    result
                )

        combined_snapshot = pd.concat(
            snapshots
        )

        # =================================
        # LOAD OLD
        # =================================

        try:

            old = pd.read_parquet(
                "multi_exchange_flow.parquet"
            )

            combined = pd.concat([

                old,

                combined_snapshot
            ])

        except:

            combined = combined_snapshot

        # =================================
        # SAVE
        # =================================

        combined.to_parquet(
            "multi_exchange_flow.parquet"
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

        for _, row in combined_snapshot.iterrows():

            print(
                row['exchange'],
                "| DELTA:",
                round(
                    row['delta'],
                    2
                ),
                "| VOLUME:",
                round(
                    row[
                        'buy_volume'
                    ]
                    +
                    row[
                        'sell_volume'
                    ],
                    2
                )
            )

        print()

        print(
            "TOTAL ROWS:",
            len(combined)
        )

        print()

        print(
            "UPDATED SUCCESSFULLY"
        )

        print()

        time.sleep(5)

    except Exception as e:

        print()
        print("ERROR")
        print(type(e).__name__)
        print(e)
        print()

        time.sleep(10)
