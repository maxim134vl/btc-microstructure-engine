#!/usr/bin/env python3
"""CLI for Model Assurance candidate registry (MODEL-7)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.model_assurance.registry import (  # noqa: E402
    read_candidate,
    read_candidate_status,
    register_candidate,
    retire_candidate,
)


def _print(payload: dict) -> int:
    print(json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    return _print(read_candidate_status(repo_root=ROOT))


def cmd_show(_: argparse.Namespace) -> int:
    cand = read_candidate(repo_root=ROOT)
    if cand is None or str(cand.get("record_status") or "") != "CANDIDATE_REGISTERED":
        return _print({"status": "NONE_REGISTERED", "candidate": None})
    return _print(
        {
            "status": cand.get("record_status"),
            "model_id": cand.get("model_id"),
            "model_version": cand.get("model_version"),
            "model_role": cand.get("model_role"),
            "execution_capability": cand.get("execution_capability"),
            "execution_enabled": cand.get("execution_enabled"),
            "prediction_only": cand.get("prediction_only"),
            "shadow_only": cand.get("shadow_only"),
            "registry_record_id": cand.get("registry_record_id"),
            "runtime_fingerprint": cand.get("runtime_fingerprint"),
        }
    )


def cmd_register(args: argparse.Namespace) -> int:
    result = register_candidate(config_path=args.config, repo_root=ROOT)
    cand = result.get("candidate") or {}
    return _print(
        {
            "status": result.get("status"),
            "model_id": cand.get("model_id"),
            "model_version": cand.get("model_version"),
            "execution_capability": cand.get("execution_capability"),
            "registry_record_id": result.get("registry_record_id"),
        }
    )


def cmd_retire(args: argparse.Namespace) -> int:
    result = retire_candidate(reason=args.reason, repo_root=ROOT)
    return _print(
        {
            "status": result.get("status"),
            "reason": args.reason,
            "registry_record_id": (result.get("candidate") or {}).get("registry_record_id"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Model Assurance candidate registry")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("show").set_defaults(func=cmd_show)
    p_reg = sub.add_parser("register")
    p_reg.add_argument("--config", required=True, help="Path to candidate descriptor JSON")
    p_reg.set_defaults(func=cmd_register)
    p_ret = sub.add_parser("retire")
    p_ret.add_argument("--reason", required=True)
    p_ret.set_defaults(func=cmd_retire)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
