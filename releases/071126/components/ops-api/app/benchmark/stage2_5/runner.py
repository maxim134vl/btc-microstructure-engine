"""Stage 2.5 intermediate cognition validation orchestrator."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from benchmark.stage2_5.aggregator import aggregate_results
from benchmark.stage2_5.event_extractor import extract_intermediate_events
from benchmark.stage2_5.paths import EXPORTS_DIR, REPORTS_DIR, VISUALS_DIR, ensure_dirs, latest_pointer_path, run_id
from benchmark.stage2_5.report_writer import render_forensic_report
from benchmark.stage2_5.verdict_engine import validate_intermediate_events
from benchmark.visuals.stage2_5_chart_renderer import render_intermediate_event_chart, render_stage2_5_summary_chart
from storage.path_registry import repo_root


def _load_config() -> dict[str, Any]:
    path = repo_root() / "benchmark" / "config.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _stage2_5_config() -> dict[str, Any]:
    return _load_config().get("stage2_5", {})


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
        "intermediate_state",
        "verdict",
        "false_positive",
        "early_warning",
        "confirmation_horizon",
        "anchor_stage2_state",
        "confidence",
        "severity",
        "observed_outcome",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in results:
            ctx = row.get("context") or {}
            writer.writerow(
                {
                    "event_index": row.get("event_index"),
                    "timestamp": row.get("timestamp"),
                    "intermediate_state": row.get("intermediate_state"),
                    "verdict": row.get("verdict"),
                    "false_positive": row.get("false_positive"),
                    "early_warning": row.get("early_warning"),
                    "confirmation_horizon": row.get("confirmation_horizon"),
                    "anchor_stage2_state": ctx.get("anchor_stage2_state"),
                    "confidence": ctx.get("confidence"),
                    "severity": ctx.get("severity"),
                    "observed_outcome": row.get("observed_outcome"),
                }
            )
    return str(path)


def run_stage2_5_benchmark(
    *,
    lookback_days: int | None = None,
    start: str | None = None,
    end: str | None = None,
    generate_visuals: bool = True,
    max_event_charts: int = 12,
) -> dict[str, Any]:
    """Execute Stage 2.5 intermediate cognition validation benchmark."""

    ensure_dirs()
    config = _stage2_5_config()
    lookback = lookback_days if lookback_days is not None else config.get("lookback_days", 7)
    rid = run_id()

    use_period = start is not None or end is not None
    events = extract_intermediate_events(
        lookback_days=None if use_period else lookback,
        start=start,
        end=end,
    )

    if len(events) == 0:
        payload = {
            "run_id": rid,
            "status": "NO_DATA",
            "message": "No Stage 2.5 intermediate cognition events in validation window.",
            "generated_at": datetime.utcnow().isoformat(),
            "period": {"start": start, "end": end} if use_period else {"lookback_days": lookback},
        }
        _write_json(REPORTS_DIR / f"stage2_5_benchmark_{rid}.json", payload)
        return payload

    results = validate_intermediate_events(events)
    summary = aggregate_results(results)
    period = {"start": start, "end": end} if use_period else {"lookback_days": lookback}

    report_md = render_forensic_report(results, summary, run_id=rid, period=period)
    md_path = REPORTS_DIR / f"stage2_5_forensic_{rid}.md"
    md_path.write_text(report_md, encoding="utf-8")

    json_path = _write_json(
        EXPORTS_DIR / f"stage2_5_benchmark_{rid}.json",
        {
            "run_id": rid,
            "generated_at": datetime.utcnow().isoformat(),
            "period": period,
            "validation_horizons": [4, 8, 16],
            "summary": summary,
            "events": results,
        },
    )

    csv_path = _write_csv(EXPORTS_DIR / f"stage2_5_summary_{rid}.csv", results)

    visual_paths: list[str] = []
    if generate_visuals:
        summary_chart = render_stage2_5_summary_chart(results, VISUALS_DIR / f"stage2_5_verdicts_{rid}.png")
        if summary_chart:
            visual_paths.append(summary_chart)
        for event in results[:max_event_charts]:
            chart = render_intermediate_event_chart(
                event,
                output_path=VISUALS_DIR / f"stage2_5_event_{event.get('event_index')}_{rid}.png",
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
        "period": period,
        "status": "OK",
    }
    _write_json(latest_pointer_path(), latest_pointer)

    try:
        from benchmark.memory.cognition_history_store import ingest_layer

        ingest_layer("stage2_5", latest_pointer)
    except Exception:
        pass

    return latest_pointer


def compare_stage2_5_vs_outcome() -> dict[str, Any]:
    """Compare latest Stage 2.5 validation against forward market outcomes."""

    latest_path = latest_pointer_path()
    if not latest_path.exists():
        return {"status": "NO_REPORT", "comparisons": []}

    with open(latest_path, encoding="utf-8") as handle:
        latest = json.load(handle)

    export_path = Path(latest.get("export_json", ""))
    if not export_path.exists():
        return {"status": "NO_EXPORT", "comparisons": []}

    with open(export_path, encoding="utf-8") as handle:
        payload = json.load(handle)

    events = payload.get("events") or []
    summary = payload.get("summary") or {}
    comparisons = []
    for event in events:
        comparisons.append(
            {
                "timestamp": event.get("timestamp"),
                "intermediate_state": event.get("intermediate_state"),
                "interpretation": event.get("interpretation"),
                "observed_outcome": event.get("observed_outcome"),
                "verdict": event.get("verdict"),
                "confirmation_horizon": event.get("confirmation_horizon"),
            }
        )

    return {
        "status": "OK",
        "run_id": latest.get("run_id"),
        "summary": summary,
        "comparisons": comparisons,
        "narrative_confirmation_rate": summary.get("narrative_confirmation_rate"),
        "by_state": summary.get("by_state"),
    }


def should_auto_run_stage2_5() -> bool:
    config = _stage2_5_config()
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


def maybe_auto_run_stage2_5_benchmark() -> dict[str, Any] | None:
    if not should_auto_run_stage2_5():
        return None
    try:
        return run_stage2_5_benchmark()
    except Exception as error:
        return {
            "status": "ERROR",
            "message": str(error),
            "generated_at": datetime.utcnow().isoformat(),
        }


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    parser = argparse.ArgumentParser(description="Stage 2.5 intermediate cognition benchmark")
    parser.add_argument("--start", default="2026-05-21")
    parser.add_argument("--end", default="2026-05-28 23:59:59")
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--no-visuals", action="store_true")
    args = parser.parse_args()

    if args.lookback_days is not None:
        result = run_stage2_5_benchmark(lookback_days=args.lookback_days, generate_visuals=not args.no_visuals)
    else:
        result = run_stage2_5_benchmark(
            start=args.start,
            end=args.end,
            generate_visuals=not args.no_visuals,
        )
    print(json.dumps(result, indent=2, default=str))
