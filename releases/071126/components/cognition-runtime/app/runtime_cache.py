import time

import pandas as pd

from storage.path_registry import resolve_read

CACHE = {}

CACHE_TTL = 5


def load_parquet_cached(file_path):

    global CACHE

    resolved = resolve_read(file_path)
    now = time.time()

    if resolved in CACHE:

        cached = CACHE[resolved]

        age = now - cached["timestamp"]

        if age < CACHE_TTL:

            return cached["data"]

    df = pd.read_parquet(
        resolved
    )

    CACHE[resolved] = {

        "timestamp":
            now,

        "data":
            df

    }

    return df

def clear_cache():

    global CACHE

    CACHE = {}
