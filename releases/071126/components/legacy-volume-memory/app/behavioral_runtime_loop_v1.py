import subprocess
import time
from datetime import datetime

print()
print("BEHAVIORAL RUNTIME LOOP")
print()

# =====================================
# PIPELINE
# =====================================

PIPELINE = [

    "behavioral_sequence_memory_v1.py",

    "behavioral_volume_observer_v1.py",

    "behavioral_execution_engine_v1.py",

    "behavioral_runtime_orchestrator_v1.py"
]

# =====================================
# LOOP
# =====================================

while True:

    print(
        "================================"
    )

    print(
        datetime.utcnow()
    )

    print(
        "================================"
    )

    print()

    for script in PIPELINE:

        try:

            print(
                "RUNNING:",
                script
            )

            result = subprocess.run(

                ["python3", script],

                capture_output=True,

                text=True
            )

            if result.returncode == 0:

                print(
                    "SUCCESS"
                )

            else:

                print(
                    "FAILED"
                )

                print(
                    result.stderr
                )

        except Exception as e:

            print(
                "ERROR:",
                script
            )

            print(e)

        print()

    print(
        "PIPELINE CYCLE COMPLETE"
    )

    print()

    # =================================
    # WAIT
    # =================================

    time.sleep(30)
