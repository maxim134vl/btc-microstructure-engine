import pandas as pd
import subprocess
import time

print("\nLIVE COGNITIVE ORCHESTRATOR V3 STARTED\n")

# =====================================
# SETTINGS
# =====================================

feed_file = "live_market_feed.parquet"

last_timestamp = None

# =====================================
# ENGINES
# =====================================

engines = [

    # =====================================
    # CORE STRUCTURE
    # =====================================

    "candle_geometry_engine_v2.py",

    "volume_localization_engine_v2.py",

    "test_recognition_engine_v1.py",

    "defended_liquidity_engine_v1.py",

    "liquidity_cluster_engine_v1.py",

    "event_chain_engine_v1.py",

    "intent_emergence_engine_v1.py",

    # =====================================
    # FLOW COGNITION
    # =====================================

    "live_volume_flow_engine_v1.py",

    "flow_liquidity_interaction_engine_v3.py",

    # =====================================
    # VALIDATION
    # =====================================

    "intent_validation_engine_v1.py",

    # =====================================
    # ADAPTIVE LEARNING
    # =====================================

    "live_mutation_runtime_engine_v1.py",

    "cognitive_confidence_engine_v1.py",

    "temporal_decay_engine_v2.py",

    "volatility_adaptive_engine_v1.py",

    # =====================================
    # FRACTAL CONTEXT
    # =====================================

    "htf_structure_engine_v1.py",

    "htf_ltf_context_engine_v1.py",

    # =====================================
    # MEMORY
    # =====================================

    "fractal_memory_engine_v1.py",

    "predictive_sequence_engine_v1.py"

]

# =====================================
# MAIN LOOP
# =====================================

while True:

    try:

        # =====================================
        # LOAD FEED
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
        # NEW CANDLE
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

            for engine in engines:

                print(
                    f"RUNNING: {engine}"
                )

                try:

                    result = subprocess.run(

                        ["python3", engine],

                        capture_output=True,

                        text=True

                    )

                    if result.returncode == 0:

                        print(
                            f"SUCCESS: {engine}"
                        )

                    else:

                        print(
                            f"FAILED: {engine}"
                        )

                        print(
                            result.stderr
                        )

                except Exception as engine_error:

                    print(
                        f"ENGINE ERROR: {engine}"
                    )

                    print(
                        engine_error
                    )

                print()

            # =====================================
            # FINAL INTENTS
            # =====================================

            try:

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

                print(
                    "LATEST MARKET INTENTS"
                )

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

            except Exception as intent_error:

                print(
                    "INTENT LOAD ERROR"
                )

                print(
                    intent_error
                )

                print()

        # =====================================
        # WAIT
        # =====================================

        time.sleep(5)

    except Exception as e:

        print()

        print(
            "ORCHESTRATOR ERROR:"
        )

        print(e)

        print()

        time.sleep(5)
