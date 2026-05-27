"""Pluggable collectors. Each is a `Collector` subclass."""

from .base import Collector
from .feature_health import FeatureHealthCollector
from .parquet_scanner import ParquetScannerCollector
from .regime_distribution import RegimeDistributionCollector
from .runtime_probe import RuntimeProbeCollector

__all__ = [
    "Collector",
    "FeatureHealthCollector",
    "ParquetScannerCollector",
    "RegimeDistributionCollector",
    "RuntimeProbeCollector",
]
