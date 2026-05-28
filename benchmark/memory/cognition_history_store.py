"""Persistent storage for all benchmark cognition runs."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmark.memory.paths import CYCLES_DIR, ensure_dirs, index_path, run_id


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def _load_index() -> dict[str, Any]:
    ensure_dirs()
    data = _read_json(index_path())
    if not data:
        return {"cycles": [], "layers": {}, "updated_at": None}
    return data


def _save_index(index: dict[str, Any]) -> None:
    index["updated_at"] = datetime.utcnow().isoformat()
    _write_json(index_path(), index)


def ingest_layer(layer: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist an immutable layer snapshot and update the memory index."""

    ensure_dirs()
    if payload.get("status") not in ("OK",):
        return {"layer": layer, "stored": False, "reason": payload.get("status")}

    rid = payload.get("run_id") or run_id()
    entry = {
        "layer": layer,
        "run_id": rid,
        "generated_at": payload.get("generated_at") or datetime.utcnow().isoformat(),
        "summary": payload.get("summary"),
        "drift": payload.get("drift"),
        "calibration": payload.get("calibration"),
        "ontology": payload.get("ontology"),
        "cognition_health": payload.get("cognition_health"),
        "export_json": payload.get("export_json"),
        "report_markdown": payload.get("report_markdown"),
        "event_count": (payload.get("summary") or {}).get("event_count", 0),
    }

    layer_path = CYCLES_DIR / f"{layer}_{rid}.json"
    _write_json(layer_path, {"entry": entry, "payload": payload})

    index = _load_index()
    index["layers"][layer] = {
        "run_id": rid,
        "generated_at": entry["generated_at"],
        "path": str(layer_path),
    }
    _save_index(index)
    return {"layer": layer, "stored": True, "run_id": rid, "path": str(layer_path)}


def build_cycle_record(*, cycle_id: str | None = None) -> dict[str, Any]:
    """Merge latest layer snapshots into a unified cognition cycle."""

    from benchmark.conformance.paths import latest_pointer_path as conformance_latest
    from benchmark.integrated.paths import latest_pointer_path as integrated_latest
    from benchmark.stage1.paths import REPORTS_DIR as stage1_reports
    from benchmark.stage2.paths import latest_pointer_path as stage2_latest

    sources = {
        "stage1": stage1_reports / "latest.json",
        "stage2": stage2_latest(),
        "integrated": integrated_latest(),
        "conformance": conformance_latest(),
    }

    cid = cycle_id or run_id()
    layers: dict[str, Any] = {}
    for layer, path in sources.items():
        data = _read_json(path)
        if data:
            layers[layer] = data

    record = {
        "cycle_id": cid,
        "generated_at": datetime.utcnow().isoformat(),
        "layers": layers,
        "layer_count": len(layers),
    }

    cycle_path = CYCLES_DIR / f"cycle_{cid}.json"
    _write_json(cycle_path, record)

    index = _load_index()
    index["cycles"].append(
        {
            "cycle_id": cid,
            "generated_at": record["generated_at"],
            "path": str(cycle_path),
            "layer_count": len(layers),
        }
    )
    index["cycles"] = index["cycles"][-120:]
    _save_index(index)
    return record


def load_cycle_history(limit: int = 52) -> list[dict[str, Any]]:
    index = _load_index()
    cycles = index.get("cycles") or []
    history: list[dict[str, Any]] = []
    for meta in reversed(cycles[-limit:]):
        data = _read_json(Path(meta["path"]))
        if data:
            history.append(data)
    history.reverse()
    return history


def load_layer_events(export_path: str | None) -> list[dict[str, Any]]:
    if not export_path:
        return []
    path = Path(export_path)
    if not path.exists():
        return []
    payload = _read_json(path) or {}
    return payload.get("events") or payload.get("chains") or payload.get("results") or []
