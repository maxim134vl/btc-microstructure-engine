import pandas as pd
import os

from datetime import datetime

MAX_ROWS_PER_FILE = 50000

def get_daily_file(

    base_path

):

    date_str = datetime.now().strftime(
        "%Y_%m_%d"
    )

    return os.path.join(

        base_path,

        f"{date_str}.parquet"
    )

def append_parquet(

    df,
    base_path

):

    os.makedirs(
        base_path,
        exist_ok=True
    )

    file_path = get_daily_file(
        base_path
    )

    if os.path.exists(file_path):

        existing = pd.read_parquet(
            file_path
        )

        combined = pd.concat(

            [existing, df],

            ignore_index=True

        )

    else:

        combined = df.copy()

    # =================================
    # CLEAN
    # =================================

    combined = combined.drop_duplicates()

    # =================================
    # LIMIT
    # =================================

    if len(combined) > MAX_ROWS_PER_FILE:

        combined = combined.iloc[
            -MAX_ROWS_PER_FILE:
        ]

    # =================================
    # ATOMIC WRITE
    # =================================

    temp_file = (
        file_path + ".tmp"
    )

    combined.to_parquet(

        temp_file,

        index=False

    )

    os.replace(
        temp_file,
        file_path
    )

    return file_path
