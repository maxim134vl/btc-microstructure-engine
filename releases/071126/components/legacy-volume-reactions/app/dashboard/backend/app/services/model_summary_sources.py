"""Model Summary source resolver.

Priority:
1. Fresh benchmark/conformance reports (primary diagnostics)
2. exports/model_governance_dashboard.json (governance-only fields)
3. data/ml/model_monitoring_memory.parquet (legacy fallback only)

Does not retrain models, generate benchmarks, or mutate pipeline/execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import (
    MODEL_BENCHMARK_MAX_AGE_HOURS,
    MODEL_GOVERNANCE_MAX_AGE_HOURS,
    MODEL_VALIDATION_MAX_AGE_HOURS,
    REPO_ROOT,
)
from app.services.model_summary_freshness import (
    STATUS_CURRENT,
    STATUS_MISSING,
    STATUS_STALE_VALIDATION,
    STATUS_UNKNOWN,
    build_freshness,
    missing_label,
    parse_timestamp,
    resolve_existing_path,
)

STATUS_GOVERNANCE_MISSING = "GOVERNANCE_MISSING"

DIAGNOSTICS_CANDIDATES: tuple[str, ...] = (
    "benchmark/conformance/reports/latest_conformance.json",
    "benchmark/reports/latest_integrated.json",
    "benchmark/reports/latest_stage2.json",
    "benchmark/reports/latest.json",
)

GOVERNANCE_CANDIDATES: tuple[str, ...] = (
    "exports/model_governance_dashboard.json",
)

LEGACY_MONITORING_CANDIDATES: tuple[str, ...] = (
    "data/ml/model_monitoring_memory.parquet",
    "data/diagnostics/model_monitoring_memory.parquet",
)

# Case-insensitive metric aliases searched recursively in report payloads.
METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "psi": ("psi", "psi_label"),
    "macro_f1": ("macro_f1", "shadow_macro_f1"),
    "balanced_accuracy": ("balanced_accuracy",),
    "loss_recall": ("loss_recall",),
    "win_rate": ("win_rate", "win_pct"),
    "neutral_rate": ("neutral_rate", "neutral_pct"),
    "loss_rate": ("loss_rate", "loss_pct"),
    "drift_severity_score": ("drift_severity_score",),
    "cognition_health": ("cognition_health",),
    "drift_severity": ("severity",),
}

# Keys that count as *toxic monitoring* metrics in benchmark reports.
# cognition_health / failed_cognition alone do NOT qualify as toxic metrics.
TOXIC_PRESENCE_KEYS: frozenset[str] = frozenset(
    {
        "toxic",
        "toxic_box",
        "toxic_events",
        "toxic_rate",
        "toxic_rate_7d",
        "toxic_rate_30d",
        "toxic_periods",
        "toxic_7d",
        "toxic_30d",
        "toxic_trend",
        "toxic_count",
        "n_toxic",
    }
)

TOXIC_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "events": ("toxic_events", "toxic_count", "n_toxic"),
    "events_last_7d": ("events_last_7d", "toxic_7d", "toxic_events_7d"),
    "toxic_rate_7d": ("toxic_rate_7d", "toxic_rate", "toxic_7d_rate"),
    "toxic_rate_30d": ("toxic_rate_30d", "toxic_30d", "toxic_30d_rate"),
    "trend": ("toxic_trend",),
}

STATUS_LEGACY_ONLY = "LEGACY_ONLY"
STATUS_MISSING_DATA = "MISSING_DATA"
TOXIC_LEGACY_REASON = (
    "current toxic metrics are not present in benchmark_primary_v1; "
    "showing historical toxic baseline"
)


def _repo_join(relative: str) -> Path:
    return Path(REPO_ROOT) / relative


def _iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.isoformat().replace("+00:00", "Z")


def _rel_display(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).resolve().relative_to(Path(REPO_ROOT).resolve()))
    except Exception:
        return path


def load_json_file(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def find_metric_ci(
    payload: Any,
    aliases: tuple[str, ...],
    *,
    _path: str = "",
) -> tuple[Any, str] | None:
    """Depth-first case-insensitive key search. Returns (value, dotted_path)."""
    wanted = {a.lower() for a in aliases}
    if isinstance(payload, dict):
        # Prefer direct key hits before descending.
        for key, value in payload.items():
            if str(key).lower() in wanted:
                if value is None or isinstance(value, (dict, list)):
                    continue
                dotted = f"{_path}.{key}" if _path else str(key)
                return value, dotted
        for key, value in payload.items():
            nested = find_metric_ci(value, aliases, _path=f"{_path}.{key}" if _path else str(key))
            if nested is not None:
                return nested
    elif isinstance(payload, list):
        for idx, item in enumerate(payload[:50]):
            nested = find_metric_ci(item, aliases, _path=f"{_path}[{idx}]")
            if nested is not None:
                return nested
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_path_candidates(*relatives: str) -> str | None:
    return resolve_existing_path(*(_repo_join(rel) for rel in relatives))


def load_diagnostics_reports() -> list[dict[str, Any]]:
    """Load existing diagnostics reports in priority order (does not generate files)."""
    reports: list[dict[str, Any]] = []
    for relative in DIAGNOSTICS_CANDIDATES:
        path = resolve_path_candidates(relative)
        if not path:
            continue
        payload = load_json_file(path)
        if payload is None:
            continue
        generated_at = payload.get("generated_at") or payload.get("timestamp")
        reports.append(
            {
                "relative": relative,
                "source_path": path,
                "source_path_display": _rel_display(path),
                "generated_at": generated_at,
                "payload": payload,
            }
        )
    return reports


def pick_primary_diagnostics(
    reports: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Select primary diagnostics report + freshness."""
    now_utc = now or datetime.now(timezone.utc)
    reports = reports if reports is not None else load_diagnostics_reports()
    if not reports:
        freshness = build_freshness(
            source_path=None,
            source_timestamp=None,
            max_age_hours=MODEL_BENCHMARK_MAX_AGE_HOURS,
            stale_status=STATUS_STALE_VALIDATION,
            now=now_utc,
        )
        return {
            "source_path": None,
            "source_path_display": None,
            "generated_at": None,
            "freshness_status": STATUS_MISSING,
            "age_hours": None,
            "age_days": None,
            "is_stale": True,
            "freshness": freshness,
            "payload": None,
            "reports": [],
            "used_as_primary": False,
        }

    primary = reports[0]
    freshness = build_freshness(
        source_path=primary["source_path"],
        source_timestamp=primary.get("generated_at"),
        max_age_hours=MODEL_BENCHMARK_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
        now=now_utc,
    )
    return {
        "source_path": primary["source_path"],
        "source_path_display": primary.get("source_path_display"),
        "generated_at": primary.get("generated_at") or freshness.get("source_timestamp"),
        "freshness_status": freshness.get("freshness_status"),
        "age_hours": freshness.get("age_hours"),
        "age_days": freshness.get("age_days"),
        "is_stale": bool(freshness.get("is_stale")),
        "freshness": freshness,
        "payload": primary.get("payload"),
        "reports": reports,
        "used_as_primary": True,
    }


