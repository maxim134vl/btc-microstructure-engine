import subprocess
import time

from datetime import datetime

# =================================
# LIVE PIPELINE
# =================================

PIPELINE = [

    # normalization

    "engines/volume_normalizer.py",

    # divergence

    "engines/divergence_engine.py",

    "engines/divergence_aftermath_engine.py",

    # unified features

    "engines/unified_feature_matrix.py",

    # ML inference

    "models/first_transition_model.py"
]

# =================================
# START
# =================================

print()
print(
    "LIVE ANALYTICS PIPELINE"
)
print()

# =================================
# LOOP
# =================================

while True:

    print("================================")

    print(
        datetime.utcnow()
    )

    print("================================")

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
