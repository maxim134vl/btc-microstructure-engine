import pandas as pd
import subprocess
import time

print("\nLIVE COGNITIVE ORCHESTRATOR V4 STARTED\n")

# =====================================
# SETTINGS
# =====================================

feed_file = "live_market_feed.parquet"

last_timestamp = None

# =====================================
# COGNITION PIPELINE
# =====================================

engines = [

    # =====================================
    # PRIMARY VOLUME PERCEPTION
    # =====================================

    "live_volume_flow_engine_v1.py",

    "volume_localization_engine_v2.py",

    # =====================================
    # STRUCTURAL INTERPRETATION
    # =====================================

    "candle_geometry_engine_v2.py",

    "test_recognition_engine_v1.py",

    "defended_liquidity_engine_v1.py",

    "liquidity_cluster_engine_v1.py",

    # =====================================
    # LIQUIDITY INTERACTION
    # =====================================

    "flow_liquidity_interaction_engine_v3.py",

    "event_chain_engine_v1.py",

    # =====================================
    # CONTEXTUAL VALIDATION
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

    "predictive_sequence_engine_v1.py",

    # =====================================
    # FINAL INFERENCE
    # =====================================

    "intent_emergence_engine_v1.py"

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

            last_timestamp = current_timestamp

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