def resolve_governance_source(*, now: datetime | None = None) -> dict[str, Any]:
    now_utc = now or datetime.now(timezone.utc)
    path = resolve_path_candidates(*GOVERNANCE_CANDIDATES)
    payload = load_json_file(path)
    if path is None or payload is None:
        return {
            "source_path": None,
            "source_path_display": None,
            "status": STATUS_GOVERNANCE_MISSING,
            "missing_reason": "governance artifact missing",
            "payload": None,
            "freshness": build_freshness(
                source_path=None,
                source_timestamp=None,
                max_age_hours=MODEL_GOVERNANCE_MAX_AGE_HOURS,
                missing_status=STATUS_MISSING,
                now=now_utc,
            ),
        }

    generated_at = (
        payload.get("last_validation_at")
        or payload.get("generated_at")
        or payload.get("timestamp")
    )
    freshness = build_freshness(
        source_path=path,
        source_timestamp=generated_at,
        max_age_hours=MODEL_GOVERNANCE_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
        now=now_utc,
    )
    return {
        "source_path": path,
        "source_path_display": _rel_display(path),
        "status": STATUS_CURRENT if not freshness.get("is_stale") else freshness.get("freshness_status"),
        "missing_reason": None,
        "payload": payload,
        "generated_at": generated_at,
        "freshness": freshness,
    }


