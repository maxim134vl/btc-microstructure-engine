"""Stage 1 benchmark orchestrator."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from benchmark.stage1.aggregator import aggregate_results
from benchmark.stage1.event_extractor import extract_cognition_events
from benchmark.stage1.forward_validator import FORWARD_HORIZON, validate_events
from benchmark.stage1.paths import EXPORTS_DIR, REPORTS_DIR, VISUALS_DIR, ensure_dirs, run_id
from benchmark.stage1.report_writer import render_forensic_report
from benchmark.visuals.chart_renderer import render_event_chart, render_summary_chart
from storage.path_registry import repo_root


def _load_config() -> dict[str, Any]:
    path = repo_root() / "benchmark" / "config.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


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
        "verdict",
        "false_positive",
        "interpretation",
        "observed_outcome",
        "bias_label",
        "move_pct",
        "follow_through",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    "event_index": row.get("event_index"),
                    "timestamp": row.get("timestamp"),
                    "verdict": row.get("verdict"),
                    "false_positive": row.get("false_positive"),
                    "interpretation": row.get("interpretation"),
                    "observed_outcome": row.get("observed_outcome"),
                    "bias_label": row.get("bias_label"),
                    "move_pct": row.get("outcome", {}).get("move_pct"),
                    "follow_through": row.get("outcome", {}).get("follow_through"),
                }
            )
    return str(path)


def run_stage1_benchmark(
    *,
    lookback_days: int | None = None,
    forward_horizon: int | None = None,
    generate_visuals: bool = True,
    max_event_charts: int = 12,
) -> dict[str, Any]:
    """Execute full Stage 1 cognitive validation benchmark."""

    ensure_dirs()
    config = _load_config()
    lookback = lookback_days or config.get("lookback_days", 7)
    horizon = forward_horizon or config.get("forward_horizon_candles", FORWARD_HORIZON)
    rid = run_id()

    events = extract_cognition_events(lookback_days=lookback)
    if len(events) == 0:
        payload = {
            "run_id": rid,
            "status": "NO_DATA",
            "message": "No Stage 1 cognition events in lookback window.",
            "generated_at": datetime.utcnow().isoformat(),
        }
        _write_json(REPORTS_DIR / f"stage1_benchmark_{rid}.json", payload)
        return payload

    results = validate_events(events, horizon=horizon)
    summary = aggregate_results(results)

    report_md = render_forensic_report(results, summary, run_id=rid)
    md_path = REPORTS_DIR / f"stage1_forensic_{rid}.md"
    md_path.write_text(report_md, encoding="utf-8")

    json_path = _write_json(
        EXPORTS_DIR / f"stage1_benchmark_{rid}.json",
        {
            "run_id": rid,
            "generated_at": datetime.utcnow().isoformat(),
            "lookback_days": lookback,
            "forward_horizon": horizon,
            "summary": summary,
            "events": results,
        },
    )

    csv_path = _write_csv(EXPORTS_DIR / f"stage1_summary_{rid}.csv", results)

    visual_paths: list[str] = []
    if generate_visuals:
        summary_chart = render_summary_chart(results, VISUALS_DIR / f"verdicts_{rid}.png")
        if summary_chart:
            visual_paths.append(summary_chart)
        for event in results[:max_event_charts]:
            chart = render_event_chart(
                event,
                output_path=VISUALS_DIR / f"event_{event.get('event_index')}_{rid}.png",
            )
            if chart:
                visual_paths.append(chart)

    latest_pointer = {
        "run_id": rid,
        "generated_at": datetime.utcnow().isoformat(),
        "report_markdown": str(md_path),
        "export_json": json_path,
        "export_csv": csv_path,
        "visuals": visual_paths,
        "summary": summary,
        "status": "OK",
    }
    _write_json(REPORTS_DIR / "latest.json", latest_pointer)

    try:
        from benchmark.memory.cognition_history_store import ingest_layer

        ingest_layer("stage1", latest_pointer)
    except Exception:
        pass

    return latest_pointer


def maybe_auto_run_benchmark() -> dict[str, Any] | None:
    """Run benchmark when auto_run interval elapsed (non-blocking caller expected)."""

    if not should_auto_run():
        return None
    try:
        return run_stage1_benchmark()
    except Exception as error:
        return {
            "status": "ERROR",
            "message": str(error),
            "generated_at": datetime.utcnow().isoformat(),
        }


def should_auto_run() -> bool:
    config = _load_config()
    auto = config.get("auto_run", {})
    if not auto.get("enabled"):
        return False

    latest_path = REPORTS_DIR / "latest.json"
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
