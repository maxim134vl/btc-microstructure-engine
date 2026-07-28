#!/usr/bin/env python3
"""CLI: register / status / show-active for Model Assurance registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from btc_ml.model_assurance.registry import (  # noqa: E402
    read_active_runtime,
    read_registry_status,
    register_active_runtime,
)


def _print(payload: dict) -> int:
    print(json.dumps(payload, sort_keys=True, ensure_ascii=True))
    return 0


def cmd_register(_: argparse.Namespace) -> int:
    result = register_active_runtime(repo_root=ROOT)
    active = result.get("active_model") or {}
    out = {
        "status": result.get("status"),
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "paper_epoch_id": active.get("paper_epoch_id"),
        "source_commit": active.get("source_commit"),
        "runtime_fingerprint": active.get("runtime_fingerprint"),
        "registry_record_id": result.get("registry_record_id"),
    }
    if result.get("status") == "VERSION_CONFLICT":
        out["existing_fingerprint"] = result.get("existing_fingerprint")
        out["conflicting_fingerprint"] = result.get("conflicting_fingerprint")
    return _print(out)


def cmd_status(_: argparse.Namespace) -> int:
    return _print(read_registry_status(repo_root=ROOT))


def cmd_show_active(_: argparse.Namespace) -> int:
    active = read_active_runtime(repo_root=ROOT)
    if active is None:
        return _print({"status": "NONE_REGISTERED", "active_model": None})
    return _print(
        {
            "status": active.get("record_status"),
            "model_id": active.get("model_id"),
            "model_version": active.get("model_version"),
            "paper_epoch_id": active.get("paper_epoch_id"),
            "source_commit": active.get("source_commit"),
            "runtime_fingerprint": active.get("runtime_fingerprint"),
            "registry_record_id": active.get("registry_record_id"),
            "paper_only": active.get("paper_only"),
            "real_execution": active.get("real_execution"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Model Assurance active runtime registry")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("register").set_defaults(func=cmd_register)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("show-active").set_defaults(func=cmd_show_active)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
