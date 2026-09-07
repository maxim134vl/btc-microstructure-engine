#!/usr/bin/env python3
"""Bootstrap an isolated VPS paper-only data root.

Never defaults to a developer live data directory.
Creates a host-parity S4.1↔LIVE1B hybrid cleanroom:
  PER_TIMEFRAME_REALIZED_EQUITY ($400k / 4×$100k sleeves) + activation.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Host hybrid capital shape (PER_TF_EQUITY_1PCT_V1_*).
SLEEVE_INITIAL_USD = 100_000.0
MASTER_INITIAL_USD = 400_000.0
HOST_HYBRID_RISK_PCT = {
    "M15": 0.5,
    "M30": 0.5,
    "H1": 1.0,
    "H4": 1.0,
}
EPOCH_PREFIX = "PER_TF_EQUITY_1PCT_V1"


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
    "trading/manager",
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
    "archive",
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


def _apply_per_tf_capital(manifest: dict) -> dict:
    """Mutate trading-contract capital to PER_TF sleeves (host hybrid shape)."""
    from btc_ml.trading.intrabar_paper.trading_contract import trading_contract_fingerprint

    capital = dict(manifest.get("capital") or {})
    capital.update(
        {
            "capital_model": "PER_TIMEFRAME_REALIZED_EQUITY",
            "master_initial_equity_usd": MASTER_INITIAL_USD,
            "timeframe_initial_equity_usd": {
                tf: SLEEVE_INITIAL_USD for tf in ("M15", "M30", "H1", "H4")
            },
            "timeframe_current_equity_source": (
                "timeframe_initial_equity_usd[tf] + cumulative_realized_net_pnl_usd[tf]"
            ),
            "risk_budget_source": "current_equity_usd[tf] * risk_pct_per_trade[tf] / 100",
            "risk_pct_per_trade": dict(HOST_HYBRID_RISK_PCT),
            "max_risk_per_trade_usd": None,
            "max_risk_per_trade_pct": None,
        }
    )
    manifest["capital"] = capital
    pos = dict(manifest.get("position_sizing") or {})
    pos["equity_basis"] = "PER_TIMEFRAME_REALIZED_EQUITY"
    pos["risk_cap_semantics"] = "PER_TIMEFRAME_CURRENT_EQUITY_PERCENT"
    pos["risk_percentage"] = None
    pos["max_risk_per_trade_pct"] = None
    pos["max_risk_per_trade_usd"] = None
    manifest["position_sizing"] = pos
    identity = dict(manifest.get("epoch_identity") or {})
    identity["initial_equity_usd"] = MASTER_INITIAL_USD
    manifest["epoch_identity"] = identity
    manifest["trading_contract_fingerprint"] = trading_contract_fingerprint(manifest)
    return manifest


def _write_hybrid_activation(manager_root: Path, *, consume_after: str) -> None:
    manager_root.mkdir(parents=True, exist_ok=True)
    path = manager_root / "activation.json"
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing.update(
        {
            "activation_timestamp": consume_after,
            "execution_enabled": False,
            "execution_owner": "LIVE1B_INTRABAR_PAPER",
            "paper_only": True,
            "d1_trader": False,
            "hybrid": {
                "enabled": True,
                "position_source": "live1b_epoch_books",
                "entry_source": "s41_command_bus",
                "consume_commands_after": consume_after,
                "cutover_at": consume_after,
                "note": "S4.1 manager commands; LIVE1B books/capital/PnL (VPS cleanroom hybrid)",
            },
            "vps_bootstrap": True,
        }
    )
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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

    from btc_ml.trading.intrabar_paper.books import EpochBooks
    from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
    from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch
    from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger
    from btc_ml.trading.intrabar_paper.trading_contract import build_trading_contract_manifest

    # Ensure data root exists and required subdirs
    data_root.mkdir(parents=True, exist_ok=True)
    for rel in REQUIRED_DIRS:
        (data_root / rel).mkdir(parents=True, exist_ok=True)

    # Never mutate the host repo data/ tree. Docker mounts the volume at
    # /app/data; host smoke/bootstrap writes only under --data-root.
    target_epochs = data_root / "trading" / "paper_epochs"
    target_books = data_root / "trading" / "intrabar_paper"
    manager_root = data_root / "trading" / "manager"

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
    consume_after = _utc()
    epoch = create_epoch(
        epochs_root=target_epochs,
        initial_equity_usd=MASTER_INITIAL_USD,
        rule_contract_version=str(cfg.rule_contract_version),
        utc_stamp=f"VPS_{stamp}",
        epoch_id_prefix=EPOCH_PREFIX,
    )
    epoch = activate_epoch(epoch, epochs_root=target_epochs)

    overlay_cfg = dict(cfg.raw)
    overlay_cfg["context_journal_root"] = "data/cognition/intrabar_context_events"
    overlay_cfg["books_root"] = "data/trading/intrabar_paper"
    overlay_cfg["epochs_root"] = "data/trading/paper_epochs"
    overlay_cfg["entry_source"] = "s41_command_bus"
    overlay_cfg["s41_consume_commands_after"] = consume_after
    overlay_cfg["initial_equity_usd"] = MASTER_INITIAL_USD
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
    manifest = _apply_per_tf_capital(manifest)
    fingerprint = manifest["trading_contract_fingerprint"]

    capital_contract = {
        "capital_model": "PER_TIMEFRAME_REALIZED_EQUITY",
        "master_initial_equity_usd": MASTER_INITIAL_USD,
        "timeframe_initial_equity_usd": {
            tf: SLEEVE_INITIAL_USD for tf in ("M15", "M30", "H1", "H4")
        },
        "risk_pct_per_trade": dict(HOST_HYBRID_RISK_PCT),
    }

    epoch_book_root = target_books / epoch.paper_epoch_id
    books_dir = epoch_book_root / "books"
    books_dir.mkdir(parents=True, exist_ok=True)
    for name in EpochBooks.TABLES:
        (books_dir / f"{name}.jsonl").touch(exist_ok=True)

    SleeveLedger.initialize(
        epoch_id=epoch.paper_epoch_id,
        epoch_root=epoch_book_root,
        initial_equity_usd=SLEEVE_INITIAL_USD,
        risk_pct_by_timeframe=HOST_HYBRID_RISK_PCT,
    )

    contract_path = target_epochs / f"{epoch.paper_epoch_id}.trading_contract.json"
    contract_payload = {
        "trading_contract_manifest": manifest,
        "trading_contract_fingerprint": fingerprint,
        "paper_epoch_id": epoch.paper_epoch_id,
        "deployment_tag": args.deployment_tag,
        "created_at": consume_after,
        "paper_only": True,
        "real_execution_enabled": False,
        "capital_contract": capital_contract,
        "paper_execution_owner": "LIVE1B_INTRABAR_PAPER",
    }
    contract_path.write_text(json.dumps(contract_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (epoch_book_root / "trading_contract.json").write_text(
        json.dumps(
            {
                "trading_contract_manifest": manifest,
                "trading_contract_fingerprint": fingerprint,
                "capital_contract": capital_contract,
                "paper_epoch_id": epoch.paper_epoch_id,
                "paper_only": True,
                "real_execution_enabled": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    active = epoch.to_dict()
    active.update(
        {
            "trading_contract_fingerprint": fingerprint,
            "parent_trading_contract_fingerprint": fingerprint,
            "deployment_tag": args.deployment_tag,
            "deployment_kind": "VPS_CLEANROOM_HYBRID",
            "paper_only": True,
            "real_execution_enabled": False,
            "execution_enabled": False,
            "paper_execution_owner": "LIVE1B_INTRABAR_PAPER",
            "capital_model": "PER_TIMEFRAME_REALIZED_EQUITY",
            "master_initial_equity_usd": MASTER_INITIAL_USD,
            "initial_equity_usd": MASTER_INITIAL_USD,
            "capital_contract": capital_contract,
            "activation_reason": "VPS_HYBRID_PER_TF_BOOTSTRAP",
        }
    )
    (target_epochs / "active.json").write_text(
        json.dumps(active, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (target_epochs / f"{epoch.paper_epoch_id}.json").write_text(
        json.dumps(active, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    _write_hybrid_activation(manager_root, consume_after=consume_after)

    meta = {
        "status": "BOOTSTRAPPED",
        "bootstrapped_at": consume_after,
        "data_root": str(data_root),
        "repo_root": str(repo_root),
        "paper_epoch_id": epoch.paper_epoch_id,
        "trading_contract_fingerprint": fingerprint,
        "capital_model": "PER_TIMEFRAME_REALIZED_EQUITY",
        "master_initial_equity_usd": MASTER_INITIAL_USD,
        "paper_only": True,
        "real_execution_enabled": False,
        "execution_enabled": False,
        "deployment_tag": args.deployment_tag,
        "hybrid": True,
        "entry_source": "s41_command_bus",
        "s41_consume_commands_after": consume_after,
        "seed_note": (
            "VPS cleanroom hybrid epoch: PER_TF_EQUITY sleeves ($400k) + "
            "activation.json (S4.1 manager → LIVE1B books). No live Mac epoch copied."
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
