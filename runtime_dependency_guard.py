import os
import pandas as pd

from storage.path_registry import resolve_read, resolve_write

STATE_FILE_KEY = "runtime_dependency_state.parquet"


def _resolve_dependencies(dependency_files):
    return [resolve_read(path) for path in dependency_files]


# =====================================
# SHOULD RUN ENGINE
# =====================================

def should_run_engine(

    engine_name,
    dependency_files

):

    current_state = {}

    resolved_deps = _resolve_dependencies(dependency_files)

    for file in resolved_deps:

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

    state_file = resolve_write(STATE_FILE_KEY)

    if os.path.exists(state_file):

        old = pd.read_parquet(
            state_file
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
            state_file
        )

        row = pd.concat([
            old,
            row
        ])

    except Exception:

        pass

    row.to_parquet(
        state_file,
        index=False
    )

    return True
