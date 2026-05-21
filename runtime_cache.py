import pandas as pd
import time

CACHE = {}

CACHE_TTL = 5

def load_parquet_cached(file_path):

    global CACHE

    now = time.time()

    if file_path in CACHE:

        cached = CACHE[file_path]

        age = now - cached["timestamp"]

        if age < CACHE_TTL:

            return cached["data"]

    df = pd.read_parquet(
        file_path
    )

    CACHE[file_path] = {

        "timestamp":
            now,

        "data":
            df

    }

    return df

def clear_cache():

    global CACHE

    CACHE = {}
