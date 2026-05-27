import time
import pandas as pd
from datetime import datetime

print()
print(
    "OBSERVATION LOGGER STARTED"
)
print()

while True:

    try:

        sequence = pd.read_parquet(
            "behavioral_sequence_memory.parquet"
        )

        response = pd.read_parquet(
            "volume_response_state.parquet"
        )

        latest_sequence = (
            sequence.iloc[-1]
        )

        latest_response = (
            response.iloc[-1]
        )

        row = pd.DataFrame([{

            "timestamp":
                datetime.now(),

            "sequence":
                latest_sequence[
                    "sequence"
                ],

            "event_state":
                latest_sequence[
                    "event_state"
                ],

            "localized_behavior":
                latest_sequence[
                    "localized_behavior"
                ],

            "delta":
                latest_sequence[
                    "delta"
                ],

            "delta_efficiency":
                latest_sequence[
                    "delta_efficiency"
                ],

            "volume_class":
                latest_response[
                    "volume_class"
                ],

            "participation_state":
                latest_response[
                    "participation_state"
                ],

            "unfinished_auction":
                latest_response[
                    "unfinished_auction"
                ],

            "continuation_quality":
                latest_response[
                    "continuation_quality"
                ],

            "effort_result_state":
                latest_response[
                    "effort_result_state"
                ]

        }])

        try:

            history = pd.read_parquet(
                "backtest_observation_log.parquet"
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
            "backtest_observation_log.parquet"
        )

        print(
            "OBSERVATION SAVED:",
            datetime.now()
        )

    except Exception as e:

        print(
            "LOGGER ERROR:"
        )

        print(e)

    time.sleep(300)