def resolve_legacy_monitoring(
    *,
    now: datetime | None = None,
    used_as_primary: bool = False,
) -> dict[str, Any]:
    now_utc = now or datetime.now(timezone.utc)
    path = resolve_path_candidates(*LEGACY_MONITORING_CANDIDATES)
    if path is None:
        return {
            "source_path": None,
            "source_path_display": None,
            "timestamp": None,
            "age_days": None,
            "age_hours": None,
            "used_as_primary": False,
            "is_stale": True,
            "freshness_status": STATUS_MISSING,
            "row": None,
        }

    timestamp = None
    row: dict[str, Any] | None = None
    try:
        frame = pd.read_parquet(path)
        if len(frame):
            latest = frame.iloc[-1]
            row = latest.to_dict()
            timestamp = latest.get("timestamp")
    except Exception:
        row = None

    freshness = build_freshness(
        source_path=path,
        source_timestamp=timestamp,
        max_age_hours=MODEL_VALIDATION_MAX_AGE_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
        now=now_utc,
    )
    return {
        "source_path": path,
        "source_path_display": _rel_display(path),
        "timestamp": timestamp if timestamp is not None else freshness.get("source_mtime"),
        "age_days": freshness.get("age_days"),
        "age_hours": freshness.get("age_hours"),
        "used_as_primary": bool(used_as_primary),
        "is_stale": bool(freshness.get("is_stale")),
        "freshness_status": freshness.get("freshness_status"),
        "freshness": freshness,
        "row": row,
    }


def extract_metric_from_reports(
    reports: list[dict[str, Any]],
    metric_name: str,
) -> dict[str, Any] | None:
    aliases = METRIC_ALIASES.get(metric_name, (metric_name,))
    for report in reports:
        payload = report.get("payload")
        hit = find_metric_ci(payload, aliases)
        if hit is None:
            continue
        value, dotted = hit
        numeric = _to_float(value)
        return {
            "value": numeric if numeric is not None else value,
            "metric_source": report.get("source_path_display") or report.get("source_path"),
            "metric_path": dotted,
            "generated_at": report.get("generated_at"),
            "metric_is_legacy": False,
        }
    return None


def _key_is_toxic_presence(key: str) -> bool:
    lower = str(key).lower()
    if lower in {"cognition_health", "failed_cognition"}:
        return False
    if lower in TOXIC_PRESENCE_KEYS:
        return True
    return lower.startswith("toxic_")


