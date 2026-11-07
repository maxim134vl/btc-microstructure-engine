#!/usr/bin/env python3
"""Bootstrap an isolated VPS paper-only data root.

Never defaults to a developer live data directory.
Uses canonical create_epoch / activate_epoch / build_trading_contract_manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


REQUIRED_DIRS = (
    "raw_market_events_v2",
    "cognition/intrabar_context_events",
    "runtime",
    "live",
    "research",
    "trading/paper_epochs",
    "trading/intrabar_paper",
    "trading/shadow_economic_correlation",
    "trading/shadow_structural_protection",
    "trading/shadow_structural_protection/stp_be33",
    "trading/shadow_auction",
    "model_assurance",
    "model_assurance/shadow",
    "model_assurance/behavioral_validation",
    "model_assurance/economic_validation",
    "model_assurance/toxic_box",
    "model_assurance/governance",
    "model_assurance/summary",
    "deployment",
)


def _refuse_live_path(data_root: Path) -> None:
    resolved = data_root.resolve()
    text = str(resolved)
    live_data = Path("/Users/fontecrypto/btc-ml/data").resolve()
    # Refuse the live Mac data tree only (not the whole repo — Docker uses /app/data).
    if text == str(live_data) or text.startswith(str(live_data) + "/"):
        raise SystemExit(
            f"REFUSED: data-root resolves to live Mac path ({resolved}). "
            "Use an isolated directory or Docker volume path."
        )
    # Also refuse bare repo root as a data root.
    repo_live = Path("/Users/fontecrypto/btc-ml").resolve()
    if text == str(repo_live):
        raise SystemExit(
            f"REFUSED: data-root is the live Mac repo root ({resolved}). "
            "Use an isolated directory or Docker volume path."
        )


def _ledger_nonempty(books_root: Path) -> list[str]:
    hits: list[str] = []
    if not books_root.exists():
        return hits
    for path in books_root.rglob("*"):
        if path.is_file() and path.stat().st_size > 0:
            if path.suffix in {".json", ".jsonl", ".parquet"} or path.name.endswith(".jsonl"):
                hits.append(str(path))
                if len(hits) >= 20:
                    break
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bootstrap VPS isolated paper environment")
    ap.add_argument("--data-root", type=Path, required=True, help="Absolute isolated data root")
    ap.add_argument(
        "--repo-root",
        type=Path,
        default=REPO,
        help="Repository root containing config/ and src/",
    )
    ap.add_argument("--allow-existing", action="store_true")
    ap.add_argument(
        "--deployment-tag",
        default="VPS_DEPLOY",
        help="Tag recorded in deployment metadata",
    )
    args = ap.parse_args(argv)

    data_root = args.data_root.expanduser().resolve()
    repo_root = args.repo_root.expanduser().resolve()
    _refuse_live_path(data_root)

    if not (repo_root / "config" / "intrabar_paper_execution.json").is_file():
        print(json.dumps({"error": "missing_config", "repo_root": str(repo_root)}))
        return 2

    sys.path.insert(0, str(repo_root / "src"))
    sys.path.insert(0, str(repo_root))

    from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
    from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch
    from btc_ml.trading.intrabar_paper.trading_contract import build_trading_contract_manifest

    # Ensure data root exists and required subdirs
    data_root.mkdir(parents=True, exist_ok=True)
    for rel in REQUIRED_DIRS:
        (data_root / rel).mkdir(parents=True, exist_ok=True)

    # Never mutate the host repo data/ tree. Docker mounts the volume at
    # /app/data; host smoke/bootstrap writes only under --data-root.
    target_epochs = data_root / "trading" / "paper_epochs"
    target_books = data_root / "trading" / "intrabar_paper"

    existing_active = target_epochs / "active.json"
    if existing_active.is_file() and not args.allow_existing:
        print(
            json.dumps(
                {
                    "error": "active_epoch_exists",
                    "path": str(existing_active),
                    "hint": "pass --allow-existing to reuse",
                }
            )
        )
        return 3

    nonempty = _ledger_nonempty(target_books)
    if nonempty and not args.allow_existing:
        print(
            json.dumps(
                {
                    "error": "non_empty_ledgers",
                    "examples": nonempty[:5],
                    "hint": "pass --allow-existing to continue",
                }
            )
        )
        return 4

    cfg = load_intrabar_paper_config(repo_root=repo_root)
    if not cfg.paper_only or cfg.real_execution_enabled:
        print(json.dumps({"error": "config_not_paper_only"}))
        return 5

    stamp = _stamp()
    epoch = create_epoch(
        epochs_root=target_epochs,
        initial_equity_usd=float(cfg.initial_equity_usd),
        rule_contract_version=str(cfg.rule_contract_version),
        utc_stamp=f"VPS_{stamp}",
    )
    epoch = activate_epoch(epoch, epochs_root=target_epochs)

    overlay_cfg = dict(cfg.raw)
    overlay_cfg["context_journal_root"] = "data/cognition/intrabar_context_events"
    overlay_cfg["books_root"] = "data/trading/intrabar_paper"
    overlay_cfg["epochs_root"] = "data/trading/paper_epochs"
    overlay_path = data_root / "deployment" / "intrabar_paper_execution.overlay.json"
    overlay_path.write_text(json.dumps(overlay_cfg, indent=2) + "\n", encoding="utf-8")

    from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config as _load

    cfg_for_manifest = _load(overlay_path, repo_root=repo_root)
    object.__setattr__(cfg_for_manifest, "epochs_root", target_epochs)
    object.__setattr__(cfg_for_manifest, "books_root", target_books)
    object.__setattr__(
        cfg_for_manifest,
        "context_journal_root",
        data_root / "cognition" / "intrabar_context_events",
    )

    manifest = build_trading_contract_manifest(
        epoch.paper_epoch_id,
        repo_root=repo_root,
        cfg=cfg_for_manifest,
        epoch=epoch,
        source_commit=os.environ.get("VPS_GIT_COMMIT"),
    )
    fingerprint = manifest["trading_contract_fingerprint"]

    contract_path = target_epochs / f"{epoch.paper_epoch_id}.trading_contract.json"
    contract_payload = {
        "trading_contract_manifest": manifest,
        "trading_contract_fingerprint": fingerprint,
        "paper_epoch_id": epoch.paper_epoch_id,
        "deployment_tag": args.deployment_tag,
        "created_at": _utc(),
        "paper_only": True,
        "real_execution_enabled": False,
    }
    contract_path.write_text(json.dumps(contract_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    epoch_book_root = target_books / epoch.paper_epoch_id
    epoch_book_root.mkdir(parents=True, exist_ok=True)
    (epoch_book_root / "trading_contract.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    active = epoch.to_dict()
    active.update(
        {
            "trading_contract_fingerprint": fingerprint,
            "parent_trading_contract_fingerprint": fingerprint,
            "deployment_tag": args.deployment_tag,
            "deployment_kind": "VPS_CLEANROOM",
            "paper_only": True,
            "real_execution_enabled": False,
            "execution_enabled": False,
        }
    )
    (target_epochs / "active.json").write_text(
        json.dumps(active, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (target_epochs / f"{epoch.paper_epoch_id}.json").write_text(
        json.dumps(active, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    meta = {
        "status": "BOOTSTRAPPED",
        "bootstrapped_at": _utc(),
        "data_root": str(data_root),
        "repo_root": str(repo_root),
        "paper_epoch_id": epoch.paper_epoch_id,
        "trading_contract_fingerprint": fingerprint,
        "paper_only": True,
        "real_execution_enabled": False,
        "execution_enabled": False,
        "deployment_tag": args.deployment_tag,
        "seed_note": (
            "New VPS cleanroom epoch via create_epoch/activate_epoch + "
            "build_trading_contract_manifest. No live Mac epoch copied."
        ),
    }
    (data_root / "deployment" / "bootstrap.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    events = data_root / "cognition" / "intrabar_context_events" / "events.jsonl"
    if not events.exists():
        events.write_text("", encoding="utf-8")

    print(json.dumps(meta, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
