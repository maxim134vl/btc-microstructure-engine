"""Tests for Model Summary source priority (benchmark primary, legacy fallback)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import model_summary_sources as sources_mod  # noqa: E402
from app.services.model_summary_freshness import STATUS_CURRENT, STATUS_MISSING, STATUS_STALE_VALIDATION  # noqa: E402
from app.services.model_summary_sources import (  # noqa: E402
    STATUS_GOVERNANCE_MISSING,
    build_model_summary_from_sources,
    build_model_summary_sources,
    compose_attention_reason,
    extract_metric_from_reports,
    pick_primary_diagnostics,
    resolve_governance_source,
    resolve_legacy_monitoring,
    resolve_metric,
)
from app.services.research_pipeline_service import (  # noqa: E402
    build_model_governance_snapshot,
    build_toxic_box_snapshot,
)


NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_legacy_parquet(path: Path, ts: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "timestamp": ts,
                "psi_label": 0.258,
                "macro_f1": 0.42,
                "loss_recall": 0.55,
                "balanced_accuracy": 0.61,
            }
        ]
    ).to_parquet(path, index=False)


@pytest.fixture
def isolated_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point REPO_ROOT at a temp tree with controlled artifacts."""
    monkeypatch.setattr(sources_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr("app.config.REPO_ROOT", tmp_path)
    monkeypatch.setattr("app.services.model_summary_freshness.REPO_ROOT", tmp_path)
    return tmp_path


def test_fresh_conformance_primary_not_legacy(isolated_repo: Path) -> None:
    _write_json(
        isolated_repo / "benchmark/conformance/reports/latest_conformance.json",
        {
            "generated_at": "2026-07-11T07:53:14.559449",
            "summary": {"cognition_health": "DRIFTING", "macro_f1": 0.71},
            "drift": {"severity": "SEVERE"},
        },
    )
    _write_legacy_parquet(
        isolated_repo / "data/ml/model_monitoring_memory.parquet",
        datetime(2026, 6, 14, tzinfo=timezone.utc),
    )

    bundle = build_model_summary_sources(now=NOW)
    primary = bundle["diagnostics_primary"]
    legacy = bundle["legacy_monitoring"]

    assert primary["freshness_status"] == STATUS_CURRENT
    assert primary.get("used_as_primary") is True
    assert str(primary["generated_at"]).startswith("2026-07-11")
    assert legacy["used_as_primary"] is False
    assert legacy["is_stale"] is True
    assert legacy["freshness_status"] in {"STALE", "STALE_VALIDATION"}
    assert "2026-06-14" in str(legacy["timestamp"])
    assert bundle.get("model_summary_source_version") == "benchmark_primary_v1"

    diag = pick_primary_diagnostics(now=NOW)
    assert diag["used_as_primary"] is True
    assert "latest_conformance" in (diag["source_path_display"] or "")


def test_missing_governance_json(isolated_repo: Path) -> None:
    _write_json(
        isolated_repo / "benchmark/reports/latest_integrated.json",
        {"generated_at": "2026-07-11T07:53:14", "summary": {}},
    )
    gov = resolve_governance_source(now=NOW)
    assert gov["status"] == STATUS_GOVERNANCE_MISSING
    assert gov["missing_reason"] == "governance artifact missing"

    # Async snapshot path
    import asyncio

    async def _run():
        sources = build_model_summary_sources(now=NOW)
        return await build_model_governance_snapshot(sources)

    out = asyncio.run(_run())
    assert out["governance_status"] == STATUS_GOVERNANCE_MISSING
    assert out["active_model_display"] == "MISSING"
    assert out["candidate_model_display"] == "MISSING"
    assert out["promotion_eligible"] is False
    assert out["promotion_eligible_label"] == "NO"


def test_fresh_benchmark_missing_governance_attention(isolated_repo: Path) -> None:
    _write_json(
        isolated_repo / "benchmark/conformance/reports/latest_conformance.json",
        {"generated_at": "2026-07-11T07:53:14", "summary": {"cognition_health": "OK"}, "drift": {"severity": "OK"}},
    )
    sources = build_model_summary_sources(now=NOW)
    summary = build_model_summary_from_sources(
        sources=sources,
        governance={
            "governance_status": STATUS_GOVERNANCE_MISSING,
            "promotion_eligible_label": "NO",
            "active_model": None,
        },
        drift={},
        shadow={},
        base_summary={"status": "ATTENTION", "level": "YELLOW"},
    )
    assert summary["status"] == "ATTENTION"
    reason = summary["attention_reason"] or ""
    assert "governance artifact missing" in reason
    assert "benchmark diagnostics current" in reason
    assert str(summary["latest_diagnostics_at"]).startswith("2026-07-11")


def test_stale_benchmark_and_legacy_attention(isolated_repo: Path) -> None:
    _write_json(
        isolated_repo / "benchmark/reports/latest.json",
        {"generated_at": "2026-06-01T00:00:00", "summary": {}},
    )
    _write_legacy_parquet(
        isolated_repo / "data/ml/model_monitoring_memory.parquet",
        datetime(2026, 6, 14, tzinfo=timezone.utc),
    )
    sources = build_model_summary_sources(now=NOW)
    assert sources["diagnostics_primary"]["freshness_status"] == STATUS_STALE_VALIDATION
    summary = build_model_summary_from_sources(
        sources=sources,
        governance={"governance_status": STATUS_GOVERNANCE_MISSING, "promotion_eligible_label": "NO"},
        drift={},
        shadow={},
    )
    assert summary["status"] == "ATTENTION"
    assert "benchmark diagnostics stale" in (summary["attention_reason"] or "")


def test_metric_from_benchmark_not_legacy(isolated_repo: Path) -> None:
    _write_json(
        isolated_repo / "benchmark/conformance/reports/latest_conformance.json",
        {
            "generated_at": "2026-07-11T07:53:14",
            "summary": {"macro_f1": 0.77, "psi": 0.11},
        },
    )
    _write_legacy_parquet(
        isolated_repo / "data/ml/model_monitoring_memory.parquet",
        datetime(2026, 6, 14, tzinfo=timezone.utc),
    )
    sources = build_model_summary_sources(now=NOW)
    macro = sources["metrics"]["macro_f1"]
    assert macro["value"] == pytest.approx(0.77)
    assert macro["metric_is_legacy"] is False
    assert "benchmark" in (macro["metric_source"] or "")
    assert macro["legacy_value"] == pytest.approx(0.42)
    assert macro["legacy_is_stale"] is True


def test_metric_missing_does_not_use_june_as_current(isolated_repo: Path) -> None:
    _write_json(
        isolated_repo / "benchmark/conformance/reports/latest_conformance.json",
        {
            "generated_at": "2026-07-11T07:53:14",
            "summary": {"cognition_health": "DRIFTING"},
            "drift": {"severity": "SEVERE"},
        },
    )
    _write_legacy_parquet(
        isolated_repo / "data/ml/model_monitoring_memory.parquet",
        datetime(2026, 6, 14, tzinfo=timezone.utc),
    )
    sources = build_model_summary_sources(now=NOW)
    psi = resolve_metric("psi", diagnostics=sources["_diagnostics"], legacy=sources["_legacy"])
    assert psi["value"] is None
    assert psi["status"] == STATUS_MISSING
    assert psi["metric_is_legacy"] is False
    assert psi["legacy_value"] == pytest.approx(0.258)
    assert psi["legacy_is_stale"] is True


def test_legacy_exposed_not_primary_when_benchmark_fresh(isolated_repo: Path) -> None:
    _write_json(
        isolated_repo / "benchmark/reports/latest_integrated.json",
        {"generated_at": "2026-07-11T07:53:14", "summary": {}},
    )
    _write_legacy_parquet(
        isolated_repo / "data/ml/model_monitoring_memory.parquet",
        datetime(2026, 6, 14, tzinfo=timezone.utc),
    )
    legacy = resolve_legacy_monitoring(now=NOW, used_as_primary=False)
    sources = build_model_summary_sources(now=NOW)
    assert sources["legacy_monitoring"]["used_as_primary"] is False
    assert legacy["source_path"] is not None


def test_toxic_missing_no_baseline_without_source(isolated_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from app.services import research_pipeline_service as rps
    from app.services.model_summary_sources import STATUS_MISSING_DATA

    monkeypatch.setattr(rps, "REPO_ROOT", isolated_repo)
    monkeypatch.setattr(sources_mod, "REPO_ROOT", isolated_repo)
    monkeypatch.setattr(
        rps,
        "resolve_dashboard_read",
        lambda name: str(isolated_repo / "data/ml" / name),
    )

    async def _fake_read(name: str, tail: int = 100):
        return pd.DataFrame()

    monkeypatch.setattr(rps, "read_parquet", _fake_read)

    out = asyncio.run(build_toxic_box_snapshot())
    assert out.get("display_status") == STATUS_MISSING_DATA
    assert (out.get("current") or {}).get("status") == STATUS_MISSING_DATA
    assert "Baseline loaded" not in str(out.get("severity_label"))
    assert "LEGACY_ONLY" not in str(out.get("display_status") or "")


def test_frontend_mapper_source_lines() -> None:
    from app.services.model_summary_sources import STATUS_GOVERNANCE_MISSING as GM
    from app.services.model_summary_sources import MODEL_SUMMARY_SOURCE_VERSION

    lines_payload = {
        "diagnostics_primary": {
            "generated_at": "2026-07-11T07:53:14",
            "freshness_status": STATUS_CURRENT,
            "used_as_primary": True,
        },
        "governance": {"status": GM, "missing_reason": "governance artifact missing"},
        "legacy_monitoring": {
            "timestamp": "2026-06-14T18:30:53Z",
            "used_as_primary": False,
            "is_stale": True,
            "freshness_status": "STALE",
        },
    }
    diag = lines_payload["diagnostics_primary"]["freshness_status"]
    gov = lines_payload["governance"]["status"]
    legacy = lines_payload["legacy_monitoring"]
    assert diag == STATUS_CURRENT
    assert gov == STATUS_GOVERNANCE_MISSING
    assert legacy["used_as_primary"] is False
    assert legacy["is_stale"] is True
    assert MODEL_SUMMARY_SOURCE_VERSION == "benchmark_primary_v1"

    reason = compose_attention_reason(
        diagnostics_status=STATUS_CURRENT,
        governance_status=STATUS_GOVERNANCE_MISSING,
    )
    assert reason == "governance artifact missing; benchmark diagnostics current"


def test_extract_metric_nested_case_insensitive(isolated_repo: Path) -> None:
    reports = [
        {
            "source_path": str(isolated_repo / "benchmark/reports/latest_integrated.json"),
            "source_path_display": "benchmark/reports/latest_integrated.json",
            "generated_at": "2026-07-11T07:53:14",
            "payload": {"Summary": {"PSI_Label": 0.19, "Shadow_Macro_F1": 0.66}},
        }
    ]
    hit = extract_metric_from_reports(reports, "psi")
    assert hit is not None
    assert hit["value"] == pytest.approx(0.19)
    assert hit["metric_is_legacy"] is False


def test_fresh_benchmark_without_toxic_is_legacy_only(isolated_repo: Path) -> None:
    from app.services.model_summary_sources import (
        STATUS_LEGACY_ONLY,
        STATUS_MISSING_DATA,
        payload_has_toxic_metrics,
        resolve_toxic_monitoring_sources,
    )

    _write_json(
        isolated_repo / "benchmark/conformance/reports/latest_conformance.json",
        {
            "generated_at": "2026-07-11T08:35:21",
            "summary": {"cognition_health": "DRIFTING"},
            "cognition_health": "DRIFTING",
        },
    )
    payload = {
        "generated_at": "2026-07-11T08:35:21",
        "summary": {"cognition_health": "DRIFTING"},
        "cognition_health": "DRIFTING",
    }
    assert payload_has_toxic_metrics(payload) is False

    truth = resolve_toxic_monitoring_sources(
        now=NOW,
        historical_source_path=str(isolated_repo / "toxic_box_memory.parquet"),
        historical_timestamp="2026-06-14T12:45:56Z",
        historical_age_days=26.84,
        historical_metrics_available=True,
    )
    assert truth["display_status"] == STATUS_LEGACY_ONLY
    assert truth["current"]["status"] == STATUS_MISSING_DATA
    assert truth["current"]["metrics_available"] is False
    assert truth["historical"]["status"] == "STALE"
    assert "toxic_box_memory.parquet" in str(truth["historical"]["source_path"])
    assert "2026-06-14" in str(truth["historical"]["timestamp"])
    assert "benchmark_primary_v1" in truth["display_reason"]


def test_fresh_benchmark_with_toxic_is_current(isolated_repo: Path) -> None:
    from app.services.model_summary_sources import (
        STATUS_CURRENT,
        payload_has_toxic_metrics,
        resolve_toxic_monitoring_sources,
    )

    _write_json(
        isolated_repo / "benchmark/conformance/reports/latest_conformance.json",
        {
            "generated_at": "2026-07-11T08:35:21",
            "toxic_box": {
                "toxic_events": 12,
                "toxic_rate_7d": 0.4,
                "toxic_rate_30d": 0.3,
                "toxic_trend": "STABLE",
            },
        },
    )
    assert payload_has_toxic_metrics(
        {
            "toxic_box": {"toxic_events": 12, "toxic_rate_7d": 0.4},
        }
    )
    truth = resolve_toxic_monitoring_sources(
        now=NOW,
        historical_source_path=str(isolated_repo / "toxic_box_memory.parquet"),
        historical_timestamp="2026-06-14T12:45:56Z",
        historical_age_days=26.84,
        historical_metrics_available=True,
    )
    assert truth["display_status"] == STATUS_CURRENT
    assert truth["current"]["status"] == STATUS_CURRENT
    assert truth["current"]["metrics_available"] is True
    assert "latest_conformance" in str(truth["current"]["source_path"])
    assert str(truth["current"]["generated_at"]).startswith("2026-07-11")
    assert truth["historical"]["metrics_available"] is True
    assert truth["historical"]["status"] == "STALE"