def payload_has_toxic_metrics(payload: Any) -> bool:
    """True when report payload contains toxic monitoring fields (not cognition_health alone)."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _key_is_toxic_presence(str(key)):
                if isinstance(value, dict) and value:
                    return True
                if isinstance(value, list) and value:
                    return True
                if value is not None and not isinstance(value, (dict, list)):
                    return True
            if payload_has_toxic_metrics(value):
                return True
    elif isinstance(payload, list):
        for item in payload[:50]:
            if payload_has_toxic_metrics(item):
                return True
    return False


def extract_toxic_metrics_from_payload(payload: Any) -> dict[str, Any]:
    """Pull known toxic metric aliases from a single report payload."""
    out: dict[str, Any] = {}
    for name, aliases in TOXIC_METRIC_ALIASES.items():
        hit = find_metric_ci(payload, aliases)
        if hit is None:
            continue
        value, dotted = hit
        numeric = _to_float(value)
        out[name] = {
            "value": numeric if numeric is not None else value,
            "metric_path": dotted,
        }
    return out


def extract_toxic_metrics_from_reports(
    reports: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """First report (priority order) that contains toxic monitoring metrics."""
    for report in reports:
        payload = report.get("payload")
        if not payload_has_toxic_metrics(payload):
            continue
        metrics = extract_toxic_metrics_from_payload(payload)
        return {
            "source_path": report.get("source_path_display") or report.get("source_path"),
            "generated_at": report.get("generated_at"),
            "metrics": metrics,
            "metrics_available": True,
        }
    return None


def resolve_toxic_monitoring_sources(
    *,
    now: datetime | None = None,
    historical_source_path: str | None = None,
    historical_timestamp: Any = None,
    historical_age_days: float | None = None,
    historical_metrics_available: bool = False,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve current vs historical toxic sources without promoting June parquet.

    Fresh July diagnostics without toxic fields → LEGACY_ONLY + MISSING_DATA current.
    """
    now_utc = now or datetime.now(timezone.utc)
    diagnostics = diagnostics if diagnostics is not None else pick_primary_diagnostics(now=now_utc)
    reports = diagnostics.get("reports") or []
    if not reports:
        reports = load_diagnostics_reports()

    extracted = extract_toxic_metrics_from_reports(reports)
    diagnostics_status = diagnostics.get("freshness_status") or STATUS_MISSING
    if diagnostics.get("payload") is not None and not diagnostics.get("is_stale"):
        diagnostics_status = STATUS_CURRENT

    hist_path = _rel_display(historical_source_path) or historical_source_path
    hist_ts = historical_timestamp
    if hist_ts is not None:
        parsed = parse_timestamp(hist_ts)
        hist_ts = _iso(parsed) if parsed is not None else hist_ts

    historical: dict[str, Any] = {
        "status": "STALE" if historical_metrics_available else STATUS_MISSING_DATA,
        "source_path": hist_path,
        "timestamp": hist_ts,
        "age_days": historical_age_days,
        "metrics_available": bool(historical_metrics_available),
    }

    if extracted is not None and diagnostics_status == STATUS_CURRENT:
        return {
            "current": {
                "status": STATUS_CURRENT,
                "source_path": extracted.get("source_path"),
                "generated_at": extracted.get("generated_at"),
                "metrics_available": True,
                "metrics": extracted.get("metrics") or {},
            },
            "historical": historical,
            "display_status": STATUS_CURRENT,
            "display_reason": "current toxic metrics loaded from benchmark_primary_v1",
            "diagnostics_status": diagnostics_status,
        }

    return {
        "current": {
            "status": STATUS_MISSING_DATA,
            "source_path": None,
            "generated_at": None,
            "metrics_available": False,
            "metrics": {},
        },
        "historical": historical,
        "display_status": STATUS_LEGACY_ONLY if historical_metrics_available else STATUS_MISSING_DATA,
        "display_reason": TOXIC_LEGACY_REASON
        if historical_metrics_available
        else (
            "current toxic metrics are not present in benchmark_primary_v1; "
            "historical toxic baseline missing"
        ),
        "diagnostics_status": diagnostics_status,
    }


def extract_legacy_metric(legacy: dict[str, Any], metric_name: str) -> dict[str, Any] | None:
    row = legacy.get("row") or {}
    aliases = METRIC_ALIASES.get(metric_name, (metric_name,))
    for alias in aliases:
        for key, value in row.items():
            if str(key).lower() == alias.lower():
                numeric = _to_float(value)
                return {
                    "legacy_value": numeric if numeric is not None else value,
                    "legacy_source_timestamp": legacy.get("timestamp"),
                    "legacy_is_stale": True,
                    "legacy_source_path": legacy.get("source_path_display") or legacy.get("source_path"),
                }
    return None


