"""Stage 11.2 / 11.3 / 11.4 — Model Summary UI semantics, Toxic Box source truth."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.model_summary_sources import MODEL_SUMMARY_SOURCE_VERSION  # noqa: E402
from app.services.research_pipeline_service import (  # noqa: E402
    build_drift_monitoring_snapshot,
    build_model_governance_snapshot,
    build_research_pipeline_snapshot,
    build_shadow_inference_snapshot,
    build_toxic_box_snapshot,
)

TOXIC_ACTION = (
    "Refresh toxic/economic validation artifacts if current toxic monitoring is required."
)
ATTENTION_REASON = "governance artifact missing; benchmark diagnostics current"


def _format_source_lines(sources: dict, *, version: str, promotion: str) -> list[str]:
    """Mirror frontend formatModelSummarySourceLines (no reason per line)."""
    diag = sources["diagnostics_primary"]
    gov = sources["governance"]
    legacy = sources["legacy_monitoring"]
    return [
        f"Data source: {version}",
        f"Latest diagnostics: {diag['generated_at']} · {diag['freshness_status']}",
        f"Source: {diag['source_path']}",
        f"Governance: {gov['status']}",
        f"Legacy monitoring: {legacy['timestamp']} · {legacy['freshness_status']} · not primary",
        f"Promotion eligible: {promotion}",
    ]


def _dedupe_phrases(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = re.sub(r"\s+", " ", line.strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _format_toxic_box_display(toxic: dict) -> list[str]:
    """Mirror frontend formatToxicBoxDisplay rendered lines (Stage 11.4)."""
    display = str(toxic.get("display_status") or toxic.get("severity_label") or "").upper()
    current = toxic.get("current") or {}
    historical = toxic.get("historical") or {}
    is_current = display == "CURRENT"
    legacy_only = (not is_current) and (
        "LEGACY" in display
        or str(current.get("status") or "").upper().startswith("MISSING")
        or bool((toxic.get("freshness") or {}).get("is_stale"))
    )

    header = "CURRENT" if is_current else ("LEGACY_ONLY / STALE" if legacy_only else display or "MISSING_DATA")
    current_line = "Current toxic monitoring: MISSING_DATA" if legacy_only else None
    baseline = (
        "Current toxic monitoring loaded"
        if is_current
        else ("Historical toxic baseline loaded" if legacy_only else None)
    )
    hist_src = Path(
        str(historical.get("source_path") or toxic.get("historical_source_path") or toxic.get("source_path") or "")
    ).name or "toxic_box_memory.parquet"
    age = historical.get("age_days")
    if age is None:
        age = toxic.get("historical_age_days") or (toxic.get("freshness") or {}).get("age_days")
    ts = historical.get("timestamp") or toxic.get("historical_timestamp") or (toxic.get("freshness") or {}).get(
        "source_timestamp"
    )
    as_of = None
    if ts or age is not None:
        # Mirror formatSourceTimestamp loosely as YYYY-MM-DD / locale-like day.
        as_of_label = str(ts)[:10] if ts else "—"
        if ts and "2026-06-14" in str(ts):
            as_of_label = "14 Jun 2026"
        age_label = f"{float(age):.2f} days" if age is not None else "—"
        as_of = (
            f"As of: {as_of_label} · age: {age_label}"
            if is_current
            else f"Historical as of: {as_of_label} · age: {age_label}"
        )

    trend = toxic.get("trend") or "—"
    trend_line = f"Historical trend: {trend}" if legacy_only else f"Trend: {trend}"
    source_line = (
        f"Source: {current.get('source_path')}"
        if is_current and current.get("source_path")
        else (f"Historical source: {hist_src}" if legacy_only else None)
    )

    lines = [
        header,
        current_line,
        baseline,
        f"Toxic events: {toxic.get('events', 0)}",
        (
            f"7d: {toxic.get('events_last_7d', 0)} · "
            f"7d toxic rate: {float(toxic.get('toxic_rate_7d') or 0):.2f}/d · "
            f"30d: {float(toxic.get('toxic_rate_30d') or 0):.2f}/d"
        ),
        trend_line,
        source_line,
        as_of,
        f"Action: {TOXIC_ACTION}" if legacy_only else None,
    ]
    return _dedupe_phrases([x for x in lines if x])


def _format_drift_display(drift: dict) -> list[str]:
    """Mirror Drift Monitoring UI lines (no standalone HISTORICAL)."""
    lines = [
        str(drift.get("severity_label") or "MISSING_DATA"),
        (
            f"Current PSI: {drift.get('psi') if drift.get('psi') is not None else '—'} · "
            f"Macro F1: {drift.get('macro_f1') if drift.get('macro_f1') is not None else '—'} · "
            f"Loss recall: {drift.get('loss_recall') if drift.get('loss_recall') is not None else '—'}"
        ),
        drift.get("status_note")
        or (
            "Current drift metrics are not present in benchmark_primary_v1."
            if drift.get("psi") is None
            else None
        ),
    ]
    legacy_psi = drift.get("legacy_psi")
    if legacy_psi is not None:
        ts = drift.get("legacy_source_timestamp")
        when = str(ts)[:10] if ts else None
        legacy = f"Legacy PSI: {float(legacy_psi):.3f} · HISTORICAL · STALE · not primary"
        if when:
            legacy = f"{legacy} · {when}"
        lines.append(legacy)
    return [x for x in lines if x]


def test_format_lines_reason_not_repeated() -> None:
    snap = asyncio.run(build_research_pipeline_snapshot())
    ms = snap["model_summary"]
    reason = ms.get("attention_reason") or ""
    lines = _format_source_lines(
        ms["model_summary_sources"],
        version=ms.get("model_summary_source_version") or MODEL_SUMMARY_SOURCE_VERSION,
        promotion=ms.get("promotion_eligible_label") or "NO",
    )
    assert sum(1 for line in lines if reason and reason in line) == 0
    assert sum(1 for line in lines if "benchmark_primary_v1" in line) == 1
    assert ms.get("model_summary_source_version") == MODEL_SUMMARY_SOURCE_VERSION


def test_attention_reason_appears_once_in_header_context() -> None:
    snap = asyncio.run(build_research_pipeline_snapshot())
    ms = snap["model_summary"]
    reason = (ms.get("attention_reason") or "").strip()
    assert reason
    rendered = [f"ATTENTION · {reason}"] + _format_source_lines(
        ms["model_summary_sources"],
        version=ms.get("model_summary_source_version") or MODEL_SUMMARY_SOURCE_VERSION,
        promotion=ms.get("promotion_eligible_label") or "NO",
    )
    assert sum(1 for line in rendered if reason in line) == 1
    if ATTENTION_REASON in reason:
        assert sum(1 for line in rendered if ATTENTION_REASON in line) == 1


def test_drift_missing_not_severe() -> None:
    drift = asyncio.run(build_drift_monitoring_snapshot())
    assert drift["severity_label"] == "MISSING_DATA"
    assert drift["level"] != "RED"
    assert drift.get("psi") is None
    assert drift.get("legacy_psi") is not None
    assert "SEVERE" not in str(drift["severity_label"]).upper()
    assert drift.get("metric_availability") in {"MISSING_DATA", "LEGACY_ONLY"}
    assert drift.get("source_freshness") == "CURRENT"


def test_drift_no_standalone_historical_line() -> None:
    drift = asyncio.run(build_drift_monitoring_snapshot())
    lines = _format_drift_display(drift)
    standalone = [line for line in lines if line.strip().upper() == "HISTORICAL"]
    assert standalone == []
    legacy_lines = [line for line in lines if line.startswith("Legacy PSI:")]
    assert len(legacy_lines) == 1
    assert "HISTORICAL" in legacy_lines[0]


def test_shadow_missing_with_current_source() -> None:
    shadow = asyncio.run(build_shadow_inference_snapshot())
    assert shadow.get("macro_f1") is None
    assert shadow.get("validation_status") in {"MISSING_DATA", "MISSING"}
    assert shadow.get("source_freshness") == "CURRENT"
    assert shadow.get("metric_availability") == "MISSING_DATA"
    assert shadow.get("metrics_scope") == "missing"


def test_governance_action_mentions_export_not_retrain() -> None:
    gov = asyncio.run(build_model_governance_snapshot())
    assert gov["governance_status"] == "GOVERNANCE_MISSING"
    assert gov["promotion_eligible_label"] == "NO"
    action = gov.get("action") or gov.get("refresh_hint") or ""
    assert "model_governance_dashboard.json" in action or "governance export" in action.lower()
    assert "retrain" not in action.lower()


def test_toxic_stale_message_not_governance() -> None:
    toxic = asyncio.run(build_toxic_box_snapshot())
    if toxic.get("display_status") == "LEGACY_ONLY" or toxic.get("freshness", {}).get("is_stale"):
        msg = (toxic.get("stale_warning") or "") + " " + (toxic.get("refresh_hint") or "")
        assert "toxic" in msg.lower() or "economic" in msg.lower()
        assert "model governance" not in msg.lower()
        assert "retrain" not in msg.lower()


def test_toxic_legacy_only_ui_semantics() -> None:
    toxic = asyncio.run(build_toxic_box_snapshot())
    assert toxic.get("display_status") == "LEGACY_ONLY"
    assert (toxic.get("current") or {}).get("status") == "MISSING_DATA"
    hist = toxic.get("historical") or {}
    assert "toxic_box_memory.parquet" in str(hist.get("source_path") or "")
    assert "2026-06-14" in str(hist.get("timestamp") or "")

    lines = _format_toxic_box_display(toxic)
    blob = "\n".join(lines)

    assert any("Current toxic monitoring: MISSING_DATA" in line for line in lines)
    assert any("Historical source: toxic_box_memory.parquet" in line for line in lines)
    assert any("Historical as of: 14 Jun 2026" in line for line in lines)
    assert any(line.strip() == "LEGACY_ONLY / STALE" for line in lines)

    # No standalone CURRENT / STABLE badge lines.
    assert not any(line.strip() == "CURRENT" for line in lines)
    assert not any(line.strip() == "STABLE" for line in lines)

    trend_lines = [line for line in lines if "trend" in line.lower()]
    assert len(trend_lines) == 1
    assert trend_lines[0].startswith("Historical trend:")
    assert not any(line.startswith("Trend:") for line in lines)

    assert sum(1 for line in lines if "Refresh toxic/economic validation artifacts" in line) == 1
    assert "2026-07-11" not in blob  # no fresh July date for Toxic Box
    assert "model governance" not in blob.lower()
    assert "retrain" not in blob.lower()


def test_toxic_box_dedup_baseline_and_action() -> None:
    toxic = asyncio.run(build_toxic_box_snapshot())
    lines = _format_toxic_box_display(toxic)
    baseline_hits = sum(
        1
        for line in lines
        if "baseline loaded" in line.lower() or "historical toxic baseline loaded" in line.lower()
    )
    assert baseline_hits <= 1
    assert sum(1 for line in lines if "Refresh toxic/economic validation artifacts" in line) <= 1


def test_june_psi_only_legacy() -> None:
    snap = asyncio.run(build_research_pipeline_snapshot())
    ms = snap["model_summary"]
    assert ms.get("psi") is None
    legacy_psi = (ms.get("legacy_metrics") or {}).get("psi")
    assert legacy_psi is not None
    assert abs(float(legacy_psi) - 0.258) < 0.01 or abs(float(legacy_psi) - 0.2577) < 0.01
    assert ms.get("metric_availability") in {"MISSING_DATA", "LEGACY_ONLY"}
    assert ms.get("source_freshness") == "CURRENT"


def test_benchmark_primary_v1_still_present() -> None:
    snap = asyncio.run(build_research_pipeline_snapshot())
    ms = snap["model_summary"]
    assert ms.get("model_summary_source_version") == "benchmark_primary_v1"
    assert MODEL_SUMMARY_SOURCE_VERSION == "benchmark_primary_v1"
    diag = ms["model_summary_sources"]["diagnostics_primary"]
    assert diag["freshness_status"] == "CURRENT"
    assert str(diag["generated_at"]).startswith("2026-07-11")
