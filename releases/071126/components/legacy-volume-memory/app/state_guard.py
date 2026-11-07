from parquet_utils import (
    safe_read_parquet
)

# =====================================
# SHOULD PERSIST
# =====================================

def should_persist_state(

    file_path,
    state_dict

):

    old = safe_read_parquet(
        file_path
    )

    if len(old) == 0:

        return True

    latest = old.iloc[-1]

    for key, value in state_dict.items():

        if key not in latest:

            return True

        if str(latest[key]) != str(value):

            return True

    return False
