"""Longitudinal cognition memory orchestrator."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from benchmark.memory.calibration_evolution import record_calibration_evolution
from benchmark.memory.cognition_history_store import build_cycle_record, ingest_layer, load_cycle_history
from benchmark.memory.evolution_tracker import build_evolution_timeline
from benchmark.memory.longitudinal_comparator import compare_longitudinal
from benchmark.memory.ontology_evolution import record_ontology_evolution
from benchmark.memory.paths import EXPORTS_DIR, REPORTS_DIR, ensure_dirs, latest_evolution_path, run_id
from benchmark.memory.regression_detector import detect_regressions
from benchmark.memory.toxic_data_separator import separate_cycle_datasets
from benchmark.memory.trust_classifier import classify_cycle_trust
from storage.path_registry import repo_root


def _load_config() -> dict[str, Any]:
    path = repo_root() / "benchmark" / "config.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _memory_config() -> dict[str, Any]:
    return _load_config().get("memory", {})


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return str(path)


def ingest_all_layers() -> dict[str, Any]:
    """Ingest latest benchmark outputs from all layers into memory."""

    from benchmark.conformance.paths import latest_pointer_path as conformance_latest
    from benchmark.integrated.paths import latest_pointer_path as integrated_latest
    from benchmark.stage1.paths import REPORTS_DIR as stage1_reports
    from benchmark.stage2.paths import latest_pointer_path as stage2_latest

    results = {}
    for layer, path in {
        "stage1": stage1_reports / "latest.json",
        "stage2": stage2_latest(),
        "integrated": integrated_latest(),
        "conformance": conformance_latest(),
    }.items():
        if path.exists():
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            results[layer] = ingest_layer(layer, payload)
    return results


def run_longitudinal_evolution(*, cycle_id: str | None = None) -> dict[str, Any]:
    """Build cognition cycle, compare history, update datasets, generate evolution report."""

    ensure_dirs()
    rid = cycle_id or run_id()

    ingest_all_layers()
    current = build_cycle_record(cycle_id=rid)
    history = load_cycle_history()
    trust = classify_cycle_trust(current)
    comparison = compare_longitudinal(current, history)
    regression = detect_regressions(comparison, trust)
    evolution = build_evolution_timeline(history)
    dataset_counts = separate_cycle_datasets(current, trust)
    calibration = record_calibration_evolution(current, comparison, regression)
    ontology = record_ontology_evolution(current, comparison)

    if regression.get("events"):
        regression_path = EXPORTS_DIR / "regression_history.jsonl"
        with open(regression_path, "a", encoding="utf-8") as handle:
            for event in regression["events"]:
                handle.write(
                    json.dumps({"cycle_id": rid, "generated_at": current["generated_at"], **event}, default=str)
                    + "\n"
                )

    report_md = _render_evolution_report(
        current, trust, comparison, regression, evolution, calibration, ontology, dataset_counts, rid
    )
    md_path = REPORTS_DIR / f"evolution_{rid}.md"
    md_path.write_text(report_md, encoding="utf-8")

    payload = {
        "run_id": rid,
        "cycle_id": current.get("cycle_id"),
        "generated_at": datetime.utcnow().isoformat(),
        "status": "OK",
        "trust": trust,
        "comparison": comparison,
        "regression": regression,
        "evolution": evolution,
        "calibration_evolution": calibration,
        "ontology_evolution": ontology,
        "dataset_counts": dataset_counts,
        "report_markdown": str(md_path),
        "history_length": len(history),
    }

    export_path = _write_json(EXPORTS_DIR / f"evolution_{rid}.json", payload)
    payload["export_json"] = export_path
    _write_json(latest_evolution_path(), payload)
    return payload


def _render_evolution_report(
    cycle: dict[str, Any],
    trust: dict[str, Any],
    comparison: dict[str, Any],
    regression: dict[str, Any],
    evolution: dict[str, Any],
    calibration: dict[str, Any],
    ontology: dict[str, Any],
    dataset_counts: dict[str, int],
    run_id: str,
) -> str:
    lines = [
        "# Cognition Evolution Report",
        "",
        f"Run ID: `{run_id}`",
        f"Cycle ID: `{cycle.get('cycle_id')}`",
        "",
        "## Trust Classification",
        "",
        f"- Level: **{trust.get('trust_level')}**",
        f"- Stability: **{trust.get('stability_score', 0):.1%}**",
        f"- Overconfident rate: **{trust.get('overconfident_rate', 0):.1%}**",
        "",
        "## Longitudinal Comparison",
        "",
        f"- History length: **{comparison.get('history_length', 0)}** cycles",
        f"- Previous cycle: `{comparison.get('previous_cycle_id', 'none')}`",
        f"- Status: **{comparison.get('status')}**",
        "",
    ]

    for row in comparison.get("comparisons") or []:
        delta = row.get("delta_vs_previous")
        delta_text = f"{delta:+.1%}" if delta is not None else "—"
        lines.append(
            f"- **{row['label']}**: {row.get('current', 0):.1%} "
            f"(Δ prev {delta_text}, trend {row.get('trend')})"
        )

    lines.extend(
        [
            "",
            "## Regression Detection",
            "",
            f"- Verdict: **{regression.get('verdict')}**",
            f"- Improvements: {regression.get('improvement_count', 0)}",
            f"- Regressions: {regression.get('regression_count', 0)}",
            "",
        ]
    )
    for event in regression.get("events") or []:
        lines.append(f"- [{event['type']}] {event.get('note')}")

    lines.extend(["", "## Evolution Trends", ""])
    for alias, trend in (evolution.get("trends") or {}).items():
        lines.append(f"- {alias}: {trend}")

    lines.extend(
        [
            "",
            "## Calibration Evolution",
            "",
            calibration.get("note", "—"),
            "",
            "## Ontology Evolution",
            "",
            ontology.get("signal", "—"),
            "",
            "## Dataset Separation",
            "",
        ]
    )
    for bucket, count in sorted(dataset_counts.items()):
        lines.append(f"- {bucket}: {count} records appended")

    return "\n".join(lines)


def should_auto_run_memory() -> bool:
    config = _memory_config()
    auto = config.get("auto_run", {})
    if not auto.get("enabled"):
        return False

    latest = latest_evolution_path()
    if not latest.exists():
        return True

    try:
        with open(latest, encoding="utf-8") as handle:
            data = json.load(handle)
        generated = datetime.fromisoformat(data["generated_at"])
        interval = int(auto.get("interval_days", 7))
        return (datetime.utcnow() - generated).days >= interval
    except Exception:
        return True


def maybe_auto_run_evolution() -> dict[str, Any] | None:
    if not should_auto_run_memory():
        return None
    try:
        return run_full_evolution_cycle()
    except Exception as error:
        return {"status": "ERROR", "message": str(error), "generated_at": datetime.utcnow().isoformat()}


def run_full_evolution_cycle(**kwargs: Any) -> dict[str, Any]:
    """Run benchmarks + integrated + conformance + longitudinal memory update."""

    from benchmark.conformance.runner import run_conformance_backtest
    from benchmark.integrated.runner import run_integrated_benchmark
    from benchmark.stage1.runner import run_stage1_benchmark
    from benchmark.stage2.runner import run_stage2_benchmark

    results = {
        "stage1": run_stage1_benchmark(generate_visuals=False),
        "stage2": run_stage2_benchmark(generate_visuals=False),
        "integrated": run_integrated_benchmark(generate_visuals=False),
        "conformance": run_conformance_backtest(generate_visuals=False),
    }
    evolution = run_longitudinal_evolution(**kwargs)
    evolution["benchmark_runs"] = {k: v.get("status") for k, v in results.items()}
    _write_json(latest_evolution_path(), evolution)
    return evolution
