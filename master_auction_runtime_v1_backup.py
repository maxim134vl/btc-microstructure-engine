import os
import time

import adaptive_meta_cognition_engine_v1
import probabilistic_auction_engine_v1
import auction_reinforcement_engine_v1
from datetime import datetime
from engine_registry import ENGINES


from state_manager_v1 import (
    refresh_state
)

print()
print(
    "MASTER AUCTION RUNTIME"
)
print()

# =====================================
# PIPELINE
# =====================================

pipeline = [

    "candle_structure_engine_v1.py",

    "volume_classification_engine_v1.py",

    "schema_validation_engine_v1.py",

    "behavioral_sequence_memory_v1.py",

    "behavioral_volume_observer_v1.py",

    "microstructure_candle_engine_v1.py",

    "volume_response_engine_v1.py",

    "climactic_behavior_engine_v1.py",

    "auction_convergence_engine_v1.py",

    "auction_synthesis_engine_v1.py",

    "auction_reinforcement_engine_v1.py",

    "probabilistic_auction_engine_v1.py",

    "auction_decay_engine_v1.py",

    "state_transition_engine_v1.py",

    "adaptive_meta_cognition_engine_v1.py"

]

# =====================================
# LOOP
# =====================================

while True:

    print()
    print(
        "=" * 40
    )

    print(
        datetime.now()
    )

    print(
        "=" * 40
    )

    print()

    for engine in pipeline:

        print(
            "RUNNING:",
            engine
        )

        try:

            if engine in ENGINES:

                ENGINES[engine]()

            else:

                os.system(
                    f"python3 {engine}"
                )

            print(
                "SUCCESS"
            )

        except Exception as e:

            print(
                "FAILED"
            )

            print(e)

        print()

    time.sleep(5)

# =================================
# WAIT
# =================================

time.sleep(60)
