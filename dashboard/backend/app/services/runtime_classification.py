"""Re-export canonical runtime classification for dashboard services."""

from runtime_classification import (  # noqa: F401
    ARCHIVED_CLASSES,
    COLLECTOR_DISPLAY_CLASS,
    PARQUET_DISPLAY_CLASS,
    ComponentClass,
    classify_collector,
    classify_engine,
    classify_parquet,
)
