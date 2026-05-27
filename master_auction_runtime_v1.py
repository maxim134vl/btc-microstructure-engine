import os
import time
import subprocess

import adaptive_meta_cognition_engine_v1
import probabilistic_auction_engine_v1
import auction_reinforcement_engine_v1

from datetime import datetime
from engine_registry import ENGINES

from state_manager_v1 import (
    refresh_state
)

from runtime_state_manager import (
    update_runtime_state
)

from runtime_dependency_map import (
    DEPENDENCIES
)

from runtime_dependency_guard import (
    should_run_engine
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

    "runtime_cognition_engine_v1.py",

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

        if engine in DEPENDENCIES:

            should_run = should_run_engine(

                engine,

                DEPENDENCIES[engine]

            )

            if not should_run:

                print(
                    "SKIPPED:",
                    engine
                )

                print()

                continue

        start_time = time.time()

        try:

            if engine in ENGINES:

                ENGINES[engine]()

            else:

                result = subprocess.run(

                    [
                        "python3",
                        engine
                    ],

                    capture_output=False,
                    text=True

                )

                if result.returncode != 0:

                    raise Exception(
                        f"ENGINE FAILED: {engine}"
                    )

            duration = round(
                time.time() - start_time,
                2
            )

            print(
                f"SUCCESS ({duration}s)"
            )

            update_runtime_state(
                engine,
                "SUCCESS",
                duration
            )

        except Exception as e:

            duration = round(
                time.time() - start_time,
                2
            )

            print(
                f"FAILED ({duration}s)"
            )

            update_runtime_state(
                engine,
                "FAILED",
                duration
            )

            print(e)

        print()

    time.sleep(5)