def resolve_metric(
    metric_name: str,
    *,
    diagnostics: dict[str, Any],
    legacy: dict[str, Any],
    allow_legacy_as_primary: bool = False,
) -> dict[str, Any]:
    """Resolve one metric: fresh reports first; never silently promote June legacy."""
    reports = diagnostics.get("reports") or []
    hit = extract_metric_from_reports(reports, metric_name) if reports else None
    legacy_hit = extract_legacy_metric(legacy, metric_name) if legacy.get("row") else None

    if hit is not None:
        freshness_status = diagnostics.get("freshness_status") or STATUS_CURRENT
        out = {
            "value": hit["value"],
            "metric_source": hit["metric_source"],
            "metric_freshness": freshness_status,
            "metric_is_legacy": False,
            "status": STATUS_CURRENT if freshness_status == STATUS_CURRENT else freshness_status,
        }
        if legacy_hit:
            out.update(legacy_hit)
        return out

    if allow_legacy_as_primary and legacy_hit is not None and diagnostics.get("payload") is None:
        return {
            "value": legacy_hit["legacy_value"],
            "metric_source": legacy_hit.get("legacy_source_path"),
            "metric_freshness": STATUS_STALE_VALIDATION,
            "metric_is_legacy": True,
            "status": STATUS_STALE_VALIDATION,
            **legacy_hit,
        }

    out: dict[str, Any] = {
        "value": None,
        "metric_source": None,
        "metric_freshness": STATUS_MISSING,
        "metric_is_legacy": False,
        "status": STATUS_MISSING,
    }
    if legacy_hit:
        out.update(legacy_hit)
    return out


MODEL_SUMMARY_SOURCE_VERSION = "benchmark_primary_v1"


