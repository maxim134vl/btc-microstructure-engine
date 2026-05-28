"""Stage 2 reasoning benchmark orchestrator."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from benchmark.stage2.aggregator import aggregate_results
from benchmark.stage2.paths import EXPORTS_DIR, REPORTS_DIR, VISUALS_DIR, ensure_dirs, latest_pointer_path, run_id
from benchmark.stage2.reasoning_extractor import extract_reasoning_events
from benchmark.stage2.report_writer import render_forensic_report
from benchmark.stage2.synthesis_validator import FORWARD_HORIZON
from benchmark.stage2.validator import validate_reasoning_events
from benchmark.visuals.stage2_chart_renderer import render_reasoning_chart, render_stage2_summary_chart
from storage.path_registry import repo_root


def _load_config() -> dict[str, Any]:
    path = repo_root() / "benchmark" / "config.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _stage2_config() -> dict[str, Any]:
    return _load_config().get("stage2", {})


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
        "confidence_quality",
        "contradiction_level",
        "context_integrity",
        "stage2_interpretation",
        "observed_outcome",
        "move_pct",
        "confidence_score",
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
                    "confidence_quality": row.get("confidence_quality"),
                    "contradiction_level": row.get("contradiction_level"),
                    "context_integrity": row.get("context_integrity"),
                    "stage2_interpretation": row.get("stage2_interpretation"),
                    "observed_outcome": row.get("observed_outcome"),
                    "move_pct": row.get("outcome", {}).get("move_pct"),
                    "confidence_score": row.get("confidence_score"),
                }
            )
    return str(path)


def run_stage2_benchmark(
    *,
    lookback_days: int | None = None,
    forward_horizon: int | None = None,
    generate_visuals: bool = True,
    max_event_charts: int = 12,
) -> dict[str, Any]:
    """Execute Stage 2 reasoning validation benchmark."""

    ensure_dirs()
    config = _stage2_config()
    lookback = lookback_days or config.get("lookback_days", 7)
    horizon = forward_horizon or config.get("forward_horizon_candles", FORWARD_HORIZON)
    rid = run_id()

    events = extract_reasoning_events(lookback_days=lookback)
    if len(events) == 0:
        payload = {
            "run_id": rid,
            "status": "NO_DATA",
            "message": "No Stage 2 reasoning events in lookback window.",
            "generated_at": datetime.utcnow().isoformat(),
        }
        _write_json(REPORTS_DIR / f"stage2_benchmark_{rid}.json", payload)
        return payload

    results = validate_reasoning_events(events, horizon=horizon)
    summary = aggregate_results(results)

    report_md = render_forensic_report(results, summary, run_id=rid)
    md_path = REPORTS_DIR / f"stage2_forensic_{rid}.md"
    md_path.write_text(report_md, encoding="utf-8")

    json_path = _write_json(
        EXPORTS_DIR / f"stage2_benchmark_{rid}.json",
        {
            "run_id": rid,
            "generated_at": datetime.utcnow().isoformat(),
            "lookback_days": lookback,
            "forward_horizon": horizon,
            "summary": summary,
            "events": results,
        },
    )

    csv_path = _write_csv(EXPORTS_DIR / f"stage2_summary_{rid}.csv", results)

    visual_paths: list[str] = []
    if generate_visuals:
        summary_chart = render_stage2_summary_chart(results, VISUALS_DIR / f"stage2_verdicts_{rid}.png")
        if summary_chart:
            visual_paths.append(summary_chart)
        for event in results[:max_event_charts]:
            chart = render_reasoning_chart(
                event,
                output_path=VISUALS_DIR / f"stage2_event_{event.get('event_index')}_{rid}.png",
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
    _write_json(latest_pointer_path(), latest_pointer)

    try:
        from benchmark.memory.cognition_history_store import ingest_layer

        ingest_layer("stage2", latest_pointer)
    except Exception:
        pass

    return latest_pointer


def should_auto_run_stage2() -> bool:
    config = _stage2_config()
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


def maybe_auto_run_stage2_benchmark() -> dict[str, Any] | None:
    if not should_auto_run_stage2():
        return None
    try:
        return run_stage2_benchmark()
    except Exception as error:
        return {
            "status": "ERROR",
            "message": str(error),
            "generated_at": datetime.utcnow().isoformat(),
        }
