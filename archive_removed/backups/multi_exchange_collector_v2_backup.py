import requests
import pandas as pd
import numpy as np
import time
import os

# =================================
# START
# =================================

print()
print(
    "MULTI EXCHANGE COLLECTOR"
)
print()

# =================================
# CONFIG
# =================================

PARQUET_FILE = (
    "multi_exchange_flow.parquet"
)

SAVE_INTERVAL = 5

MAX_ROWS = 100000

# =================================
# HTTP SESSION
# =================================

session = requests.Session()

# =================================
# SAFE SAVE
# =================================

def safe_save(snapshot_df):

    try:

        old = pd.read_parquet(
            PARQUET_FILE
        )

    except Exception:

        old = pd.DataFrame()

    combined = pd.concat(

        [old, snapshot_df],

        ignore_index=True

    )

    # =================================
    # CLEANUP
    # =================================

    combined = combined.drop_duplicates()

    combined = combined.sort_values(
        "timestamp"
    )

    # =================================
    # LIMIT DATASET
    # =================================

    if len(combined) > MAX_ROWS:

        combined = combined.iloc[
            -MAX_ROWS:
        ]

    # =================================
    # ATOMIC WRITE
    # =================================

    temp_file = (
        PARQUET_FILE + ".tmp"
    )

    combined.to_parquet(
        temp_file,
        index=False
    )

    os.replace(
        temp_file,
        PARQUET_FILE
    )

    return combined

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
            df["side"]
            ==
            "Buy"
        ][
            "size"
        ]
        .sum()
    )

    sell_volume = (

        df[
            df["side"]
            ==
            "Sell"
        ][
            "size"
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
            "price"
        ]
        .mean()

    )

    price_change = (

        df[
            "price"
        ]
        .iloc[-1]

        -

        df[
            "price"
        ]
        .iloc[0]

    )

    total_volume = (

        buy_volume
        +
        sell_volume

    )

    efficiency = (

        abs(price_change)

        /

        (
            total_volume
            +
            1
        )

    )

    snapshot = pd.DataFrame([{

        "timestamp":
            pd.Timestamp.now().tz_localize(None),

        "exchange":
            exchange,

        "buy_volume":
            buy_volume,

        "sell_volume":
            sell_volume,

        "delta":
            delta,

        "trade_count":
            len(df),

        "avg_price":
            avg_price,

        "price_change":
            price_change,

        "efficiency":
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

        r = session.get(
            url,
            timeout=20
        )

        trades = r.json()

        rows = []

        for t in trades:

            side = "Buy"

            if t["isBuyerMaker"]:

                side = "Sell"

            rows.append({

                "price":
                    float(
                        t["price"]
                    ),

                "size":
                    float(
                        t["qty"]
                    ),

                "side":
                    side
            })

        return build_snapshot(
            rows,
            "BINANCE"
        )

    except Exception as e:

        print()
        print("BINANCE ERROR")
        print(e)

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

        r = session.get(
            url,
            timeout=20
        )

        data = r.json()

        trades = data[
            "result"
        ][
            "list"
        ]

        rows = []

        for t in trades:

            rows.append({

                "price":
                    float(
                        t["price"]
                    ),

                "size":
                    float(
                        t["size"]
                    ),

                "side":
                    t["side"]

            })

        return build_snapshot(
            rows,
            "BYBIT"
        )

    except Exception as e:

        print()
        print("BYBIT ERROR")
        print(e)

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

        r = session.post(

            url,

            json=payload,

            timeout=20

        )

        trades = r.json()

        rows = []

        for t in trades:

            side = "Buy"

            if t.get("side") == "A":

                side = "Sell"

            rows.append({

                "price":
                    float(
                        t["px"]
                    ),

                "size":
                    float(
                        t["sz"]
                    ),

                "side":
                    side

            })

        return build_snapshot(
            rows,
            "HYPERLIQUID"
        )

    except Exception as e:

        print()
        print("HYPERLIQUID ERROR")
        print(e)

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

        r = session.get(
            url,
            timeout=20
        )

        data = r.json()

        # =================================
        # VALIDATION
        # =================================

        if "data" not in data:

            print()
            print("HUOBI INVALID RESPONSE")
            print(data)

            return None

        rows = []

        for batch in data["data"]:

            for t in batch["data"]:

                rows.append({

                    "price":
                        float(
                            t["price"]
                        ),

                    "size":
                        float(
                            t["amount"]
                        ),

                    "side":

                        "Buy"

                        if

                        t["direction"]
                        ==
                        "buy"

                        else

                        "Sell"

                })

        return build_snapshot(
            rows,
            "HUOBI"
        )

    except Exception as e:

        print()
        print("HUOBI ERROR")
        print(e)

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

        ]:

            result = fn()

            if result is not None:

                snapshots.append(
                    result
                )

        # =================================
        # EMPTY PROTECTION
        # =================================

        if len(snapshots) == 0:

            print()
            print("NO SNAPSHOTS COLLECTED")

            time.sleep(SAVE_INTERVAL)

            continue

        combined_snapshot = pd.concat(
            snapshots,
            ignore_index=True
        )

        # =================================
        # NAN CLEANUP
        # =================================

        combined_snapshot = (
            combined_snapshot
            .dropna()
        )

        # =================================
        # SAVE
        # =================================

        combined = safe_save(
            combined_snapshot
        )

        # =================================
        # OUTPUT
        # =================================

        print("================================")

        print(
            pd.Timestamp.now()
        )

        print("================================")

        print()

        for _, row in combined_snapshot.iterrows():

            print(

                row["exchange"],

                "| DELTA:",

                round(
                    row["delta"],
                    2
                ),

                "| VOLUME:",

                round(

                    row["buy_volume"]
                    +
                    row["sell_volume"],

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

        time.sleep(SAVE_INTERVAL)

    except Exception as e:

        print()
        print("RUNTIME ERROR")
        print(type(e).__name__)
        print(e)
        print()

        time.sleep(10)
