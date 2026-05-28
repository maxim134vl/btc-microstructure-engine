"""Integrated cognition benchmark orchestrator."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from benchmark.integrated.aggregator import aggregate_results, analyze_cognition_drift
from benchmark.integrated.chain_validator import validate_integrated_chains
from benchmark.integrated.cognition_chain_builder import build_cognition_chains
from benchmark.integrated.forensic_integrator import render_integrated_report
from benchmark.integrated.outcome_validator import FORWARD_HORIZON
from benchmark.integrated.paths import EXPORTS_DIR, REPORTS_DIR, VISUALS_DIR, ensure_dirs, latest_pointer_path, run_id
from benchmark.visuals.integrated_chart_renderer import render_integrated_chart, render_integrated_summary_chart
from storage.path_registry import repo_root


def _load_config() -> dict[str, Any]:
    path = repo_root() / "benchmark" / "config.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _integrated_config() -> dict[str, Any]:
    return _load_config().get("integrated", {})


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return str(path)


def _write_csv(path: Path, results: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "event_index",
        "timestamp",
        "integrated_verdict",
        "stage1_verdict",
        "stage2_verdict",
        "root_cause",
        "failure_pattern",
        "confidence_realism",
        "alignment_level",
        "contradiction_propagation",
        "observed_outcome",
        "move_pct",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    "event_index": row.get("event_index"),
                    "timestamp": row.get("timestamp"),
                    "integrated_verdict": row.get("integrated_verdict"),
                    "stage1_verdict": row.get("stage1_verdict"),
                    "stage2_verdict": row.get("stage2_verdict"),
                    "root_cause": row.get("root_cause"),
                    "failure_pattern": row.get("failure_pattern"),
                    "confidence_realism": row.get("confidence_realism"),
                    "alignment_level": row.get("alignment_level"),
                    "contradiction_propagation": row.get("contradiction_propagation"),
                    "observed_outcome": row.get("observed_outcome"),
                    "move_pct": row.get("outcome", {}).get("move_pct"),
                }
            )
    return str(path)


def run_integrated_benchmark(
    *,
    lookback_days: int | None = None,
    forward_horizon: int | None = None,
    generate_visuals: bool = True,
    max_event_charts: int = 12,
) -> dict[str, Any]:
    ensure_dirs()
    config = _integrated_config()
    lookback = lookback_days or config.get("lookback_days", 7)
    horizon = forward_horizon or config.get("forward_horizon_candles", FORWARD_HORIZON)
    rid = run_id()

    chains = build_cognition_chains(lookback_days=lookback)
    if not chains:
        payload = {
            "run_id": rid,
            "status": "NO_DATA",
            "message": "No integrated cognition chains in lookback window.",
            "generated_at": datetime.utcnow().isoformat(),
        }
        _write_json(REPORTS_DIR / f"integrated_benchmark_{rid}.json", payload)
        return payload

    results = validate_integrated_chains(chains, horizon=horizon)
    summary = aggregate_results(results)
    drift = analyze_cognition_drift(results)

    report_md = render_integrated_report(results, summary, drift, run_id=rid)
    md_path = REPORTS_DIR / f"integrated_forensic_{rid}.md"
    md_path.write_text(report_md, encoding="utf-8")

    drift_path = REPORTS_DIR / f"cognition_drift_{rid}.md"
    drift_path.write_text(_render_drift_report(drift, summary, rid), encoding="utf-8")

    json_path = _write_json(
        EXPORTS_DIR / f"integrated_benchmark_{rid}.json",
        {
            "run_id": rid,
            "generated_at": datetime.utcnow().isoformat(),
            "lookback_days": lookback,
            "forward_horizon": horizon,
            "summary": summary,
            "drift": drift,
            "chains": results,
        },
    )

    csv_path = _write_csv(EXPORTS_DIR / f"integrated_summary_{rid}.csv", results)

    visual_paths: list[str] = []
    if generate_visuals:
        summary_chart = render_integrated_summary_chart(results, VISUALS_DIR / f"integrated_verdicts_{rid}.png")
        if summary_chart:
            visual_paths.append(summary_chart)
        for event in results[:max_event_charts]:
            chart = render_integrated_chart(
                event,
                output_path=VISUALS_DIR / f"integrated_event_{event.get('event_index')}_{rid}.png",
            )
            if chart:
                visual_paths.append(chart)

    latest_pointer = {
        "run_id": rid,
        "generated_at": datetime.utcnow().isoformat(),
        "report_markdown": str(md_path),
        "drift_report": str(drift_path),
        "export_json": json_path,
        "export_csv": csv_path,
        "visuals": visual_paths,
        "summary": summary,
        "drift": drift,
        "status": "OK",
    }
    _write_json(latest_pointer_path(), latest_pointer)

    try:
        from benchmark.memory.cognition_history_store import ingest_layer

        ingest_layer("integrated", latest_pointer)
    except Exception:
        pass

    return latest_pointer


def _render_drift_report(drift: dict[str, Any], summary: dict[str, Any], run_id: str) -> str:
    lines = [
        "# Cognition Drift Analysis",
        "",
        f"Run ID: `{run_id}`",
        "",
        f"Health: **{drift.get('health', 'UNKNOWN')}**",
        "",
        "## Signals",
        "",
    ]
    for signal in drift.get("signals", []):
        lines.append(f"- {signal}")
    if not drift.get("signals"):
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Rates",
            "",
            f"- Overconfident: {drift.get('overconfident_rate', 0):.1%}",
            f"- Contradiction: {drift.get('contradiction_rate', 0):.1%}",
            f"- Misalignment: {drift.get('misalignment_rate', 0):.1%}",
            f"- Perception failure: {drift.get('perception_failure_rate', 0):.1%}",
            f"- Reasoning failure: {drift.get('reasoning_failure_rate', 0):.1%}",
            f"- Cognition drift frequency: {summary.get('cognition_drift_frequency', 0):.1%}",
            "",
        ]
    )
    return "\n".join(lines)


def should_auto_run_integrated() -> bool:
    config = _integrated_config()
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


def maybe_auto_run_integrated_benchmark() -> dict[str, Any] | None:
    if not should_auto_run_integrated():
        return None
    try:
        return run_integrated_benchmark()
    except Exception as error:
        return {
            "status": "ERROR",
            "message": str(error),
            "generated_at": datetime.utcnow().isoformat(),
        }
