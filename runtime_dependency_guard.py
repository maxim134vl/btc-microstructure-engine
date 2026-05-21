import os
import pandas as pd

STATE_FILE = (
    "runtime_dependency_state.parquet"
)

# =====================================
# SHOULD RUN ENGINE
# =====================================

def should_run_engine(

    engine_name,
    dependency_files

):

    current_state = {}

    for file in dependency_files:

        if not os.path.exists(file):

            current_state[file] = (
                "MISSING"
            )

            continue

        current_state[file] = str(
            os.path.getmtime(file)
        )

    current_signature = str(
        current_state
    )

    if os.path.exists(STATE_FILE):

        old = pd.read_parquet(
            STATE_FILE
        )

        old_engine = old[
            old["engine"]
            ==
            engine_name
        ]

        if len(old_engine) > 0:

            previous_signature = (
                old_engine.iloc[-1][
                    "signature"
                ]
            )

            if previous_signature == current_signature:

                return False

    row = pd.DataFrame([{

        "engine":
            engine_name,

        "signature":
            current_signature

    }])

    try:

        old = pd.read_parquet(
            STATE_FILE
        )

        row = pd.concat([
            old,
            row
        ])

    except:

        pass

    row.to_parquet(
        STATE_FILE,
        index=False
    )

    return True
