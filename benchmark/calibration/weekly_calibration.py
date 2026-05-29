"""Weekly Stage 2.5 calibration orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from benchmark.calibration.calibration_report import build_calibration_snapshot, render_calibration_markdown
from benchmark.calibration.paths import (
    EXPORTS_DIR,
    REPORTS_DIR,
    ensure_dirs,
    latest_pointer_path,
    run_id,
    weekly_history_path,
)
from benchmark.calibration.state_quality_tracker import track_state_quality


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return str(path)


def _append_weekly_history(entry: dict[str, Any]) -> None:
    ensure_dirs()
    path = weekly_history_path()
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")


def load_weekly_history(limit: int = 12) -> list[dict[str, Any]]:
    path = weekly_history_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


def should_run_weekly_calibration(interval_days: int = 7) -> bool:
    latest = _read_json(latest_pointer_path())
    if not latest:
        return True
    try:
        generated = datetime.fromisoformat(latest["generated_at"])
        return datetime.utcnow() - generated >= timedelta(days=interval_days)
    except Exception:
        return True


def run_weekly_calibration(*, force: bool = False) -> dict[str, Any]:
    """Compute Stage 2.5 calibration snapshot from benchmark + evolution + conformance."""

    ensure_dirs()
    if not force and not should_run_weekly_calibration():
        latest = _read_json(latest_pointer_path())
        return latest or {"status": "SKIPPED", "message": "Weekly calibration not due."}

    rid = run_id()
    assessment = track_state_quality()
    if assessment.get("run_count", 0) == 0:
        payload = {
            "run_id": rid,
            "status": "NO_DATA",
            "message": "No Stage 2.5 benchmark history available for calibration.",
            "generated_at": datetime.utcnow().isoformat(),
        }
        _write_json(latest_pointer_path(), payload)
        return payload

    snapshot = build_calibration_snapshot(assessment, run_id=rid)
    markdown = render_calibration_markdown(assessment, run_id=rid)

    md_path = REPORTS_DIR / f"stage2_5_calibration_{rid}.md"
    md_path.write_text(markdown, encoding="utf-8")

    export_path = _write_json(
        EXPORTS_DIR / f"stage2_5_calibration_{rid}.json",
        {
            "run_id": rid,
            "generated_at": datetime.utcnow().isoformat(),
            "assessment": assessment,
            "snapshot": snapshot,
        },
    )

    pointer = {
        "run_id": rid,
        "generated_at": datetime.utcnow().isoformat(),
        "status": "OK",
        "overall_status": snapshot.get("overall_status"),
        "overall_metrics": snapshot.get("overall_metrics"),
        "overall_trends": snapshot.get("overall_trends"),
        "states": snapshot.get("states"),
        "evolution_context": snapshot.get("evolution_context"),
        "conformance_context": snapshot.get("conformance_context"),
        "report_markdown": str(md_path),
        "export_json": export_path,
        "latest_benchmark_run_id": snapshot.get("latest_run_id"),
    }
    _write_json(latest_pointer_path(), pointer)

    _append_weekly_history(
        {
            "run_id": rid,
            "generated_at": pointer["generated_at"],
            "overall_status": pointer["overall_status"],
            "states": {
                state: block.get("status")
                for state, block in (snapshot.get("states") or {}).items()
            },
            "overall_metrics": snapshot.get("overall_metrics"),
        }
    )

    try:
        from benchmark.memory.cognition_history_store import ingest_layer

        ingest_layer(
            "stage2_5_calibration",
            {
                **pointer,
                "summary": {
                    "overall_status": pointer["overall_status"],
                    "states": snapshot.get("states"),
                    "overall_metrics": snapshot.get("overall_metrics"),
                },
            },
        )
    except Exception:
        pass

    return pointer


def build_calibration_dashboard_snapshot() -> dict[str, Any]:
    """Read-only snapshot for dashboard — runs tracker without persisting."""

    latest = _read_json(latest_pointer_path())
    assessment = track_state_quality()
    history = load_weekly_history()

    return {
        "purpose": "Track Stage 2.5 intermediate cognition calibration quality over time",
        "latest_run": latest,
        "live_assessment": build_calibration_snapshot(assessment, run_id=latest.get("run_id") if latest else "live"),
        "weekly_history": history,
        "auto_run_due": should_run_weekly_calibration(),
        "status_definitions": [
            "VERIFIED",
            "STABLE",
            "DEGRADING",
            "NEEDS_CALIBRATION",
        ],
    }


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    parser = argparse.ArgumentParser(description="Stage 2.5 weekly calibration")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_weekly_calibration(force=args.force)
    print(json.dumps(result, indent=2, default=str))
