"""Freshness guard for Model Summary / Governance / Drift / Toxic / Economic cards.

Does not retrain models. Does not change pipeline or execution.
Marks research artifacts as CURRENT / STALE_* / MISSING_DATA / UNKNOWN_FRESHNESS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import (
    MODEL_BENCHMARK_MAX_AGE_HOURS,
    MODEL_DRIFT_MAX_AGE_HOURS,
    MODEL_ECONOMIC_MAX_AGE_HOURS,
    MODEL_GOVERNANCE_MAX_AGE_HOURS,
    MODEL_TOXIC_MAX_AGE_HOURS,
    MODEL_VALIDATION_MAX_AGE_HOURS,
    REPO_ROOT,
)

# Thresholds (hours) — re-exported for tests / callers
MAX_AGE_GOVERNANCE_HOURS = MODEL_GOVERNANCE_MAX_AGE_HOURS
MAX_AGE_DRIFT_HOURS = MODEL_DRIFT_MAX_AGE_HOURS
MAX_AGE_TOXIC_HOURS = MODEL_TOXIC_MAX_AGE_HOURS
MAX_AGE_ECONOMIC_HOURS = MODEL_ECONOMIC_MAX_AGE_HOURS
MAX_AGE_BENCHMARK_HOURS = MODEL_BENCHMARK_MAX_AGE_HOURS
MAX_AGE_VALIDATION_HOURS = MODEL_VALIDATION_MAX_AGE_HOURS

STATUS_CURRENT = "CURRENT"
STATUS_STALE_VALIDATION = "STALE_VALIDATION"
STATUS_STALE_GOVERNANCE = "STALE_GOVERNANCE_DATA"
STATUS_STALE_DRIFT = "STALE_DRIFT_DATA"
STATUS_MISSING = "MISSING_DATA"
STATUS_UNKNOWN = "UNKNOWN_FRESHNESS"

REFRESH_HINT = "Run manual validation/retrain to refresh model governance."


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        ts = value
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.to_pydatetime()
    except Exception:
        return None


def file_mtime_utc(path: str | Path | None) -> datetime | None:
    if not path:
        return None
    try:
        p = Path(path)
        if not p.exists():
            return None
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def resolve_existing_path(*candidates: str | Path | None) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_absolute():
            path = Path(REPO_ROOT) / path
        if path.exists():
            return str(path)
    return None


def build_freshness(
    *,
    source_path: str | None,
    source_timestamp: Any = None,
    max_age_hours: float,
    stale_status: str = STATUS_STALE_VALIDATION,
    missing_status: str = STATUS_MISSING,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build normalized freshness payload for one dashboard block."""
    now_utc = now or _utc_now()
    path = source_path
    mtime = file_mtime_utc(path)
    artifact_ts = parse_timestamp(source_timestamp)

    if path is None or (path and not Path(path).exists()):
        if artifact_ts is None and mtime is None:
            return {
                "source_path": path,
                "source_timestamp": None,
                "source_mtime": None,
                "age_hours": None,
                "age_days": None,
                "is_stale": True,
                "stale_reason": "source artifact missing",
                "max_age_hours": float(max_age_hours),
                "freshness_status": missing_status,
                "metrics_scope": "missing",
                "warning": "Data is missing. Metrics are unavailable.",
            }

    effective_ts = artifact_ts or mtime
    source_ts_iso = artifact_ts.isoformat().replace("+00:00", "Z") if artifact_ts else None
    mtime_iso = mtime.isoformat().replace("+00:00", "Z") if mtime else None

    if effective_ts is None:
        return {
            "source_path": path,
            "source_timestamp": source_ts_iso,
            "source_mtime": mtime_iso,
            "age_hours": None,
            "age_days": None,
            "is_stale": True,
            "stale_reason": "timestamp unavailable",
            "max_age_hours": float(max_age_hours),
            "freshness_status": STATUS_UNKNOWN,
            "metrics_scope": "unknown",
            "warning": "Data freshness unknown. Treat metrics as unverified.",
        }

    age_hours = max(0.0, (now_utc - effective_ts).total_seconds() / 3600.0)
    age_days = round(age_hours / 24.0, 2)
    is_stale = age_hours > float(max_age_hours)
    if is_stale:
        as_of = effective_ts.date().isoformat()
        reason = (
            f"Data is stale. Last validation was {as_of}. Metrics are historical."
            if artifact_ts is not None
            else f"Data is stale. Source mtime was {as_of}. Metrics are historical."
        )
        return {
            "source_path": path,
            "source_timestamp": source_ts_iso,
            "source_mtime": mtime_iso,
            "age_hours": round(age_hours, 2),
            "age_days": age_days,
            "is_stale": True,
            "stale_reason": reason,
            "max_age_hours": float(max_age_hours),
            "freshness_status": stale_status,
            "metrics_scope": "historical",
            "warning": reason,
            "refresh_hint": REFRESH_HINT,
        }

    return {
        "source_path": path,
        "source_timestamp": source_ts_iso,
        "source_mtime": mtime_iso,
        "age_hours": round(age_hours, 2),
        "age_days": age_days,
        "is_stale": False,
        "stale_reason": None,
        "max_age_hours": float(max_age_hours),
        "freshness_status": STATUS_CURRENT,
        "metrics_scope": "current",
        "warning": None,
        "refresh_hint": None,
    }


