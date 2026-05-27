# metrics-exporter

Domain-aware Prometheus exporter for the BTC microstructure data plane.

## What it does

Each tick (default 10s) it runs four collectors over `/data`:

| Collector | Emits |
| --- | --- |
| `parquet_scanner`     | freshness, size, row count, growth rate, schema validity per parquet file |
| `feature_health`      | NaN ratio, inf count, z-score mean/std on the tail of allowlisted features |
| `regime_distribution` | per-regime fraction + Shannon entropy from the regime column |
| `runtime_probe`       | derived "last iteration age" — min mtime across runtime-output files |

All metrics are namespaced `btc_*` and documented in [OBSERVABILITY.md §2](../../docs/OBSERVABILITY.md).

## Why this design

- **Read-only**: never opens parquet files for writing; safe to deploy alongside live producers.
- **Bounded cost**: feature health samples the tail only (`FEATURE_SAMPLE_ROWS` rows), with explicit column projection. Whole-file scans are not performed.
- **Cardinality discipline**: every label set is fixed in source (`config.py`), no path-as-label or timestamp-as-label.
- **Fail-soft**: one collector's failure increments an error counter but does not stop the others.

## Run

```bash
make build               # from monitoring/
make up                  # then visit http://localhost:9101/metrics
```

## Configure

All knobs via env (see [.env.example](../../.env.example)):

- `METRICS_EXPORTER_SCAN_INTERVAL_SECONDS` (default 10)
- `METRICS_EXPORTER_FEATURE_SAMPLE_ROWS` (default 2000)
- `METRICS_EXPORTER_REGIME_SAMPLE_ROWS` (default 5000)
- `DATA_DIR` (default `/data`)
- `LOG_LEVEL` (default `INFO`)

## Test

```bash
cd services/metrics-exporter
python -m pytest -q
```

## Add a new collector

1. Implement a `Collector` subclass in `src/btc_metrics_exporter/collectors/yours.py`
2. Export it from `collectors/__init__.py`
3. Append to the list in `app.py:main_async`
4. Add its metrics to `registry.py:build_metrics()`
