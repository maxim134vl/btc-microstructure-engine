import pandas as pd
import subprocess
import time
from datetime import datetime

print("\nLIVE COGNITIVE ORCHESTRATOR STARTED\n")

# =====================================
# SETTINGS
# =====================================

feed_file = "live_market_feed.parquet"

last_timestamp = None

# =====================================
# LOOP
# =====================================

while True:

    try:

        # =====================================
        # LOAD LIVE FEED
        # =====================================

        df = pd.read_parquet(
            feed_file
        )

        df = df.sort_values(
            "timestamp"
        )

        latest = df.iloc[-1]

        current_timestamp = latest[
            "timestamp"
        ]

        # =====================================
        # NEW CANDLE CHECK
        # =====================================

        if current_timestamp != last_timestamp:

            print("=" * 60)

            print(
                f"NEW CANDLE DETECTED: "
                f"{current_timestamp}"
            )

            print("=" * 60)

            print()

            last_timestamp = (
                current_timestamp
            )

            # =====================================
            # RUN PIPELINE
            # =====================================

            engines = [

                "candle_geometry_engine_v2.py",

                "volume_localization_engine_v2.py",

                "test_recognition_engine_v1.py",

                "defended_liquidity_engine_v1.py",

                "liquidity_cluster_engine_v1.py",

                "event_chain_engine_v1.py",

                "intent_emergence_engine_v1.py"

            ]

            for engine in engines:

                print(
                    f"RUNNING: {engine}"
                )

                subprocess.run(

                    ["python3", engine]

                )

                print(
                    f"FINISHED: {engine}"
                )

                print()

            # =====================================
            # LOAD FINAL INTENT
            # =====================================

            intent_df = pd.read_parquet(
                "intent_emergence_memory.parquet"
            )

            latest_intents = (

                intent_df[
                    intent_df[
                        "market_intent"
                    ]
                    !=
                    "undefined"
                ]

                .tail(5)

            )

            print("=" * 60)

            print("LATEST MARKET INTENTS")

            print("=" * 60)

            print()

            print(

                latest_intents[
                    [

                        "chain_id",

                        "market_intent",

                        "confidence"

                    ]

                ]

            )

            print()

        # =====================================
        # WAIT
        # =====================================

        time.sleep(5)

    except Exception as e:

        print()

        print("ORCHESTRATOR ERROR:")

        print(e)

        print()

        time.sleep(5)
