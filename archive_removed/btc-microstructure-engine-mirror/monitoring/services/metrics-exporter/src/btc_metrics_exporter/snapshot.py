"""
Build a structured JSON snapshot of the current metric state.

Reads from the Prometheus CollectorRegistry directly — no PromQL parsing,
no Prometheus dependency at the consumer side. health-api and alert-engine
both consume this instead of speaking PromQL.

Schema (versioned via top-level `schema_version`):

  {
    "schema_version": 1,
    "ts": "<iso8601>",
    "scan_seq": <int>,
    "parquets": [{ file, age_seconds, size_bytes, rows, rows_per_minute,
                   schema_valid, read_errors }],
    "features": [{ dataset, feature, nan_ratio, inf_count, zmean, zstd }],
    "regime": { file, entropy_bits, distribution: [{ regime, p }] },
    "runtime": { name, last_iter_age_seconds, iterations },
    "self": { scans_total, scan_errors_total, last_scan_duration_seconds }
  }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from prometheus_client import CollectorRegistry

from .config import classify_parquet


SCHEMA_VERSION = 2


def _collect_samples(reg: CollectorRegistry) -> dict[str, list[dict[str, Any]]]:
    """Flat { metric_name: [{labels, value}, ...] }."""
    out: dict[str, list[dict[str, Any]]] = {}
    for metric in reg.collect():
        for s in metric.samples:
            out.setdefault(s.name, []).append({"labels": dict(s.labels), "value": s.value})
    return out


def build_snapshot(reg: CollectorRegistry) -> dict[str, Any]:
    s = _collect_samples(reg)

    def vec(name: str, label: str) -> dict[str, float]:
        return {row["labels"].get(label, "?"): row["value"] for row in s.get(name, [])}

    def scalar(name: str) -> float | None:
        rows = s.get(name, [])
        return float(rows[0]["value"]) if rows else None

    # ---- parquets ----
    p_age   = vec("btc_parquet_age_seconds",          "file")
    p_size  = vec("btc_parquet_size_bytes",           "file")
    p_rows  = vec("btc_parquet_rows_total",           "file")
    p_rate  = vec("btc_parquet_rows_delta_per_minute","file")
    p_valid = vec("btc_parquet_schema_valid",         "file")

    # per-file read errors aggregated across `kind` labels
    p_errors: dict[str, float] = {}
    for row in s.get("btc_parquet_read_errors_total", []):
        f = row["labels"].get("file", "?")
        p_errors[f] = p_errors.get(f, 0.0) + row["value"]

    files = sorted(set(p_age) | set(p_size) | set(p_rows) | set(p_valid))
    parquets = []
    for f in files:
        producer, kind = classify_parquet(f)
        parquets.append({
            "file": f,
            "producer":         producer,
            "kind":             kind,
            "age_seconds":      p_age.get(f),
            "size_bytes":       p_size.get(f),
            "rows":             p_rows.get(f),
            "rows_per_minute":  p_rate.get(f),
            "schema_valid":     bool(p_valid.get(f, 1)),
            "read_errors":      int(p_errors.get(f, 0)),
        })

    # ---- features ----
    feat_index: dict[tuple[str, str], dict[str, Any]] = {}
    for metric_name, key in [
        ("btc_feature_nan_ratio",   "nan_ratio"),
        ("btc_feature_inf_count",   "inf_count"),
        ("btc_feature_zscore_mean", "zmean"),
        ("btc_feature_zscore_std",  "zstd"),
    ]:
        for row in s.get(metric_name, []):
            lbl = row["labels"]
            k = (lbl.get("dataset", "?"), lbl.get("feature", "?"))
            feat_index.setdefault(k, {"dataset": k[0], "feature": k[1]})[key] = row["value"]
    features = sorted(feat_index.values(), key=lambda d: (d["dataset"], d["feature"]))

    # ---- regime ----
    regime_dist = []
    regime_file = None
    for row in s.get("btc_regime_distribution", []):
        lbl = row["labels"]
        regime_file = lbl.get("dataset", regime_file)
        regime_dist.append({"regime": lbl.get("regime", "?"), "p": row["value"]})
    regime_dist.sort(key=lambda d: -d["p"])
    regime_entropy = scalar("btc_regime_entropy")

    # ---- runtime ----
    runtime_age = scalar("btc_runtime_last_iter_age_seconds")
    runtime_name = "autonomous_runtime_v2"
    for row in s.get("btc_runtime_last_iter_age_seconds", []):
        runtime_name = row["labels"].get("runtime", runtime_name)
        break

    # ---- self ----
    scan_dur = {}
    for row in s.get("btc_exporter_scan_duration_seconds", []):
        scan_dur[row["labels"].get("collector", "?")] = row["value"]
    scans_total = sum(
        row["value"] for row in s.get("btc_exporter_scans_total", [])
    )
    scan_errors = sum(
        row["value"] for row in s.get("btc_exporter_scan_errors_total", [])
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "parquets": parquets,
        "features": features,
        "regime": {
            "file": regime_file,
            "entropy_bits": regime_entropy,
            "distribution": regime_dist,
        },
        "runtime": {
            "name": runtime_name,
            "last_iter_age_seconds": runtime_age,
        },
        "self": {
            "scans_total":          int(scans_total),
            "scan_errors_total":    int(scan_errors),
            "scan_duration_seconds": scan_dur,
        },
    }
