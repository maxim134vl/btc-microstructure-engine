import pandas as pd

from state_manager_v1 import STATE

# =====================================
# RUNTIME COGNITION ENGINE
# =====================================

def run():

    print()
    print(
        "RUNTIME COGNITION ENGINE"
    )
    print()

    cognition = pd.read_parquet(

        "runtime_cognition_memory.parquet"

    )

    if "alignment_score" not in cognition.columns:

        synthesis = pd.read_parquet(
            "multi_timeframe_synthesis.parquet"
        )

        cognition = cognition.merge(
            synthesis[
                [
                    "timestamp",
                    "alignment_score"
                ]
            ],
            on="timestamp",
            how="left"
        )

        cognition["alignment_score"] = (
            cognition["alignment_score"]
            .fillna(0.25)
        )

    if len(cognition) == 0:

        print(
            "NO COGNITION STATES"
        )

        print()

        return

    latest_state = cognition.iloc[-1]

    STATE["runtime_cognition"] = {

        "timestamp":
            latest_state["timestamp"],

        "synthesis_state":
            latest_state["synthesis_state"],

        "trigger_event":
            latest_state["trigger_event"],

        "persistence":
            latest_state["persistence"],

        "persistence_score":
            latest_state["persistence_score"],

        "structural_rank":
            latest_state["structural_rank"],

        "alignment_score":
            latest_state["alignment_score"],

        "location_bias":
            latest_state["location_bias"]

    }

    print(
        STATE["runtime_cognition"]
    )

    print()

# =====================================
# START
# =====================================

if __name__ == "__main__":

    run()
