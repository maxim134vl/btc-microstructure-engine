import pandas as pd
import os

from datetime import datetime

STATE_FILE = (
    "runtime_engine_state.parquet"
)

MAX_ROWS = 50000

def update_runtime_state(

    engine,
    status,
    duration

):

    try:

        existing = pd.read_parquet(
            STATE_FILE
        )

    except Exception:

        existing = pd.DataFrame()

    row = pd.DataFrame([{

        "timestamp":
            datetime.now(),

        "engine":
            engine,

        "status":
            status,

        "duration":
            duration

    }])

    combined = pd.concat(

        [existing, row],

        ignore_index=True

    )

    combined = combined.iloc[
        -MAX_ROWS:
    ]

    temp_file = (
        STATE_FILE + ".tmp"
    )

    combined.to_parquet(
        temp_file,
        index=False
    )

    os.replace(
        temp_file,
        STATE_FILE
    )
