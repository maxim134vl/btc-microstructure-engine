"""
Rule evaluator. Each rule is a pure function:

    rule(snapshot: dict) -> list[Alert]

Given a metrics-exporter snapshot, returns a list of zero or more alerts.
The orchestrator in `app.py` is responsible for fingerprinting, cooldown,
and publishing the resulting alerts.

Replaces the prior Prometheus rules; we no longer depend on PromQL or
Alertmanager. The advantage: one set of source-controlled Python rules,
unit-testable, no separate alert-routing config.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# Thresholds — single source of truth. Tweak here, not at the call sites.
PARQUET_STALE_WARN = 60.0
PARQUET_STALE_CRIT = 120.0
LIVE_FEED_STALE_WARN = 30.0
LIVE_FEED_STALE_CRIT = 60.0
RUNTIME_STALL_WARN = 60.0
RUNTIME_STALL_CRIT = 120.0
RUNTIME_STALL_HARD = 600.0
NAN_RATIO_WARN = 0.01
NAN_RATIO_CRIT = 0.10
REGIME_ENTROPY_COLLAPSE = 0.1


@dataclass
class Alert:
    """A firing alert. fingerprint is computed downstream."""

    alertname: str
    severity: str          # critical | warning | info
    domain: str            # pipeline | dataflow | feed | system | research
    summary: str
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -----------------------------------------------------------------------------
# Rules
# -----------------------------------------------------------------------------

def rule_runtime_stalled(snapshot: dict) -> list[Alert]:
    rt = snapshot.get("runtime") or {}
    age = rt.get("last_iter_age_seconds")
    name = rt.get("name", "runtime")
    if age is None:
        return []
    if age >= RUNTIME_STALL_HARD:
        return [Alert(
            alertname="RuntimeCriticallyStalled",
            severity="critical",
            domain="pipeline",
            summary=f"runtime stalled > 10 min ({int(age)}s)",
            labels={"runtime": name},
            annotations={"description":
                         "Beyond watchdog's auto-restart budget. Investigate.",
                         "runbook": "docs/RUNBOOK.md#runtime-stalled"},
        )]
    if age >= RUNTIME_STALL_CRIT:
        return [Alert(
            alertname="RuntimeStalled",
            severity="critical",
            domain="pipeline",
            summary=f"runtime stalled ({int(age)}s since last iter)",
            labels={"runtime": name},
            annotations={"runbook": "docs/RUNBOOK.md#runtime-stalled"},
        )]
    if age >= RUNTIME_STALL_WARN:
        return [Alert(
            alertname="RuntimeLagging",
            severity="warning",
            domain="pipeline",
            summary=f"runtime lagging ({int(age)}s since last iter)",
            labels={"runtime": name},
            annotations={"runbook": "docs/RUNBOOK.md#runtime-stalled"},
        )]
    return []


def _tracked(p: dict) -> bool:
    """Alert only on known producers — pipeline memory caches and
    unknown files are informational only."""
    return p.get("kind") in ("live", "rest")


def rule_parquet_stale(snapshot: dict) -> list[Alert]:
    out: list[Alert] = []
    for p in snapshot.get("parquets") or []:
        if not _tracked(p):
            continue
        age = p.get("age_seconds")
        if age is None:
            continue
        file = p.get("file", "?")
        producer = p.get("producer") or "?"
        is_live = p.get("kind") == "live"
        warn = LIVE_FEED_STALE_WARN if is_live else PARQUET_STALE_WARN
        crit = LIVE_FEED_STALE_CRIT if is_live else PARQUET_STALE_CRIT
        domain = "feed" if is_live else "dataflow"
        if age >= crit:
            out.append(Alert(
                alertname="ParquetStale",
                severity="critical",
                domain=domain,
                summary=f"{producer}: {file} stale ({int(age)}s)",
                labels={"file": file, "producer": producer},
                annotations={"runbook": "docs/RUNBOOK.md#parquet-stale"},
            ))
        elif age >= warn:
            out.append(Alert(
                alertname="ParquetStaleWarn",
                severity="warning",
                domain=domain,
                summary=f"{producer}: {file} aging ({int(age)}s)",
                labels={"file": file, "producer": producer},
                annotations={"runbook": "docs/RUNBOOK.md#parquet-stale"},
            ))
    return out


def rule_parquet_missing(snapshot: dict) -> list[Alert]:
    """Producer is listed in the producer map but the file doesn't exist
    on disk (e.g. liquidations collector that never writes its parquet)."""
    from btc_alert_engine.evaluator import _expected_producers  # late import
    files_seen = {(p.get("file") or "") for p in (snapshot.get("parquets") or [])}
    out: list[Alert] = []
    for fname, info in _expected_producers().items():
        if fname not in files_seen:
            out.append(Alert(
                alertname="ProducerMissingParquet",
                severity="critical",
                domain="dataflow" if info["kind"] != "live" else "feed",
                summary=f"{info['producer']} has not produced {fname}",
                labels={"file": fname, "producer": info["producer"]},
                annotations={"description":
                             "Container is up but never wrote its parquet — "
                             "likely silent failure inside the collector."},
            ))
    return out


def _expected_producers() -> dict[str, dict[str, str]]:
    """Mirror of metrics-exporter's PARQUET_PRODUCERS. Kept in alert-engine
    to avoid cross-service imports; sync manually if you add producers."""
    return {
        "live_market_feed.parquet":    {"producer": "binance-feed",   "kind": "live"},
        "intraday_flow.parquet":       {"producer": "intraday-flow",  "kind": "rest"},
        "multi_exchange_flow.parquet": {"producer": "multi-exchange", "kind": "live"},
        "orderbook.parquet":           {"producer": "orderbook",      "kind": "live"},
        "oi_history.parquet":          {"producer": "oi",             "kind": "rest"},
        "liquidations.parquet":        {"producer": "liquidations",   "kind": "live"},
    }


def rule_parquet_schema_invalid(snapshot: dict) -> list[Alert]:
    out: list[Alert] = []
    for p in snapshot.get("parquets") or []:
        if not _tracked(p):
            continue
        if p.get("schema_valid") is False:
            file = p.get("file", "?")
            out.append(Alert(
                alertname="ParquetSchemaInvalid",
                severity="critical",
                domain="dataflow",
                summary=f"{file} has invalid schema",
                labels={"file": file},
                annotations={"runbook": "docs/RUNBOOK.md#parquet-schema-invalid"},
            ))
    return out


def rule_parquet_empty(snapshot: dict) -> list[Alert]:
    out: list[Alert] = []
    for p in snapshot.get("parquets") or []:
        if not _tracked(p):
            continue
        rows = p.get("rows")
        if rows is not None and rows == 0:
            file = p.get("file", "?")
            out.append(Alert(
                alertname="ParquetEmpty",
                severity="warning",
                domain="dataflow",
                summary=f"{file} is empty (0 rows)",
                labels={"file": file},
                annotations={"runbook": "docs/RUNBOOK.md#parquet-stale"},
            ))
    return out


def rule_feature_nan(snapshot: dict) -> list[Alert]:
    out: list[Alert] = []
    for f in snapshot.get("features") or []:
        ratio = f.get("nan_ratio")
        if ratio is None:
            continue
        dataset, feature = f.get("dataset", "?"), f.get("feature", "?")
        if ratio >= NAN_RATIO_CRIT:
            out.append(Alert(
                alertname="FeatureNaNCritical",
                severity="critical",
                domain="research",
                summary=f"{feature} NaN ratio {ratio*100:.1f}% in {dataset}",
                labels={"dataset": dataset, "feature": feature},
                annotations={"runbook": "docs/RUNBOOK.md#feature-nan-explosion"},
            ))
        elif ratio >= NAN_RATIO_WARN:
            out.append(Alert(
                alertname="FeatureNaNExplosion",
                severity="warning",
                domain="research",
                summary=f"{feature} NaN ratio {ratio*100:.1f}% in {dataset}",
                labels={"dataset": dataset, "feature": feature},
                annotations={"runbook": "docs/RUNBOOK.md#feature-nan-explosion"},
            ))
    return out


def rule_feature_inf(snapshot: dict) -> list[Alert]:
    out: list[Alert] = []
    for f in snapshot.get("features") or []:
        n = f.get("inf_count") or 0
        if n > 0:
            dataset, feature = f.get("dataset", "?"), f.get("feature", "?")
            out.append(Alert(
                alertname="FeatureInfDetected",
                severity="warning",
                domain="research",
                summary=f"{feature} has {int(n)} infinite value(s)",
                labels={"dataset": dataset, "feature": feature},
            ))
    return out


def rule_regime_collapse(snapshot: dict) -> list[Alert]:
    r = snapshot.get("regime") or {}
    entropy = r.get("entropy_bits")
    file = r.get("file", "?")
    if entropy is None:
        return []
    if entropy < REGIME_ENTROPY_COLLAPSE:
        return [Alert(
            alertname="RegimeCollapse",
            severity="warning",
            domain="research",
            summary=f"regime entropy collapsed ({entropy:.2f} bit)",
            labels={"file": file},
        )]
    return []


def rule_exporter_errors(snapshot: dict) -> list[Alert]:
    s = snapshot.get("self") or {}
    errs = s.get("scan_errors_total") or 0
    scans = s.get("scans_total") or 0
    # rate inferred from totals — orchestrator already gates with cooldown so
    # one-shot errors won't spam
    if scans > 50 and errs > 0 and (errs / max(scans, 1)) > 0.05:
        return [Alert(
            alertname="ExporterScanErrors",
            severity="warning",
            domain="pipeline",
            summary=f"metrics-exporter error rate {errs}/{scans}",
            labels={},
        )]
    return []


# -----------------------------------------------------------------------------
# Registry
# -----------------------------------------------------------------------------
ALL_RULES = [
    rule_runtime_stalled,
    rule_parquet_stale,
    rule_parquet_missing,
    rule_parquet_schema_invalid,
    rule_parquet_empty,
    rule_feature_nan,
    rule_feature_inf,
    rule_regime_collapse,
    rule_exporter_errors,
]


def evaluate_all(snapshot: dict) -> list[Alert]:
    """Run every registered rule, return the union."""
    fired: list[Alert] = []
    for rule in ALL_RULES:
        try:
            fired.extend(rule(snapshot))
        except Exception:
            # one rule's bug must not stop the rest; orchestrator logs
            continue
    return fired
