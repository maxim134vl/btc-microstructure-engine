"""
Prometheus metric declarations. Single source of truth for what the
exporter emits. Every metric carries `btc_` prefix; every label set is
documented in OBSERVABILITY.md §2.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge


@dataclass(frozen=True)
class Metrics:
    """Strongly-typed handle on the registry — passed to every collector."""

    registry: CollectorRegistry

    # ---- parquet / data-flow ----
    parquet_age_seconds:          Gauge
    parquet_size_bytes:           Gauge
    parquet_rows_total:           Gauge
    parquet_rows_delta_per_minute: Gauge
    parquet_schema_valid:         Gauge
    parquet_read_errors_total:    Counter

    # ---- runtime / pipeline ----
    runtime_last_iter_age_seconds: Gauge
    runtime_iterations_total:      Counter           # set-on-poll (best-effort)

    # ---- feature health ----
    feature_nan_ratio:    Gauge
    feature_inf_count:    Gauge
    feature_zscore_mean:  Gauge
    feature_zscore_std:   Gauge

    # ---- regime ----
    regime_distribution: Gauge
    regime_entropy:      Gauge

    # ---- self ----
    exporter_scan_duration_seconds: Gauge
    exporter_scans_total:           Counter
    exporter_scan_errors_total:     Counter


def build_metrics() -> Metrics:
    r = CollectorRegistry(auto_describe=True)

    return Metrics(
        registry=r,
        # ---- parquet ----
        parquet_age_seconds=Gauge(
            "btc_parquet_age_seconds",
            "Seconds since the parquet file was last modified",
            ["file"],
            registry=r,
        ),
        parquet_size_bytes=Gauge(
            "btc_parquet_size_bytes",
            "Size of the parquet file in bytes",
            ["file"],
            registry=r,
        ),
        parquet_rows_total=Gauge(
            "btc_parquet_rows_total",
            "Number of rows in the parquet file (best-effort metadata read)",
            ["file"],
            registry=r,
        ),
        parquet_rows_delta_per_minute=Gauge(
            "btc_parquet_rows_delta_per_minute",
            "Rows added since the previous scan, normalized per minute",
            ["file"],
            registry=r,
        ),
        parquet_schema_valid=Gauge(
            "btc_parquet_schema_valid",
            "1 if the parquet schema matches the expected column set; 0 otherwise",
            ["file"],
            registry=r,
        ),
        parquet_read_errors_total=Counter(
            "btc_parquet_read_errors_total",
            "Total parquet read failures by error kind",
            ["file", "kind"],
            registry=r,
        ),
        # ---- runtime ----
        runtime_last_iter_age_seconds=Gauge(
            "btc_runtime_last_iter_age_seconds",
            "Estimated seconds since the runtime last produced fresh data. "
            "Derived from the minimum parquet mtime across runtime-output files.",
            ["runtime"],
            registry=r,
        ),
        runtime_iterations_total=Counter(
            "btc_runtime_iterations_total",
            "Total observed runtime iterations (best-effort from row growth)",
            ["runtime"],
            registry=r,
        ),
        # ---- feature health ----
        feature_nan_ratio=Gauge(
            "btc_feature_nan_ratio",
            "Ratio of NaN values in the sampled tail of the feature column",
            ["dataset", "feature"],
            registry=r,
        ),
        feature_inf_count=Gauge(
            "btc_feature_inf_count",
            "Count of inf/-inf values in the sampled tail of the feature column",
            ["dataset", "feature"],
            registry=r,
        ),
        feature_zscore_mean=Gauge(
            "btc_feature_zscore_mean",
            "Mean of z-scored values in sampled tail (drift detector)",
            ["dataset", "feature"],
            registry=r,
        ),
        feature_zscore_std=Gauge(
            "btc_feature_zscore_std",
            "Std of z-scored values in sampled tail (normalization-collapse detector)",
            ["dataset", "feature"],
            registry=r,
        ),
        # ---- regime ----
        regime_distribution=Gauge(
            "btc_regime_distribution",
            "Fraction of sampled rows in each regime",
            ["dataset", "regime"],
            registry=r,
        ),
        regime_entropy=Gauge(
            "btc_regime_entropy",
            "Shannon entropy of the regime distribution (collapse detector)",
            ["dataset"],
            registry=r,
        ),
        # ---- self ----
        exporter_scan_duration_seconds=Gauge(
            "btc_exporter_scan_duration_seconds",
            "Wall-clock duration of the last full scan, per collector",
            ["collector"],
            registry=r,
        ),
        exporter_scans_total=Counter(
            "btc_exporter_scans_total",
            "Total scan iterations per collector",
            ["collector"],
            registry=r,
        ),
        exporter_scan_errors_total=Counter(
            "btc_exporter_scan_errors_total",
            "Total scan failures per collector",
            ["collector"],
            registry=r,
        ),
    )
