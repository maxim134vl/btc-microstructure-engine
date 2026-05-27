# Observability

What we measure, what we log, and how it lines up with the operator's
five-second view of system health.

## 1. The three pillars

| Pillar | Tool | Retention | Cardinality budget |
| --- | --- | --- | --- |
| Metrics | Prometheus | 15d / 10 GB | < 100k active series |
| Logs    | Loki        | 7d         | label set: `{job, container, level}` |
| Traces  | OpenTelemetry (v0.4) | — | — |

## 2. Metric catalog

All custom metrics emitted by `metrics-exporter` use the prefix `btc_`. Vendor
exporters (node, cAdvisor) use their upstream prefixes.

### 2.1 Pipeline Health

| Metric | Type | Labels | Source |
| --- | --- | --- | --- |
| `btc_runtime_loop_seconds`         | gauge   | `runtime` | runtime-probe (parses runtime log) |
| `btc_runtime_last_iter_age_seconds`| gauge   | `runtime` | runtime-probe (mtime of state file) |
| `btc_engine_iterations_total`      | counter | `runtime` | runtime-probe |
| `container_last_seen_timestamp`    | gauge   | `name`    | cAdvisor |
| `container_restart_count`          | counter | `name`    | cAdvisor |
| `container_memory_usage_bytes`     | gauge   | `name`    | cAdvisor |
| `container_cpu_usage_seconds_total`| counter | `name`    | cAdvisor |

### 2.2 Data Flow

| Metric | Type | Labels |
| --- | --- | --- |
| `btc_parquet_age_seconds`          | gauge   | `file`, `producer` |
| `btc_parquet_size_bytes`           | gauge   | `file` |
| `btc_parquet_rows_total`           | gauge   | `file` |
| `btc_parquet_rows_delta_per_minute`| gauge   | `file` |
| `btc_parquet_schema_valid`         | gauge   | `file` (0/1) |
| `btc_parquet_read_errors_total`    | counter | `file`, `kind` |

### 2.3 Live Feed

| Metric | Type | Labels |
| --- | --- | --- |
| `btc_feed_reconnects_total`        | counter | `feed`, `exchange` |
| `btc_feed_lag_seconds`             | gauge   | `feed`, `exchange` |
| `btc_feed_messages_total`          | counter | `feed`, `exchange`, `channel` |
| `btc_feed_disconnect_total`        | counter | `feed`, `exchange`, `reason` |

(Most "feed" metrics are derived from log line counters by Promtail-side regex; see `infra/promtail/promtail-config.yml`.)

### 2.4 System

Provided by `node-exporter`:
- `node_cpu_seconds_total`
- `node_memory_MemAvailable_bytes`, `node_memory_MemTotal_bytes`
- `node_filesystem_avail_bytes{mountpoint="/data"}`
- `node_load1`, `node_load5`, `node_load15`
- `node_filefd_allocated`

Process-level (cAdvisor): zombie detection via `container_tasks_state{state="zombie"}`.

### 2.5 Research / Behavioral

| Metric | Type | Labels |
| --- | --- | --- |
| `btc_feature_nan_ratio`            | gauge   | `feature`, `dataset` |
| `btc_feature_inf_count`            | gauge   | `feature`, `dataset` |
| `btc_feature_zscore_mean`          | gauge   | `feature`, `dataset` |
| `btc_feature_zscore_std`           | gauge   | `feature`, `dataset` |
| `btc_regime_distribution`          | gauge   | `regime` |
| `btc_regime_entropy`               | gauge   | `dataset` |

The exporter samples the last `METRICS_EXPORTER_FEATURE_SAMPLE_ROWS` rows of
each parquet (default 2000) rather than scanning whole files — bounded I/O cost.

### 2.6 Alert engine

| Metric | Type | Labels |
| --- | --- | --- |
| `btc_alerts_received_total`        | counter | `severity`, `source` |
| `btc_alerts_emitted_total`         | counter | `severity`, `domain` |
| `btc_alerts_deduped_total`         | counter | `severity` |
| `btc_alerts_active`                | gauge   | `severity` |
| `btc_alert_engine_cooldowns_active`| gauge   | — |

## 3. Cardinality discipline

- No metric labels contain timestamps, request IDs, full file paths, or anything unbounded.
- `file` labels normalized to basename only.
- `feature` labels limited to a known allowlist (config in `metrics-exporter/src/config.py`).
- `prometheus.yml` enforces `sample_limit: 10000` and `label_limit: 30` per scrape.

## 4. Log schema

All custom services log JSON with this shape:

```json
{
  "ts": "2026-05-20T14:33:21.124Z",
  "level": "INFO",
  "service": "health-api",
  "event": "ws.subscribe",
  "correlation_id": "8f3c…",
  "user": "admin",
  "msg": "client subscribed to alerts.live",
  "fields": {"topic": "alerts.live", "client_addr": "10.0.0.7"}
}
```

`level` is one of `DEBUG INFO WARN ERROR CRITICAL`. `event` is a stable
machine-readable key (snake.dot.notation). Free-form text goes in `msg`.

Promtail extracts `level`, `service`, `event` as Loki labels (low cardinality;
no `correlation_id` as a label).

## 5. Audit logs

Special `event` prefix `audit.*` is emitted by:
- `watchdog`: `audit.container.restart`, `audit.container.skip` (budget exceeded), `audit.circuit.tripped`
- `traefik`: every authenticated request via `accessLog` middleware
- `alert-engine`: `audit.silence.created`, `audit.silence.expired`

Loki retains audit logs for 30d (separate stream selector in `loki-config.yml`
v0.2 — MVP keeps everything together for simplicity).

## 6. SLOs (initial)

| Service | SLO | Window |
| --- | --- | --- |
| metrics-exporter `/metrics` reachable    | 99.9%  | 30d |
| health-api WS uptime                     | 99.5%  | 30d |
| Alert end-to-end latency (rule fire → UI)| < 30s  | p95, 30d |
| Parquet freshness (live feed)            | < 60s  | p99, 30d |

SLO burn alerts are *not* in MVP — added in v0.3 once we have baseline data.

## 7. Why not OpenTelemetry yet?

The runtime is a recursive batch loop, not a request/response service. Traces
add little ops value here. Once we add a query API or strategy backtester
(v0.4), OTel goes in as the canonical instrumentation layer; SDK shims will
emit metrics into the same Prometheus and logs into the same Loki.