def build_model_summary_sources(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble diagnostics / governance / legacy source descriptors."""
    now_utc = now or datetime.now(timezone.utc)
    diagnostics = pick_primary_diagnostics(now=now_utc)
    governance = resolve_governance_source(now=now_utc)
    # Legacy is never primary when any diagnostics report exists.
    legacy_primary = diagnostics.get("payload") is None
    legacy = resolve_legacy_monitoring(now=now_utc, used_as_primary=legacy_primary)

    metrics = {
        name: resolve_metric(
            name,
            diagnostics=diagnostics,
            legacy=legacy,
            allow_legacy_as_primary=legacy_primary,
        )
        for name in ("psi", "macro_f1", "balanced_accuracy", "loss_recall")
    }

    diagnostics_status = diagnostics.get("freshness_status") or STATUS_MISSING
    if diagnostics.get("payload") is not None and not diagnostics.get("is_stale"):
        diagnostics_status = STATUS_CURRENT

    diag_used_as_primary = diagnostics.get("payload") is not None
    legacy_freshness = legacy.get("freshness_status")
    if legacy.get("is_stale") and legacy.get("row") is not None:
        legacy_freshness = "STALE"
    elif legacy.get("row") is None and legacy.get("source_path") is None:
        legacy_freshness = STATUS_MISSING

    gov_path = (
        governance.get("source_path_display")
        or governance.get("source_path")
        or GOVERNANCE_CANDIDATES[0]
    )

    return {
        "model_summary_source_version": MODEL_SUMMARY_SOURCE_VERSION,
        "diagnostics_primary": {
            "source_path": diagnostics.get("source_path_display") or diagnostics.get("source_path"),
            "generated_at": diagnostics.get("generated_at"),
            "freshness_status": diagnostics_status,
            "age_hours": diagnostics.get("age_hours"),
            "age_days": diagnostics.get("age_days"),
            "is_stale": diagnostics.get("is_stale"),
            "used_as_primary": diag_used_as_primary,
        },
        "governance": {
            "source_path": gov_path,
            "status": governance.get("status"),
            "missing_reason": governance.get("missing_reason"),
        },
        "legacy_monitoring": {
            "source_path": legacy.get("source_path_display") or legacy.get("source_path"),
            "timestamp": _iso(parse_timestamp(legacy.get("timestamp"))) if legacy.get("timestamp") is not None else legacy.get("timestamp"),
            "age_days": legacy.get("age_days"),
            "age_hours": legacy.get("age_hours"),
            "used_as_primary": bool(legacy.get("used_as_primary")),
            "is_stale": legacy.get("is_stale"),
            "freshness_status": legacy_freshness,
        },
        "metrics": metrics,
        "_diagnostics": diagnostics,
        "_governance": governance,
        "_legacy": legacy,
    }


def compose_attention_reason(
    *,
    diagnostics_status: str,
    governance_status: str,
) -> str | None:
    gov_missing = governance_status in {STATUS_GOVERNANCE_MISSING, STATUS_MISSING}
    diag_current = diagnostics_status == STATUS_CURRENT
    diag_stale = diagnostics_status in {
        STATUS_STALE_VALIDATION,
        "STALE_DRIFT_DATA",
        STATUS_UNKNOWN,
    }

    if gov_missing and diag_current:
        return "governance artifact missing; benchmark diagnostics current"
    if diag_stale:
        return "benchmark diagnostics stale"
    if gov_missing and diagnostics_status == STATUS_MISSING:
        return "governance artifact missing; benchmark diagnostics missing"
    if gov_missing:
        return "governance artifact missing"
    return None


def build_model_summary_from_sources(
    *,
    sources: dict[str, Any],
    governance: dict[str, Any],
    drift: dict[str, Any],
    shadow: dict[str, Any],
    base_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose Model Summary using source priority (benchmark primary)."""
    summary = dict(base_summary or {})
    diagnostics = sources.get("_diagnostics") or {}
    gov_src = sources.get("_governance") or {}
    legacy = sources.get("legacy_monitoring") or {}
    metrics = sources.get("metrics") or {}

    diagnostics_status = (sources.get("diagnostics_primary") or {}).get("freshness_status") or STATUS_MISSING
    governance_status = str(
        governance.get("governance_status")
        or gov_src.get("status")
        or STATUS_GOVERNANCE_MISSING
    )

    latest_diagnostics_at = diagnostics.get("generated_at")
    summary["latest_diagnostics_at"] = latest_diagnostics_at
    summary["diagnostics_status"] = diagnostics_status
    # Do not present June legacy timestamp as the primary "last validation".
    summary["last_validation_at"] = latest_diagnostics_at
    summary["governance_validation_at"] = governance.get("last_validation_at") or gov_src.get("generated_at")
    summary["model"] = missing_label(summary.get("model") or governance.get("active_model"))
    summary["governance_status"] = governance_status
    summary["promotion_eligible_label"] = governance.get("promotion_eligible_label") or "NO"
    summary["source_freshness"] = diagnostics_status if diagnostics_status == STATUS_CURRENT else (
        "STALE" if diagnostics.get("is_stale") else diagnostics_status
    )
    has_current_metrics = any(
        (metrics.get(name) or {}).get("value") is not None for name in ("psi", "macro_f1", "loss_recall")
    )
    summary["metric_availability"] = (
        "AVAILABLE"
        if has_current_metrics
        else (
            "LEGACY_ONLY"
            if any((metrics.get(name) or {}).get("legacy_value") is not None for name in ("psi", "macro_f1", "loss_recall"))
            else "MISSING_DATA"
        )
    )

    psi_m = metrics.get("psi") or {}
    macro_m = metrics.get("macro_f1") or {}
    loss_m = metrics.get("loss_recall") or {}
    summary["psi"] = psi_m.get("value")
    summary["psi_meta"] = {
        k: psi_m.get(k)
        for k in (
            "metric_source",
            "metric_freshness",
            "metric_is_legacy",
            "status",
            "legacy_value",
            "legacy_source_timestamp",
            "legacy_is_stale",
        )
    }
    summary["shadow_macro_f1"] = macro_m.get("value")
    summary["macro_f1_meta"] = {
        k: macro_m.get(k)
        for k in (
            "metric_source",
            "metric_freshness",
            "metric_is_legacy",
            "status",
            "legacy_value",
            "legacy_source_timestamp",
            "legacy_is_stale",
        )
    }
    summary["loss_recall"] = loss_m.get("value")
    summary["loss_recall_meta"] = {
        k: loss_m.get(k)
        for k in (
            "metric_source",
            "metric_freshness",
            "metric_is_legacy",
            "status",
            "legacy_value",
            "legacy_source_timestamp",
            "legacy_is_stale",
        )
    }
    summary["model_summary_source_version"] = (
        sources.get("model_summary_source_version") or MODEL_SUMMARY_SOURCE_VERSION
    )
    summary["model_summary_sources"] = {
        "diagnostics_primary": sources.get("diagnostics_primary"),
        "governance": sources.get("governance"),
        "legacy_monitoring": {
            "source_path": legacy.get("source_path"),
            "timestamp": legacy.get("timestamp"),
            "age_days": legacy.get("age_days"),
            "used_as_primary": bool(legacy.get("used_as_primary")),
            "is_stale": legacy.get("is_stale"),
            "freshness_status": legacy.get("freshness_status"),
        },
    }
    # Explicit legacy metric bag — never promote into current PSI/F1 fields.
    summary["legacy_metrics"] = {
        "psi": (metrics.get("psi") or {}).get("legacy_value"),
        "macro_f1": (metrics.get("macro_f1") or {}).get("legacy_value"),
        "loss_recall": (metrics.get("loss_recall") or {}).get("legacy_value"),
        "source_timestamp": legacy.get("timestamp"),
        "is_stale": True if legacy.get("timestamp") else None,
    }
    if governance_status in {STATUS_GOVERNANCE_MISSING, STATUS_MISSING} or governance.get("promotion_eligible") is False:
        summary["promotion_eligible"] = False
        summary["promotion_eligible_label"] = "NO"
    else:
        summary["promotion_eligible"] = bool(governance.get("promotion_eligible"))
        summary["promotion_eligible_label"] = governance.get("promotion_eligible_label") or (
            "YES" if governance.get("promotion_eligible") else "NO"
        )

    diag_fresh = diagnostics.get("freshness") or build_freshness(
        source_path=diagnostics.get("source_path"),
        source_timestamp=latest_diagnostics_at,
        max_age_hours=MODEL_BENCHMARK_MAX_AGE_HOURS,
    )
    summary["freshness"] = diag_fresh
    summary["metrics_scope"] = "current" if diagnostics_status == STATUS_CURRENT else diag_fresh.get("metrics_scope")

    reason = compose_attention_reason(
        diagnostics_status=diagnostics_status,
        governance_status=governance_status,
    )
    if reason:
        summary["status"] = "ATTENTION"
        summary["level"] = "YELLOW"
        summary["status_reason"] = reason
        summary["attention_reason"] = reason
        summary["freshness_status"] = (
            STATUS_CURRENT if diagnostics_status == STATUS_CURRENT else diagnostics_status
        )
        if "stale" in reason:
            summary["stale_warning"] = (
                f"Data is stale. Latest diagnostics were {latest_diagnostics_at}. Metrics are historical."
            )
        else:
            summary["stale_warning"] = None
    else:
        # Preserve caller base status when no attention reason.
        summary.setdefault("status", "HEALTHY")
        summary.setdefault("level", "GREEN")
        summary["freshness_status"] = diagnostics_status
        summary["attention_reason"] = None
        summary["status_reason"] = None

    return summary


def drift_fields_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Map conformance/integrated drift labels when classic PSI metrics are absent."""
    payload = diagnostics.get("payload") or {}
    reports = diagnostics.get("reports") or []
    severity = None
    cognition_health = None
    for report in reports:
        hit = find_metric_ci(report.get("payload"), ("severity",))
        if hit and severity is None:
            # Prefer nested drift.severity over unrelated severity keys when path contains drift.
            value, path = hit
            if "drift" in path.lower() or severity is None:
                if "drift" in path.lower():
                    severity = str(value)
        health = find_metric_ci(report.get("payload"), ("cognition_health",))
        if health and cognition_health is None:
            cognition_health = str(health[0])

    drift_obj = payload.get("drift") if isinstance(payload.get("drift"), dict) else {}
    if severity is None and drift_obj.get("severity") is not None:
        severity = str(drift_obj.get("severity"))
    if cognition_health is None:
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        if summary.get("cognition_health") is not None:
            cognition_health = str(summary.get("cognition_health"))

    return {
        "benchmark_drift_severity": severity,
        "cognition_health": cognition_health,
        "benchmark_status": payload.get("status"),
    }
