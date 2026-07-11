"""Tests for Model Summary / governance freshness guard (dashboard-only)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.model_summary_freshness import (  # noqa: E402
    MAX_AGE_ECONOMIC_HOURS,
    MAX_AGE_VALIDATION_HOURS,
    STATUS_CURRENT,
    STATUS_MISSING,
    STATUS_STALE_GOVERNANCE,
    STATUS_STALE_VALIDATION,
    apply_stale_governance,
    build_freshness,
    build_model_summary_with_freshness,
)


NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def test_fresh_artifact_is_current(tmp_path: Path) -> None:
    path = tmp_path / "monitoring.parquet"
    path.write_bytes(b"x")
    ts = NOW - timedelta(hours=12)
    freshness = build_freshness(
        source_path=str(path),
        source_timestamp=ts,
        max_age_hours=MAX_AGE_VALIDATION_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
        now=NOW,
    )
    assert freshness["is_stale"] is False
    assert freshness["freshness_status"] == STATUS_CURRENT
    assert freshness["metrics_scope"] == "current"
    assert freshness["age_hours"] == pytest.approx(12.0)


def test_old_artifact_is_stale_validation(tmp_path: Path) -> None:
    path = tmp_path / "monitoring.parquet"
    path.write_bytes(b"x")
    ts = NOW - timedelta(days=20)
    freshness = build_freshness(
        source_path=str(path),
        source_timestamp=ts,
        max_age_hours=MAX_AGE_VALIDATION_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
        now=NOW,
    )
    assert freshness["is_stale"] is True
    assert freshness["freshness_status"] == STATUS_STALE_VALIDATION
    assert freshness["metrics_scope"] == "historical"
    assert freshness["age_days"] == pytest.approx(20.0)
    assert "2026-06-20" in (freshness["stale_reason"] or "")
    assert "historical" in (freshness["warning"] or "").lower()


def test_missing_artifact_is_missing_data() -> None:
    freshness = build_freshness(
        source_path=None,
        source_timestamp=None,
        max_age_hours=MAX_AGE_VALIDATION_HOURS,
        now=NOW,
    )
    assert freshness["is_stale"] is True
    assert freshness["freshness_status"] == STATUS_MISSING
    assert freshness["metrics_scope"] == "missing"


def test_missing_timestamp_uses_fresh_mtime(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    path.write_text("{}", encoding="utf-8")
    # Touch mtime to "now"
    import os

    os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    freshness = build_freshness(
        source_path=str(path),
        source_timestamp=None,
        max_age_hours=MAX_AGE_VALIDATION_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
        now=NOW + timedelta(hours=1),
    )
    assert freshness["is_stale"] is False
    assert freshness["freshness_status"] == STATUS_CURRENT
    assert freshness["source_mtime"] is not None
    assert freshness["source_timestamp"] is None


def test_governance_stale_forces_promotion_no(tmp_path: Path) -> None:
    path = tmp_path / "gov.json"
    path.write_text("{}", encoding="utf-8")
    freshness = build_freshness(
        source_path=str(path),
        source_timestamp=NOW - timedelta(days=14),
        max_age_hours=MAX_AGE_VALIDATION_HOURS,
        stale_status=STATUS_STALE_GOVERNANCE,
        now=NOW,
    )
    out = apply_stale_governance(
        {
            "governance_status": "DRIFT_WARNING",
            "promotion_eligible": True,
            "promotion_eligible_label": "YES",
            "active_model": None,
            "candidate_model": "",
            "level": "YELLOW",
        },
        freshness,
    )
    assert out["promotion_eligible"] is False
    assert out["promotion_eligible_label"] == "NO"
    assert out["governance_status"] == "DRIFT_WARNING+STALE"
    assert out["active_model_display"] == "MISSING"
    assert out["candidate_model_display"] == "MISSING"
    assert out["metrics_scope"] == "historical"


def test_model_summary_stale_attention() -> None:
    gov_fresh = build_freshness(
        source_path="/tmp/missing-gov",
        source_timestamp="2026-06-14T12:00:00Z",
        max_age_hours=MAX_AGE_VALIDATION_HOURS,
        stale_status=STATUS_STALE_GOVERNANCE,
        now=NOW,
    )
    # Force stale even if path missing by providing timestamp
    assert gov_fresh["is_stale"] is True

    summary = build_model_summary_with_freshness(
        governance={
            "freshness": gov_fresh,
            "governance_status": "DRIFT_WARNING+STALE",
            "active_model": None,
            "last_validation_at": "2026-06-14T12:00:00Z",
            "promotion_eligible_label": "NO",
        },
        drift={"freshness": {"is_stale": True}},
        shadow={"freshness": {"is_stale": True}, "last_validation_time": "2026-06-14T12:00:00Z"},
        base_summary={
            "level": "GREEN",
            "status": "HEALTHY",
            "model": None,
            "shadow_macro_f1": 0.42,
            "loss_recall": 0.55,
            "psi": 0.258,
            "governance_status": "DRIFT_WARNING",
        },
    )
    assert summary["status"] == "ATTENTION"
    assert summary["level"] == "YELLOW"
    assert "stale" in (summary["status_reason"] or "").lower()
    assert summary["last_validation_at"] == "2026-06-14T12:00:00Z"
    assert summary["metrics_scope"] == "historical"
    assert summary["model"] == "MISSING"
    assert summary["promotion_eligible_label"] == "NO"
    assert summary["freshness_status"] == STATUS_STALE_VALIDATION


def test_toxic_box_stale_not_current_baseline() -> None:
    freshness = build_freshness(
        source_path=None,
        source_timestamp="2026-06-11T00:00:00Z",
        max_age_hours=MAX_AGE_VALIDATION_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
        now=NOW,
    )
    from app.services.model_summary_freshness import apply_stale_block

    payload = apply_stale_block(
        {
            "level": "GREEN",
            "severity_label": "Baseline loaded (STALE)",
            "events": 12,
        },
        freshness,
    )
    assert payload["freshness"]["is_stale"] is True
    assert "STALE" in payload["severity_label"]
    assert payload["metrics_scope"] == "historical"
    assert payload["stale_warning"]


def test_economic_validation_stale_over_48h(tmp_path: Path) -> None:
    path = tmp_path / "economic.parquet"
    path.write_bytes(b"x")
    freshness = build_freshness(
        source_path=str(path),
        source_timestamp=NOW - timedelta(hours=60),
        max_age_hours=MAX_AGE_ECONOMIC_HOURS,
        stale_status=STATUS_STALE_VALIDATION,
        now=NOW,
    )
    assert freshness["is_stale"] is True
    assert freshness["freshness_status"] == STATUS_STALE_VALIDATION
    assert freshness["max_age_hours"] == 48
