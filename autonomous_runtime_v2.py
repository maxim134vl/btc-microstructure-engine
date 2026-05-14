import os
import time
from datetime import datetime

print("\nAUTONOMOUS RECURSIVE RUNTIME V2 STARTED\n")

# =====================================
# PYTHON ENV
# =====================================

PYTHON = "venv/bin/python3"

# =====================================
# ENGINE LIST
# =====================================

engines = [

    "candle_geometry_incremental_v3.py",

    "volume_localization_incremental_v3.py",

    "test_recognition_engine_v1.py",

    "defended_liquidity_engine_v1.py",

    "live_volume_flow_engine_v1.py",

    "flow_liquidity_interaction_engine_v3.py",

    "intent_validation_engine_v1.py",

    "live_mutation_runtime_engine_v1.py",

    "cognitive_confidence_engine_v1.py",

    "temporal_decay_engine_v2.py",

    "volatility_adaptive_engine_v1.py",

    "htf_structure_engine_v1.py",

    "htf_ltf_context_engine_v1.py",

    "fractal_memory_engine_v1.py",

    "predictive_sequence_engine_v1.py"

]

# =====================================
# LOOP
# =====================================

while True:

    print("=" * 60)

    print(
        f"COGNITIVE CYCLE: {datetime.now()}"
    )

    print("=" * 60)

    print()

    # =====================================
    # RUN ENGINES
    # =====================================

    for i, engine in enumerate(

        engines,

        start=1

    ):

        print(
            f"STEP {i}: {engine}"
        )

        # =====================================
        # EXISTS CHECK
        # =====================================

        if not os.path.exists(engine):

            print(
                f"ENGINE NOT FOUND: {engine}"
            )

            print()

            continue

        # =====================================
        # RUN
        # =====================================

        exit_code = os.system(

            f"{PYTHON} {engine}"

        )

        # =====================================
        # RESULT
        # =====================================

        if exit_code == 0:

            print(
                f"SUCCESS: {engine}"
            )

        else:

            print(
                f"FAILED: {engine}"
            )

        print()

    # =====================================
    # COMPLETE
    # =====================================

    print("=" * 60)

    print(
        "COGNITIVE CYCLE COMPLETE"
    )

    print("=" * 60)

    print()

    # =====================================
    # WAIT
    # =====================================

    time.sleep(60)
