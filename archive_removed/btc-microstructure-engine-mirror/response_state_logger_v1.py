import time
import pandas as pd
from datetime import datetime

print()
print(
    "RESPONSE LOGGER STARTED"
)
print()

while True:

    try:

        response = pd.read_parquet(
            "volume_response_state.parquet"
        )

        latest = response.iloc[-1]

        row = pd.DataFrame([{

            "timestamp":
                datetime.now(),

            "volume_class":
                latest[
                    "volume_class"
                ],

            "volume_event":
                latest[
                    "volume_event"
                ],

            "continuation_quality":
                latest[
                    "continuation_quality"
                ],

            "unfinished_auction":
                latest[
                    "unfinished_auction"
                ],

            "effort_result_state":
                latest[
                    "effort_result_state"
                ],

            "participation_state":
                latest[
                    "participation_state"
                ]

        }])

        try:

            history = pd.read_parquet(
                "response_state_history.parquet"
            )

            history = pd.concat(
                [
                    history,
                    row
                ]
            )

        except:

            history = row

        history.to_parquet(
            "response_state_history.parquet"
        )

        print(
            "RESPONSE SNAPSHOT SAVED"
        )

    except Exception as e:

        print(e)

    time.sleep(300)
