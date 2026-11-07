"""Shadow model orchestrator (MODEL-7) — observational, execution-incapable."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from btc_ml.model_assurance.registry import (
    read_active_runtime,
    read_candidate,
    read_candidate_status,
)
from btc_ml.model_assurance.shadow.candidate_adapter import (
    UnavailableCandidateAdapter,
    load_candidate_adapter,
)
from btc_ml.model_assurance.shadow.comparison import compare_active_shadow
from btc_ml.model_assurance.shadow.input_contract import collect_shadow_inputs
from btc_ml.model_assurance.shadow.prediction_contract import build_shadow_prediction
from btc_ml.model_assurance.toxic_box.common import (
    append_jsonl,
    atomic_write_json,
    load_json,
    read_jsonl,
    utc_now_iso,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "shadow"
    return {
        "inputs": base / "inputs" / "shadow_inputs.jsonl",
        "predictions": base / "predictions" / "shadow_predictions.jsonl",
        "comparisons": base / "comparisons" / "active_shadow_comparisons.jsonl",
        "summary": base / "snapshots" / "latest_summary.json",
        "checkpoint": base / "runtime" / "checkpoint.json",
        "health": base / "runtime" / "health.json",
        "drift_summary": root / "data" / "model_assurance" / "drift" / "snapshots" / "latest_summary.json",
        "books_root": root / "data" / "trading" / "intrabar_paper",
    }


def _persist_unique(path: Path, row: dict[str, Any], *, id_field: str, existing: set[str]) -> bool:
    rid = str(row.get(id_field) or "")
    if not rid or rid in existing:
        return False
    append_jsonl(path, row)
    existing.add(rid)
    return True


def _promotion_blockers(repo_root: Path) -> list[str]:
    blockers: list[str] = []
    drift = load_json(paths(repo_root)["drift_summary"]) or {}
    if str(drift.get("input_drift_status") or "").upper() == "CRITICAL":
        blockers.append("INPUT_DRIFT_CRITICAL")
    return blockers


def _count_paper_entities(repo_root: Path, paper_epoch_id: str | None) -> dict[str, int]:
    if not paper_epoch_id:
        return {"orders": 0, "fills": 0, "positions": 0}
    books = paths(repo_root)["books_root"] / paper_epoch_id / "books"
    out = {}
    for name in ("orders", "fills", "positions"):
        out[name] = len(read_jsonl(books / f"{name}.jsonl")) if (books / f"{name}.jsonl").exists() else 0
    return out


def build_summary(
    *,
    active: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    status: str,
    shadow_status: str,
    counts: dict[str, int],
    agreement_count: int,
    disagreement_count: int,
    last_times: dict[str, str | None],
    promotion_blockers: list[str],
    paper_entities: dict[str, int],
) -> dict[str, Any]:
    total = agreement_count + disagreement_count
    rate = (agreement_count / total) if total else None
    return {
        "status": status,
        "runtime_impact": "NONE",
        "monitoring_mode": "SHADOW_ONLY",
        "active_model_id": (active or {}).get("model_id"),
        "active_model_version": (active or {}).get("model_version"),
        "candidate_status": (
            (candidate or {}).get("record_status")
            if candidate and candidate.get("record_status") == "CANDIDATE_REGISTERED"
            else "NONE_REGISTERED"
        ),
        "candidate_model_id": (candidate or {}).get("model_id")
        if candidate and candidate.get("record_status") == "CANDIDATE_REGISTERED"
        else None,
        "candidate_model_version": (candidate or {}).get("model_version")
        if candidate and candidate.get("record_status") == "CANDIDATE_REGISTERED"
        else None,
        "shadow_status": shadow_status,
        "shadow_inputs": counts.get("inputs", 0),
        "shadow_predictions": counts.get("predictions", 0),
        "comparisons": counts.get("comparisons", 0),
        "agreement_count": agreement_count,
        "disagreement_count": disagreement_count,
        "agreement_rate": rate,
        "last_shadow_input_at": last_times.get("input"),
        "last_shadow_prediction_at": last_times.get("prediction"),
        "last_comparison_at": last_times.get("comparison"),
        "promotion_impact": "BLOCKED_UNTIL_SHADOW_EVIDENCE",
        "promotion_blockers": promotion_blockers,
        "shadow_created_orders": 0,
        "shadow_created_fills": 0,
        "shadow_created_positions": 0,
        "paper_epoch_orders": paper_entities.get("orders", 0),
        "paper_epoch_fills": paper_entities.get("fills", 0),
        "paper_epoch_positions": paper_entities.get("positions", 0),
        "updated_at": utc_now_iso(),
    }


def run_once(*, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    p = paths(root)
    active = read_active_runtime(repo_root=root)
    candidate = read_candidate(repo_root=root)
    blockers = _promotion_blockers(root)
    paper_entities = _count_paper_entities(root, (active or {}).get("paper_epoch_id"))

    if candidate is None or str(candidate.get("record_status") or "") != "CANDIDATE_REGISTERED":
        summary = build_summary(
            active=active,
            candidate=None,
            status="NO_CANDIDATE_REGISTERED",
            shadow_status="NOT_APPLICABLE_NO_CANDIDATE",
            counts={"inputs": 0, "predictions": 0, "comparisons": 0},
            agreement_count=0,
            disagreement_count=0,
            last_times={},
            promotion_blockers=blockers,
            paper_entities=paper_entities,
        )
        atomic_write_json(p["summary"], summary)
        atomic_write_json(
            p["health"],
            {
                "status": summary["status"],
                "shadow_status": summary["shadow_status"],
                "alive": True,
                "runtime_impact": "NONE",
                "monitoring_mode": "SHADOW_ONLY",
                "pid": os.getpid(),
                "promotion_blockers": blockers,
                "paper_only": (active or {}).get("paper_only", True),
                "real_execution": (active or {}).get("real_execution", False),
                "updated_at": utc_now_iso(),
            },
        )
        atomic_write_json(
            p["checkpoint"],
            {"status": summary["status"], "updated_at": utc_now_iso()},
        )
        return summary

    try:
        adapter = load_candidate_adapter(candidate)
    except RuntimeError as exc:
        status = str(exc)
        summary = build_summary(
            active=active,
            candidate=candidate,
            status=status,
            shadow_status=status,
            counts={"inputs": 0, "predictions": 0, "comparisons": 0},
            agreement_count=0,
            disagreement_count=0,
            last_times={},
            promotion_blockers=blockers,
            paper_entities=paper_entities,
        )
        atomic_write_json(p["summary"], summary)
        atomic_write_json(
            p["health"],
            {
                "status": summary["status"],
                "shadow_status": summary["shadow_status"],
                "alive": True,
                "runtime_impact": "NONE",
                "monitoring_mode": "SHADOW_ONLY",
                "pid": os.getpid(),
                "updated_at": utc_now_iso(),
            },
        )
        return summary

    if isinstance(adapter, UnavailableCandidateAdapter):
        summary = build_summary(
            active=active,
            candidate=candidate,
            status="CANDIDATE_ADAPTER_UNAVAILABLE",
            shadow_status="CANDIDATE_ADAPTER_UNAVAILABLE",
            counts={
                "inputs": len(read_jsonl(p["inputs"])),
                "predictions": len(read_jsonl(p["predictions"])),
                "comparisons": len(read_jsonl(p["comparisons"])),
            },
            agreement_count=0,
            disagreement_count=0,
            last_times={},
            promotion_blockers=blockers,
            paper_entities=paper_entities,
        )
        atomic_write_json(p["summary"], summary)
        atomic_write_json(
            p["health"],
            {
                "status": summary["status"],
                "shadow_status": summary["shadow_status"],
                "alive": True,
                "runtime_impact": "NONE",
                "monitoring_mode": "SHADOW_ONLY",
                "pid": os.getpid(),
                "updated_at": utc_now_iso(),
            },
        )
        return summary

    assert active is not None
    existing_inputs = {str(r.get("shadow_input_id")) for r in read_jsonl(p["inputs"])}
    existing_preds = {str(r.get("shadow_prediction_id")) for r in read_jsonl(p["predictions"])}
    existing_cmps = {str(r.get("comparison_id")) for r in read_jsonl(p["comparisons"])}
    seen = set(existing_inputs)

    new_inputs = collect_shadow_inputs(
        repo_root=root, active=active, candidate=candidate, seen_ids=seen
    )
    last_times: dict[str, str | None] = {
        "input": None,
        "prediction": None,
        "comparison": None,
    }
    for row in read_jsonl(p["inputs"]):
        last_times["input"] = row.get("created_at") or last_times["input"]
    for row in read_jsonl(p["predictions"]):
        last_times["prediction"] = row.get("created_at") or last_times["prediction"]
    for row in read_jsonl(p["comparisons"]):
        last_times["comparison"] = row.get("created_at") or last_times["comparison"]

    for shadow_in in new_inputs:
        if not _persist_unique(p["inputs"], shadow_in, id_field="shadow_input_id", existing=existing_inputs):
            continue
        last_times["input"] = shadow_in.get("created_at")
        result = adapter.predict(shadow_in)
        pred = build_shadow_prediction(
            active=active,
            candidate=candidate,
            shadow_input=shadow_in,
            predicted_context=str(result.get("predicted_context")),
            confidence=result.get("confidence"),
            prediction_payload=result.get("prediction_payload")
            if isinstance(result.get("prediction_payload"), dict)
            else {},
        )
        if _persist_unique(p["predictions"], pred, id_field="shadow_prediction_id", existing=existing_preds):
            last_times["prediction"] = pred.get("created_at")

        # Active context from provisional feature payload
        feat = shadow_in.get("feature_payload") if isinstance(shadow_in.get("feature_payload"), dict) else {}
        provisional = feat.get("provisional") if isinstance(feat.get("provisional"), dict) else {}
        active_ctx = provisional.get("market_context") or provisional.get("active")
        cmp = compare_active_shadow(
            active=active,
            candidate=candidate,
            timeframe=str(shadow_in.get("timeframe")),
            causal_cutoff_timestamp=shadow_in.get("causal_cutoff_timestamp"),
            causal_cutoff_monotonic_ns=shadow_in.get("causal_cutoff_monotonic_ns"),
            active_context=active_ctx,
            shadow_context=pred.get("predicted_context"),
            active_confidence=None,
            shadow_confidence=pred.get("confidence"),
            active_context_event_id=None,
            shadow_prediction_id=pred.get("shadow_prediction_id"),
        )
        if _persist_unique(p["comparisons"], cmp, id_field="comparison_id", existing=existing_cmps):
            last_times["comparison"] = cmp.get("created_at")

    inputs_n = len(read_jsonl(p["inputs"]))
    preds_n = len(read_jsonl(p["predictions"]))
    cmps = read_jsonl(p["comparisons"])
    agree = sum(1 for c in cmps if c.get("comparison_status") == "AGREE")
    disagree = sum(1 for c in cmps if c.get("comparison_status") == "DISAGREE")

    if preds_n > 0:
        status = "SHADOW_COLLECTING"
        shadow_status = "SHADOW_COLLECTING"
    else:
        status = "SHADOW_STARTING"
        shadow_status = "SHADOW_STARTING"

    summary = build_summary(
        active=active,
        candidate=candidate,
        status=status,
        shadow_status=shadow_status,
        counts={"inputs": inputs_n, "predictions": preds_n, "comparisons": len(cmps)},
        agreement_count=agree,
        disagreement_count=disagree,
        last_times=last_times,
        promotion_blockers=blockers,
        paper_entities=paper_entities,
    )
    atomic_write_json(p["summary"], summary)
    atomic_write_json(
        p["checkpoint"],
        {
            "candidate_registry_record_id": candidate.get("registry_record_id"),
            "shadow_inputs": inputs_n,
            "shadow_predictions": preds_n,
            "comparisons": len(cmps),
            "updated_at": utc_now_iso(),
        },
    )
    atomic_write_json(
        p["health"],
        {
            "status": summary["status"],
            "shadow_status": summary["shadow_status"],
            "alive": True,
            "runtime_impact": "NONE",
            "monitoring_mode": "SHADOW_ONLY",
            "pid": os.getpid(),
            "promotion_blockers": blockers,
            "paper_only": active.get("paper_only", True),
            "real_execution": active.get("real_execution", False),
            "updated_at": utc_now_iso(),
        },
    )
    return summary
