import os
from datetime import datetime

import pandas as pd

from parquet_utils import atomic_parquet_write, safe_read_parquet

STATE_FILE = (
    "runtime_engine_state.parquet"
)

MAX_ROWS = 50000


def update_runtime_state(

    engine,
    status,
    duration

):
    """Append engine status. Never raise — status write must not kill runtime."""

    try:

        existing = safe_read_parquet(
            STATE_FILE
        )

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

        atomic_parquet_write(
            combined,
            STATE_FILE
        )

    except Exception as exc:
        # Status sidecar is best-effort. A failed write during engine exception
        # handling must not cascade and take down the whole runtime.
        print(
            f"WARNING: update_runtime_state failed for {engine} "
            f"status={status}: {exc}"
        )
        try:
            audit_dir = os.path.join("reports", "runtime_loop")
            os.makedirs(audit_dir, exist_ok=True)
            audit_path = os.path.join(audit_dir, "runtime_state_write_failures.jsonl")
            with open(audit_path, "a", encoding="utf-8") as handle:
                handle.write(
                    f'{{"timestamp":"{datetime.now().isoformat()}",'
                    f'"engine":"{engine}","status":"{status}",'
                    f'"error":"{str(exc).replace(chr(34), chr(39))}"}}\n'
                )
        except Exception:
            pass
        return
