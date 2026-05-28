"""Dashboard service — Stage 1 & Stage 2 cognitive validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.conformance.paths import latest_pointer_path as conformance_latest_path
from benchmark.conformance.runner import (
    maybe_auto_run_conformance_backtest,
    run_conformance_backtest,
    should_auto_run_conformance,
)
from benchmark.integrated.paths import latest_pointer_path as integrated_latest_path
from benchmark.integrated.runner import (
    maybe_auto_run_integrated_benchmark,
    run_integrated_benchmark,
    should_auto_run_integrated,
)
from benchmark.stage1.paths import REPORTS_DIR as STAGE1_REPORTS_DIR
from benchmark.stage1.runner import run_stage1_benchmark, should_auto_run as should_auto_run_stage1
from benchmark.stage2.paths import REPORTS_DIR as STAGE2_REPORTS_DIR, latest_pointer_path as stage2_latest_path
from benchmark.stage2.runner import (
    maybe_auto_run_stage2_benchmark,
    run_stage2_benchmark,
    should_auto_run_stage2,
)
from benchmark.memory.paths import DATASETS_DIR, EXPORTS_DIR, REPORTS_DIR, latest_evolution_path
from benchmark.memory.runner import (
    maybe_auto_run_evolution,
    run_full_evolution_cycle,
    run_longitudinal_evolution,
    should_auto_run_memory,
)


def _read_latest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


async def build_validation_snapshot() -> dict[str, Any]:
    stage1_latest = _read_latest(STAGE1_REPORTS_DIR / "latest.json")
    stage2_latest = _read_latest(stage2_latest_path())
    integrated_latest = _read_latest(integrated_latest_path())
    conformance_latest = _read_latest(conformance_latest_path())
    evolution = await build_evolution_snapshot()
    return {
        "framework": "cognitive_validation",
        "stage1": {
            "purpose": "Validate Stage 1 market perception — not PnL",
            "auto_run_due": should_auto_run_stage1(),
            "latest_run": stage1_latest,
            "validation_targets": [
                "market_structure",
                "initiative",
                "climax",
                "stopping",
                "effort_result",
                "auction_state",
                "state_transition",
                "mtf_alignment",
                "probabilistic",
            ],
            "verdict_types": [
                "CONFIRMED",
                "PARTIAL",
                "FAILED",
                "FALSE POSITIVE",
                "LATE DETECTION",
                "EARLY DETECTION",
            ],
        },
        "stage2": {
            "purpose": "Validate Stage 2 reasoning and synthesis — not PnL",
            "auto_run_due": should_auto_run_stage2(),
            "latest_run": stage2_latest,
            "validation_targets": [
                "reasoning_quality",
                "synthesis_correctness",
                "probabilistic_validity",
                "context_coherence",
                "regime_interpretation",
                "transition_logic",
                "narrative_continuity",
                "contradiction_handling",
                "confidence_calibration",
                "multi_signal_integration",
            ],
            "verdict_types": [
                "CONFIRMED",
                "PARTIAL",
                "FAILED",
                "OVERCONFIDENT",
                "UNDERCONFIDENT",
                "CONTRADICTORY",
                "NOISY_REASONING",
                "CONTEXT_FAILURE",
                "FALSE_NARRATIVE",
            ],
        },
        "integrated": {
            "purpose": "End-to-end cognition validation — perception → reasoning → outcome",
            "auto_run_due": should_auto_run_integrated(),
            "latest_run": integrated_latest,
            "validation_targets": [
                "stage1_correctness",
                "stage2_correctness",
                "cross_stage_consistency",
                "narrative_coherence",
                "confidence_realism",
                "contradiction_propagation",
                "perception_reasoning_alignment",
                "market_confirmation",
                "cognitive_drift",
                "ontology_integrity",
            ],
            "verdict_types": [
                "FULLY_CONFIRMED",
                "PARTIAL_CONFIRMATION",
                "PERCEPTION_FAILURE",
                "REASONING_FAILURE",
                "CONFIDENCE_FAILURE",
                "CONTRADICTION_FAILURE",
                "FALSE_NARRATIVE",
                "SYNTHESIS_COLLAPSE",
                "CONTEXT_BREAKDOWN",
                "ONTOLOGY_DRIFT",
            ],
        },
        "conformance": {
            "purpose": "Architecture conformance — expected vs observed cognition behavior",
            "auto_run_due": should_auto_run_conformance(),
            "latest_run": conformance_latest,
            "cognition_health": conformance_latest.get("cognition_health") if conformance_latest else None,
            "health_emoji": conformance_latest.get("health_emoji") if conformance_latest else None,
            "validation_targets": [
                "benchmark_spec_conformance",
                "calibration_validity",
                "ontology_integrity",
                "cognition_drift",
                "confidence_realism",
                "transition_stability",
                "contradiction_pressure",
            ],
            "verdict_types": [
                "CONFIRMED",
                "PARTIAL",
                "FAILED",
                "DRIFTING",
                "SEVERE_DRIFT",
                "ONTOLOGY_DEGRADATION",
                "CALIBRATION_COLLAPSE",
            ],
        },
        "exports": {
            "reports_dir": str(STAGE1_REPORTS_DIR.parent / "reports"),
            "exports_dir": str(STAGE1_REPORTS_DIR.parent / "exports"),
            "visuals_dir": str(STAGE1_REPORTS_DIR.parent / "visuals"),
            "conformance_reports_dir": str(conformance_latest_path().parent),
            "memory_reports_dir": str(REPORTS_DIR),
            "memory_exports_dir": str(EXPORTS_DIR),
            "memory_datasets_dir": str(DATASETS_DIR),
        },
        "evolution": evolution,
    }


async def run_validation_benchmark(**kwargs: Any) -> dict[str, Any]:
    return run_stage1_benchmark(**kwargs)


async def run_stage2_validation_benchmark(**kwargs: Any) -> dict[str, Any]:
    return run_stage2_benchmark(**kwargs)


async def run_integrated_validation_benchmark(**kwargs: Any) -> dict[str, Any]:
    return run_integrated_benchmark(**kwargs)


async def run_conformance_validation(**kwargs: Any) -> dict[str, Any]:
    return run_conformance_backtest(**kwargs)


async def get_validation_report(stage: str = "stage1") -> dict[str, Any]:
    if stage == "conformance":
        latest_path = conformance_latest_path()
    elif stage == "integrated":
        latest_path = integrated_latest_path()
    elif stage == "stage2":
        latest_path = stage2_latest_path()
    else:
        latest_path = STAGE1_REPORTS_DIR / "latest.json"
    latest = _read_latest(latest_path)
    if not latest:
        return {"status": "NO_REPORT", "markdown": None, "stage": stage}

    md_path = Path(latest.get("report_markdown", ""))
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else None
    return {
        "status": "OK",
        "stage": stage,
        "run_id": latest.get("run_id"),
        "summary": latest.get("summary"),
        "markdown": markdown,
        "paths": latest,
    }


async def generate_visual_replay(stage: str = "stage1", **kwargs: Any) -> dict[str, Any]:
    if stage == "integrated":
        return run_integrated_benchmark(generate_visuals=True, **kwargs)
    if stage == "stage2":
        return run_stage2_benchmark(generate_visuals=True, **kwargs)
    return run_stage1_benchmark(generate_visuals=True, **kwargs)


async def export_validation_package(stage: str = "stage1") -> dict[str, Any]:
    if stage == "conformance":
        latest_path = conformance_latest_path()
    elif stage == "integrated":
        latest_path = integrated_latest_path()
    elif stage == "stage2":
        latest_path = stage2_latest_path()
    else:
        latest_path = STAGE1_REPORTS_DIR / "latest.json"
    latest = _read_latest(latest_path)
    if not latest:
        return {"status": "NO_REPORT", "exports": [], "stage": stage}

    paths = {
        "report_json": latest_path,
        "forensic_markdown": Path(latest.get("report_markdown", "")),
        "drift_report": Path(latest.get("drift_report", "")),
        "calibration_report": Path(latest.get("calibration_report", "")),
        "export_json": Path(latest.get("export_json", "")),
        "export_csv": Path(latest.get("export_csv", "")),
        "visuals": [Path(path) for path in latest.get("visuals", [])],
    }
    exports = []
    for key, value in paths.items():
        if key == "visuals":
            for visual in value:
                if visual.exists():
                    exports.append({"type": "visual", "path": str(visual)})
            continue
        if isinstance(value, Path) and value.exists() and str(value):
            exports.append({"type": key, "path": str(value)})

    return {
        "status": "OK",
        "stage": stage,
        "run_id": latest.get("run_id"),
        "exports": exports,
        "directories": {
            "reports": str(conformance_latest_path().parent if stage == "conformance" else STAGE1_REPORTS_DIR),
            "exports": str(STAGE1_REPORTS_DIR.parent / "exports"),
            "visuals": str(STAGE1_REPORTS_DIR.parent / "visuals"),
            "conformance": str(conformance_latest_path().parent),
        },
    }


async def get_conformance_health() -> dict[str, Any]:
    latest = _read_latest(conformance_latest_path())
    if not latest:
        return {"status": "NO_DATA", "cognition_health": "UNKNOWN", "health_emoji": "⚪"}
    return {
        "status": "OK",
        "cognition_health": latest.get("cognition_health"),
        "health_emoji": latest.get("health_emoji"),
        "summary": latest.get("summary"),
        "drift": latest.get("drift"),
        "calibration": latest.get("calibration"),
        "run_id": latest.get("run_id"),
    }


async def compare_stage1_stage2() -> dict[str, Any]:
    stage1 = _read_latest(STAGE1_REPORTS_DIR / "latest.json")
    stage2 = _read_latest(stage2_latest_path())
    integrated = _read_latest(integrated_latest_path())
    return {
        "status": "OK",
        "stage1_summary": stage1.get("summary") if stage1 else None,
        "stage2_summary": stage2.get("summary") if stage2 else None,
        "integrated_summary": integrated.get("summary") if integrated else None,
        "stage1_run_id": stage1.get("run_id") if stage1 else None,
        "stage2_run_id": stage2.get("run_id") if stage2 else None,
        "integrated_run_id": integrated.get("run_id") if integrated else None,
        "drift": integrated.get("drift") if integrated else None,
    }


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _dataset_totals() -> dict[str, int]:
    totals: dict[str, int] = {}
    if not DATASETS_DIR.exists():
        return totals
    for bucket_dir in DATASETS_DIR.iterdir():
        if bucket_dir.is_dir():
            totals[bucket_dir.name] = _count_jsonl_lines(bucket_dir / "records.jsonl")
    return totals


def _trust_ratio_summary(latest: dict[str, Any] | None, dataset_totals: dict[str, int]) -> dict[str, Any]:
    validated = dataset_totals.get("validated_cognition", 0)
    toxic = dataset_totals.get("toxic_periods", 0)
    failed = dataset_totals.get("failed_cognition", 0)
    total = validated + toxic + failed
    trust = latest.get("trust") if latest else {}
    return {
        "current_trust_level": trust.get("trust_level"),
        "stability_score": trust.get("stability_score"),
        "overconfident_rate": trust.get("overconfident_rate"),
        "validated_records": validated,
        "toxic_records": toxic,
        "failed_records": failed,
        "stable_vs_toxic_ratio": round(validated / max(toxic, 1), 2),
        "trustworthy_share": round(validated / max(total, 1), 3) if total else None,
    }


async def build_evolution_snapshot() -> dict[str, Any]:
    latest = _read_latest(latest_evolution_path())
    dataset_totals = _dataset_totals()
    return {
        "purpose": "Longitudinal cognition memory — evolution, trust classification, ML-ready datasets",
        "auto_run_due": should_auto_run_memory(),
        "latest_run": latest,
        "history_length": latest.get("history_length") if latest else 0,
        "trust": _trust_ratio_summary(latest, dataset_totals),
        "regression": latest.get("regression") if latest else None,
        "comparison": latest.get("comparison") if latest else None,
        "evolution": latest.get("evolution") if latest else None,
        "calibration_evolution": latest.get("calibration_evolution") if latest else None,
        "ontology_evolution": latest.get("ontology_evolution") if latest else None,
        "dataset_totals": dataset_totals,
        "dataset_buckets": sorted(dataset_totals.keys()),
    }


async def run_evolution_cycle(*, full_cycle: bool = False) -> dict[str, Any]:
    if full_cycle:
        return run_full_evolution_cycle()
    return run_longitudinal_evolution()


async def get_evolution_report() -> dict[str, Any]:
    latest = _read_latest(latest_evolution_path())
    if not latest:
        return {"status": "NO_REPORT", "markdown": None}

    md_path = Path(latest.get("report_markdown", ""))
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else None
    return {
        "status": "OK",
        "run_id": latest.get("run_id"),
        "cycle_id": latest.get("cycle_id"),
        "trust": latest.get("trust"),
        "regression": latest.get("regression"),
        "evolution": latest.get("evolution"),
        "markdown": markdown,
        "paths": latest,
    }