def missing_label(value: Any, *, missing_token: str = "MISSING") -> str:
    if value is None:
        return missing_token
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "—", "-"}:
        return missing_token
    return text


def apply_stale_governance(
    governance: dict[str, Any],
    freshness: dict[str, Any],
) -> dict[str, Any]:
    """Force promotion NO and annotate status when governance/validation is stale."""
    out = dict(governance)
    out["freshness"] = freshness
    out["active_model_display"] = missing_label(out.get("active_model"))
    out["candidate_model_display"] = missing_label(out.get("candidate_model"))
    out["metrics_scope"] = freshness.get("metrics_scope")

    if freshness.get("is_stale"):
        out["promotion_eligible"] = False
        out["promotion_eligible_label"] = "NO"
        status = str(out.get("governance_status") or "")
        if freshness.get("freshness_status") == STATUS_MISSING:
            out["governance_status"] = STATUS_MISSING
        elif status and status not in {STATUS_STALE_GOVERNANCE, STATUS_STALE_VALIDATION}:
            out["governance_status"] = f"{status}+STALE"
            out["governance_status_base"] = status
        else:
            out["governance_status"] = STATUS_STALE_GOVERNANCE
        out["level"] = "YELLOW"
        out["stale_warning"] = freshness.get("warning")
        out["refresh_hint"] = REFRESH_HINT
    return out


def apply_stale_block(
    block: dict[str, Any],
    freshness: dict[str, Any],
    *,
    stale_status_field: str | None = None,
    stale_status_value: str | None = None,
) -> dict[str, Any]:
    out = dict(block)
    out["freshness"] = freshness
    out["metrics_scope"] = freshness.get("metrics_scope")
    if freshness.get("is_stale"):
        out["level"] = "YELLOW" if out.get("level") != "RED" else out.get("level")
        out["stale_warning"] = freshness.get("warning")
        out["refresh_hint"] = REFRESH_HINT
        if stale_status_field and stale_status_value:
            out[stale_status_field] = stale_status_value
    return out


def build_model_summary_with_freshness(
    *,
    governance: dict[str, Any],
    drift: dict[str, Any],
    shadow: dict[str, Any],
    base_summary: dict[str, Any],
) -> dict[str, Any]:
    """Downgrade Model Summary when validation/governance/drift are stale."""
    summary = dict(base_summary)
    gov_fresh = (governance.get("freshness") or {})
    drift_fresh = (drift.get("freshness") or {})
    shadow_fresh = (shadow.get("freshness") or {})

    stale_parts = []
    if gov_fresh.get("is_stale"):
        stale_parts.append("governance")
    if drift_fresh.get("is_stale"):
        stale_parts.append("drift")
    if shadow_fresh.get("is_stale"):
        stale_parts.append("validation")

    summary["freshness"] = gov_fresh or drift_fresh or shadow_fresh or build_freshness(
        source_path=None,
        max_age_hours=MAX_AGE_VALIDATION_HOURS,
        missing_status=STATUS_MISSING,
    )
    summary["metrics_scope"] = "historical" if stale_parts else summary.get("metrics_scope", "current")
    summary["model"] = missing_label(summary.get("model") or governance.get("active_model"))
    summary["last_validation_at"] = (
        governance.get("last_validation_at")
        or shadow.get("last_validation_time")
        or (gov_fresh.get("source_timestamp") if gov_fresh else None)
    )

    if stale_parts:
        summary["status"] = "ATTENTION"
        summary["level"] = "YELLOW"
        summary["freshness_status"] = STATUS_STALE_VALIDATION
        summary["status_reason"] = "model validation data stale"
        summary["attention_reason"] = "model validation data stale"
        as_of = summary.get("last_validation_at") or gov_fresh.get("source_timestamp") or "unknown"
        if hasattr(as_of, "isoformat"):
            as_of = as_of.isoformat().replace("+00:00", "Z")
        # Prefer date-only in warning when possible
        as_of_str = str(as_of)
        if "T" in as_of_str:
            as_of_str = as_of_str.split("T", 1)[0]
        summary["stale_warning"] = (
            f"Data is stale. Last validation was {as_of_str}. Metrics are historical."
        )
        summary["refresh_hint"] = REFRESH_HINT
        summary["governance_status"] = governance.get("governance_status")
        summary["promotion_eligible_label"] = "NO"
        summary["metrics_scope"] = "historical"
    return summary
