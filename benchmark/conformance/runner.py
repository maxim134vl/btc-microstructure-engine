"""Cognition conformance backtest orchestrator."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from benchmark.conformance.benchmark_spec_loader import load_all_specs, load_spec
from benchmark.conformance.calibration_audit import build_calibration_audit
from benchmark.conformance.conformance_validator import validate_layer
from benchmark.conformance.drift_analyzer import analyze_drift
from benchmark.conformance.ontology_integrity import score_ontology_integrity
from benchmark.conformance.paths import (
    EXPORTS_DIR,
    HISTORY_DIR,
    REPORTS_DIR,
    VISUALS_DIR,
    ensure_dirs,
    latest_pointer_path,
    run_id,
)
from benchmark.conformance.report_writer import render_conformance_report, render_drift_report
from benchmark.conformance.runtime_profile_builder import build_runtime_profile
from benchmark.conformance.visuals import render_conformance_chart, render_health_chart
from storage.path_registry import repo_root


def _load_config() -> dict[str, Any]:
    path = repo_root() / "benchmark" / "config.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _conformance_config() -> dict[str, Any]:
    return _load_config().get("conformance", {})


def _aggregate_summary(results: list[dict[str, Any]], ontology: dict[str, Any], calibration: dict[str, Any]) -> dict[str, Any]:
    total = len(results) or 1
    confirmed = sum(1 for r in results if r["verdict"] == "CONFIRMED")
    partial = sum(1 for r in results if r["verdict"] == "PARTIAL")
    failed = sum(1 for r in results if r["verdict"] in ("FAILED", "ONTOLOGY_DEGRADATION"))
    drifting = sum(1 for r in results if r["verdict"] in ("DRIFTING", "SEVERE_DRIFT", "CALIBRATION_COLLAPSE"))
    avg_divergence = sum(float(r.get("divergence", 0.0)) for r in results) / total

    stability = round((confirmed + partial * 0.5) / total, 4)
    calibration_health = round(1.0 - min(1.0, drifting / total + avg_divergence * 0.5), 4)

    confidence_rows = [r for r in results if "confidence" in r["metric"]]
    confidence_score = (
        round(sum(1 for r in confidence_rows if r["verdict"] == "CONFIRMED") / len(confidence_rows), 4)
        if confidence_rows
        else 0.5
    )

    transition_rows = [r for r in results if "transition" in r["metric"]]
    transition_score = (
        round(sum(1 for r in transition_rows if r["verdict"] == "CONFIRMED") / len(transition_rows), 4)
        if transition_rows
        else 0.5
    )

    contradiction_rows = [r for r in results if "contradiction" in r["metric"]]
    contradiction_pressure = (
        round(1.0 - sum(float(r.get("divergence", 0.0)) for r in contradiction_rows) / len(contradiction_rows), 4)
        if contradiction_rows
        else 0.5
    )

    drift_severity_score = round(min(1.0, avg_divergence + drifting / total), 4)

    if stability >= 0.70 and drifting == 0 and calibration["status"] == "STABLE":
        health = "STABLE"
        emoji = "🟢"
    elif stability >= 0.45 or calibration["status"] == "ADVISORY":
        health = "DRIFTING"
        emoji = "🟡"
    else:
        health = "DEGRADED"
        emoji = "🔴"

    return {
        "metric_count": len(results),
        "confirmed_count": confirmed,
        "partial_count": partial,
        "failed_count": failed,
        "drifting_count": drifting,
        "cognition_stability_score": stability,
        "ontology_integrity_score": ontology.get("score", 0.0),
        "calibration_health_score": calibration_health,
        "confidence_realism_score": confidence_score,
        "transition_stability_score": transition_score,
        "contradiction_pressure_score": contradiction_pressure,
        "drift_severity_score": drift_severity_score,
        "cognition_health": health,
        "health_emoji": emoji,
        "verdict_distribution": _verdict_distribution(results),
    }


def _verdict_distribution(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in results:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return counts


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return str(path)


def _write_csv(path: Path, results: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["layer", "metric", "expected_level", "observed_value", "verdict", "divergence", "calibration_hint"]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow({field: row.get(field) for field in fields})
    return str(path)


def run_conformance_backtest(
    *,
    layers: list[str] | None = None,
    lookback_days: int | None = None,
    generate_visuals: bool = True,
) -> dict[str, Any]:
    """Execute architecture conformance backtest against benchmark specs."""

    ensure_dirs()
    config = _conformance_config()
    lookback = lookback_days or config.get("lookback_days", 7)
    target_layers = layers or ["stage1", "stage2", "integrated"]
    rid = run_id()

    profile_bundle = build_runtime_profile(lookback_days=lookback)
    specs = load_all_specs()
    results: list[dict[str, Any]] = []

    for layer in target_layers:
        if layer == "stage1" and not profile_bundle["has_stage1"]:
            continue
        if layer == "stage2" and not profile_bundle["has_stage2"]:
            continue
        if layer == "integrated" and not profile_bundle["has_integrated"]:
            continue
        spec = specs.get(layer) or load_spec(layer)
        results.extend(validate_layer(layer, spec, profile_bundle[layer]))

    if not results:
        payload = {
            "run_id": rid,
            "status": "NO_DATA",
            "message": "No benchmark outputs available for conformance comparison. Run Stage 1/2/Integrated benchmarks first.",
            "generated_at": datetime.utcnow().isoformat(),
        }
        _write_json(REPORTS_DIR / f"conformance_{rid}.json", payload)
        return payload

    ontology = score_ontology_integrity(results)
    calibration = build_calibration_audit(results)
    summary = _aggregate_summary(results, ontology, calibration)
    drift = analyze_drift(results, current_health={"signals": profile_bundle.get("integrated", {}).get("drift_signals")})

    report_md = render_conformance_report(results, summary, drift, calibration, ontology, run_id=rid)
    md_path = REPORTS_DIR / f"conformance_forensic_{rid}.md"
    md_path.write_text(report_md, encoding="utf-8")

    drift_md = render_drift_report(drift, summary, run_id=rid)
    drift_path = REPORTS_DIR / f"conformance_drift_{rid}.md"
    drift_path.write_text(drift_md, encoding="utf-8")

    calibration_path = REPORTS_DIR / f"calibration_audit_{rid}.md"
    calibration_path.write_text(_render_calibration_md(calibration, rid), encoding="utf-8")

    json_path = _write_json(
        EXPORTS_DIR / f"conformance_audit_{rid}.json",
        {
            "run_id": rid,
            "generated_at": datetime.utcnow().isoformat(),
            "lookback_days": lookback,
            "layers": target_layers,
            "summary": summary,
            "drift": drift,
            "calibration": calibration,
            "ontology": ontology,
            "results": results,
            "runtime_profile": {
                "stage1": profile_bundle.get("stage1"),
                "stage2": profile_bundle.get("stage2"),
                "integrated": profile_bundle.get("integrated"),
            },
        },
    )

    csv_path = _write_csv(EXPORTS_DIR / f"conformance_summary_{rid}.csv", results)

    visual_paths: list[str] = []
    if generate_visuals:
        chart = render_conformance_chart(results, VISUALS_DIR / f"conformance_drift_{rid}.png")
        if chart:
            visual_paths.append(chart)
        health = render_health_chart(summary, VISUALS_DIR / f"cognition_health_{rid}.png")
        if health:
            visual_paths.append(health)

    latest_pointer = {
        "run_id": rid,
        "generated_at": datetime.utcnow().isoformat(),
        "report_markdown": str(md_path),
        "drift_report": str(drift_path),
        "calibration_report": str(calibration_path),
        "export_json": json_path,
        "export_csv": csv_path,
        "visuals": visual_paths,
        "summary": summary,
        "drift": drift,
        "calibration": calibration,
        "ontology": ontology,
        "cognition_health": summary.get("cognition_health"),
        "health_emoji": summary.get("health_emoji"),
        "status": "OK",
    }
    _write_json(latest_pointer_path(), latest_pointer)
    _write_json(HISTORY_DIR / f"conformance_{rid}.json", latest_pointer)

    try:
        from benchmark.memory.cognition_history_store import ingest_layer

        ingest_layer("conformance", latest_pointer)
    except Exception:
        pass

    return latest_pointer


def _render_calibration_md(calibration: dict[str, Any], run_id: str) -> str:
    lines = [
        "# Calibration Audit",
        "",
        f"Run ID: `{run_id}`",
        f"Status: **{calibration.get('status')}**",
        "",
    ]
    for item in calibration.get("recommendations") or []:
        lines.extend(
            [
                f"## {item['metric']} ({item['layer']})",
                "",
                f"**{item['recommendation']}**",
                "",
                f"Evidence: {item.get('evidence', '—')}",
                "",
            ]
        )
    return "\n".join(lines)


def should_auto_run_conformance() -> bool:
    config = _conformance_config()
    auto = config.get("auto_run", {})
    if not auto.get("enabled"):
        return False

    latest_path = latest_pointer_path()
    if not latest_path.exists():
        return True

    try:
        with open(latest_path, encoding="utf-8") as handle:
            latest = json.load(handle)
        generated = datetime.fromisoformat(latest["generated_at"])
        interval = int(auto.get("interval_days", 7))
        return (datetime.utcnow() - generated).days >= interval
    except Exception:
        return True


def maybe_auto_run_conformance_backtest() -> dict[str, Any] | None:
    if not should_auto_run_conformance():
        return None
    try:
        return run_conformance_backtest()
    except Exception as error:
        return {
            "status": "ERROR",
            "message": str(error),
            "generated_at": datetime.utcnow().isoformat(),
        }
