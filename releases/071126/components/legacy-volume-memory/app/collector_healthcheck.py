import os

import pandas as pd

from datetime import datetime

from runtime_config import (
    LEGACY_LIVE_FEED_PARQUET,
    LIVE_MARKET_FEED_PARQUET,
)

DATASETS = {

    "live_feed":
        LIVE_MARKET_FEED_PARQUET,

    "live_feed_legacy_mirror":
        LEGACY_LIVE_FEED_PARQUET,

    "oi":
        "datasets/oi",

    "orderbook":
        "datasets/orderbook",

    "multi_exchange":
        "datasets/multi_exchange"

}

STALE_THRESHOLD = 60

print()
print("=" * 60)
print("COLLECTOR HEALTHCHECK")
print("=" * 60)

now = datetime.now()

# =====================================
# CHECKS
# =====================================

for name, path in DATASETS.items():

    print()
    print(name)

    try:

        # =====================================
        # DIRECTORY DATASETS
        # =====================================

        if os.path.isdir(path):

            files = sorted(

                [

                    os.path.join(path, f)

                    for f in os.listdir(path)

                    if f.endswith(".parquet")

                ]

            )

            if len(files) == 0:

                print("STATE: EMPTY")

                continue

            latest_file = files[-1]

            df = pd.read_parquet(
                latest_file
            )

        else:

            df = pd.read_parquet(
                path
            )

        if len(df) == 0:

            print("STATE: EMPTY")

            continue

        latest_timestamp = pd.to_datetime(

            df.iloc[-1]["timestamp"]

        )

        lag = (

            now - latest_timestamp.to_pydatetime()

        ).total_seconds()

        stale = (
            lag > STALE_THRESHOLD
        )

        if stale:

            state = "STALE"

        else:

            state = "LIVE"

        print(
            "STATE:",
            state
        )

        print(
            "ROWS:",
            len(df)
        )

        print(
            "LAST UPDATE:",
            round(lag, 2),
            "sec ago"
        )

    except Exception as e:

        print(
            "STATE: FAILED"
        )

        print(type(e).__name__)
        print(e)
