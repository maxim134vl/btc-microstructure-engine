#!/usr/bin/env python3
"""CLI for governance decisions (MODEL-8) — never switches active model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.model_assurance.governance import ledger  # noqa: E402
from btc_ml.model_assurance.governance.evidence import (  # noqa: E402
    build_promotion_evidence_snapshot,
    load_governance_config,
)
from btc_ml.model_assurance.governance.monitor import paths  # noqa: E402
from btc_ml.model_assurance.governance.promotion_gate import (  # noqa: E402
    build_evaluation_record,
    evaluate_promotion_eligibility,
)
from btc_ml.model_assurance.toxic_box.common import load_json, read_jsonl  # noqa: E402


def _print(payload: dict) -> int:
    print(json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str))
    return 0


def _latest_evaluation(p: dict[str, Path], evaluation_id: str) -> dict | None:
    rows = [r for r in read_jsonl(p["evaluations"]) if str(r.get("evaluation_id")) == str(evaluation_id)]
    return rows[-1] if rows else None


def cmd_status(_: argparse.Namespace) -> int:
    p = paths(ROOT)
    gate = load_json(p["latest_gate"]) or {}
    return _print(
        {
            "status": gate.get("status"),
            "eligibility_status": gate.get("eligibility_status"),
            "governance_status": gate.get("governance_status"),
            "candidate_status": gate.get("candidate_status"),
            "blockers": gate.get("blockers"),
            "environment_blockers": gate.get("environment_blockers"),
            "evaluation_id": gate.get("evaluation_id"),
            "evidence_hash": gate.get("evidence_hash"),
            "active_decision_id": gate.get("active_decision_id"),
            "promotion_execution_status": gate.get("promotion_execution_status"),
            "active_model_change_performed": gate.get("active_model_change_performed"),
        }
    )


def cmd_approve(args: argparse.Namespace) -> int:
    p = paths(ROOT)
    evidence = build_promotion_evidence_snapshot(repo_root=ROOT)
    config = load_governance_config(ROOT)
    eligibility = evaluate_promotion_eligibility(evidence=evidence, config=config)
    evaluation = _latest_evaluation(p, args.evaluation_id) or build_evaluation_record(
        evidence=evidence, eligibility=eligibility
    )
    try:
        row = ledger.approve(
            decisions_path=p["decisions"],
            evaluation=evaluation,
            evidence=evidence,
            actor_id=args.actor,
            reason=args.reason,
            expected_evaluation_id=args.evaluation_id,
        )
    except ValueError as exc:
        return _print({"status": str(exc), "decision": None})
    return _print({"status": "APPROVED", "decision": row, "active_model_change_performed": False})


def cmd_reject(args: argparse.Namespace) -> int:
    p = paths(ROOT)
    evidence = build_promotion_evidence_snapshot(repo_root=ROOT)
    config = load_governance_config(ROOT)
    eligibility = evaluate_promotion_eligibility(evidence=evidence, config=config)
    evaluation = _latest_evaluation(p, args.evaluation_id) or build_evaluation_record(
        evidence=evidence, eligibility=eligibility
    )
    try:
        row = ledger.reject(
            decisions_path=p["decisions"],
            evaluation=evaluation,
            evidence=evidence,
            actor_id=args.actor,
            reason=args.reason,
            expected_evaluation_id=args.evaluation_id,
        )
    except ValueError as exc:
        return _print({"status": str(exc), "decision": None})
    return _print({"status": "REJECTED", "decision": row, "active_model_change_performed": False})


def cmd_revoke(args: argparse.Namespace) -> int:
    p = paths(ROOT)
    evidence = build_promotion_evidence_snapshot(repo_root=ROOT)
    config = load_governance_config(ROOT)
    eligibility = evaluate_promotion_eligibility(evidence=evidence, config=config)
    evaluation = build_evaluation_record(evidence=evidence, eligibility=eligibility)
    try:
        row = ledger.revoke(
            decisions_path=p["decisions"],
            evaluation=evaluation,
            evidence=evidence,
            actor_id=args.actor,
            reason=args.reason,
            decision_id=args.decision_id,
        )
    except ValueError as exc:
        return _print({"status": str(exc), "decision": None})
    return _print({"status": "REVOKED", "decision": row, "active_model_change_performed": False})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Model Assurance governance decisions")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)

    p_ap = sub.add_parser("approve")
    p_ap.add_argument("--evaluation-id", required=True)
    p_ap.add_argument("--actor", required=True)
    p_ap.add_argument("--reason", required=True)
    p_ap.set_defaults(func=cmd_approve)

    p_rj = sub.add_parser("reject")
    p_rj.add_argument("--evaluation-id", required=True)
    p_rj.add_argument("--actor", required=True)
    p_rj.add_argument("--reason", required=True)
    p_rj.set_defaults(func=cmd_reject)

    p_rv = sub.add_parser("revoke")
    p_rv.add_argument("--decision-id", required=True)
    p_rv.add_argument("--actor", required=True)
    p_rv.add_argument("--reason", required=True)
    p_rv.set_defaults(func=cmd_revoke)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
