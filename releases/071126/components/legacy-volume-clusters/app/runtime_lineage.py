import json
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Union

import pandas as pd

LINEAGE_COLUMNS = [
    "lineage_engine",
    "lineage_source_parquet",
    "lineage_event_timestamp",
    "lineage_propagation_timestamp",
    "lineage_dependency_chain",
]


def utc_now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def build_dependency_chain(steps: Iterable[str]) -> str:
    return "->".join(steps)


def apply_lineage_metadata(
    df: pd.DataFrame,
    engine_name: str,
    source_parquet: str,
    dependency_chain: Union[str, List[str]],
    event_timestamp_col: str = "timestamp",
) -> pd.DataFrame:
    """Attach lineage metadata columns without changing domain fields."""

    if len(df) == 0:
        return df.copy()

    output = df.copy()
    propagation_ts = utc_now()

    if isinstance(dependency_chain, list):
        dependency_chain = build_dependency_chain(dependency_chain)

    output["lineage_engine"] = engine_name
    output["lineage_source_parquet"] = source_parquet
    output["lineage_propagation_timestamp"] = propagation_ts
    output["lineage_dependency_chain"] = dependency_chain

    if event_timestamp_col in output.columns:
        output["lineage_event_timestamp"] = pd.to_datetime(
            output[event_timestamp_col]
        )
    else:
        output["lineage_event_timestamp"] = propagation_ts

    return output


def parquet_mtime(path: str) -> Optional[float]:
    import os

    if not os.path.exists(path):
        return None
    return os.path.getmtime(path)


def lineage_record_from_row(row: pd.Series) -> dict:
    return {
        "lineage_engine": row.get("lineage_engine"),
        "lineage_source_parquet": row.get("lineage_source_parquet"),
        "lineage_event_timestamp": row.get("lineage_event_timestamp"),
        "lineage_propagation_timestamp": row.get("lineage_propagation_timestamp"),
        "lineage_dependency_chain": row.get("lineage_dependency_chain"),
    }


def lineage_record_to_json(record: dict) -> str:
    return json.dumps(record, default=str)
