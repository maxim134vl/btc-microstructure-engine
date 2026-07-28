"""LIVE1B cutover: archive + void legacy paper + activate INTRABAR_RULES_V1 epoch."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "live"))

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.epoch import (
    activate_epoch,
    create_epoch,
    load_active_epoch,
    mark_epoch_status,
)

VOID_STATUS = "VOID_PRE_INTRABAR_RULE_CONTRACT"
VOID_REASON = (
    "entries and exits were produced under invalid "
    "closed-bar / next-completed-bar execution contract"
)
TIMEFRAMES = ("M15", "M30", "H1", "H4")
BOOK_FILES = (
    "signals.parquet",
    "orders.parquet",
    "fills.parquet",
    "trades.parquet",
    "positions.parquet",
    "equity.parquet",
    "metrics.parquet",
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_count(path: Path) -> int:
    if not path.exists():
        return 0
    if path.suffix == ".parquet":
        try:
            import pyarrow.parquet as pq

            return int(pq.ParquetFile(path).metadata.num_rows)
        except Exception:
            return 0
    if path.suffix == ".json" or path.suffix == ".jsonl":
        try:
            if path.suffix == ".jsonl":
                return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            return 1
        except Exception:
            return 0
    return 0


def archive_legacy(*, archive_root: Path) -> dict[str, Any]:
    archive_root.mkdir(parents=True, exist_ok=True)
    sources = {
        "timeframe_traders": REPO / "data" / "trading" / "timeframe_traders",
        "manager": REPO / "data" / "trading" / "manager",
        "activation": REPO / "data" / "trading" / "manager" / "activation.json",
    }
    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "void_status": VOID_STATUS,
        "void_reason": VOID_REASON,
        "files": [],
        "counts": {},
    }
    for label, src in sources.items():
        if not src.exists():
            continue
        dst = archive_root / label
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            manifest["files"].append(
                {
                    "path": str(dst.relative_to(archive_root)),
                    "sha256": _sha256(dst),
                    "rows": _row_count(dst),
                }
            )
        else:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            for f in dst.rglob("*"):
                if f.is_file():
                    rel = str(f.relative_to(archive_root))
                    rows = _row_count(f)
                    manifest["files"].append({"path": rel, "sha256": _sha256(f), "rows": rows})
                    key = f.stem
                    manifest["counts"][key] = manifest["counts"].get(key, 0) + rows
    # Summarize key tables
    summary = {
        "signals": 0,
        "orders": 0,
        "fills": 0,
        "trades": 0,
        "positions": 0,
    }
    for tf in TIMEFRAMES:
        base = archive_root / "timeframe_traders" / tf
        for name in summary:
            p = base / f"{name}.parquet"
            summary[name] += _row_count(p)
    manifest["table_row_counts"] = summary
    (archive_root / "ARCHIVE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def write_void_index(*, archive_root: Path, epochs_root: Path) -> dict[str, Any]:
    traders = REPO / "data" / "trading" / "timeframe_traders"
    voided = {
        "void_status": VOID_STATUS,
        "void_reason": VOID_REASON,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "by_timeframe": {},
        "totals": {"signals": 0, "orders": 0, "fills": 0, "trades": 0, "positions": 0, "open_positions": 0},
        "legacy_realized_pnl_excluded": True,
        "legacy_equity_excluded": True,
        "archive_path": str(archive_root),
    }
    try:
        import pandas as pd
    except ImportError:
        pd = None  # type: ignore

    for tf in TIMEFRAMES:
        tf_info: dict[str, Any] = {}
        for table in ("signals", "orders", "fills", "trades", "positions"):
            path = traders / tf / f"{table}.parquet"
            n = _row_count(path)
            tf_info[table] = n
            voided["totals"][table] = voided["totals"].get(table, 0) + n
            ids: list[str] = []
            if pd is not None and path.exists() and n:
                try:
                    df = pd.read_parquet(path)
                    id_col = {
                        "signals": "signal_id",
                        "orders": "order_id",
                        "fills": "fill_id",
                        "trades": "trade_id",
                        "positions": "position_id",
                    }[table]
                    if id_col in df.columns:
                        ids = [str(x) for x in df[id_col].tolist()]
                    if table == "positions" and "status" in df.columns:
                        open_n = int((df["status"].astype(str).str.upper() == "OPEN").sum())
                        voided["totals"]["open_positions"] += open_n
                        tf_info["open_positions"] = open_n
                except Exception as exc:
                    tf_info[f"{table}_read_error"] = str(exc)
            tf_info[f"{table}_ids_sample"] = ids[:20]
        voided["by_timeframe"][tf] = tf_info

    epochs_root.mkdir(parents=True, exist_ok=True)
    void_path = epochs_root / "legacy_void_index.json"
    void_path.write_text(json.dumps(voided, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Marker next to legacy books (no rewrite of historical values)
    marker = REPO / "data" / "trading" / "timeframe_traders" / "LEGACY_EPOCH_VOID.json"
    marker.write_text(
        json.dumps(
            {
                "status": VOID_STATUS,
                "reason": VOID_REASON,
                "void_index": str(void_path),
                "archive_path": str(archive_root),
                "excluded_from_active_metrics": True,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return voided


def stop_legacy_paper_stack() -> dict[str, Any]:
    ctl = REPO / "scripts" / "timeframe_trading_ctl.sh"
    out: dict[str, Any] = {"ctl": str(ctl), "steps": []}
    if not ctl.exists():
        out["error"] = "ctl_missing"
        return out
    for target in ("traders", "manager"):
        proc = subprocess.run(
            ["bash", str(ctl), "stop", target],
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
        out["steps"].append(
            {
                "target": target,
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "")[-2000:],
                "stderr": (proc.stderr or "")[-2000:],
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="LIVE1B legacy void + new epoch activation")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-stop", action="store_true", help="Do not stop legacy manager/traders")
    ap.add_argument("--activate-only", action="store_true", help="Assume archive/void done; only create epoch")
    args = ap.parse_args()

    cfg = load_intrabar_paper_config(repo_root=REPO)
    stamp = _utc_stamp()
    archive_root = REPO / "data" / "paper_trading" / "archive" / f"pre_intrabar_rules_{stamp}"
    result: dict[str, Any] = {
        "stamp": stamp,
        "dry_run": args.dry_run,
        "paper_only": True,
        "real_execution_enabled": False,
    }

    if not args.activate_only and not args.skip_stop:
        result["stop_legacy"] = stop_legacy_paper_stack()

    if args.dry_run:
        result["status"] = "DRY_RUN"
        print(json.dumps(result, indent=2))
        return 0

    if not args.activate_only:
        result["archive"] = archive_legacy(archive_root=archive_root)
        result["void"] = write_void_index(archive_root=archive_root, epochs_root=cfg.epochs_root)

    epoch = create_epoch(
        epochs_root=cfg.epochs_root,
        initial_equity_usd=cfg.initial_equity_usd,
        rule_contract_version=cfg.rule_contract_version,
        utc_stamp=stamp,
    )
    activate_epoch(epoch, epochs_root=cfg.epochs_root)
    # Seed empty books
    books_root = cfg.books_root / epoch.paper_epoch_id / "books"
    books_root.mkdir(parents=True, exist_ok=True)
    for name in (
        "signals",
        "commands",
        "orders",
        "fills",
        "trades",
        "positions",
        "equity_snapshots",
        "metrics",
        "blocked",
    ):
        (books_root / f"{name}.jsonl").touch(exist_ok=True)
    # Initial equity snapshot
    snap = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "equity_usd": cfg.initial_equity_usd,
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "paper_epoch_id": epoch.paper_epoch_id,
        "note": "epoch_activation_reset",
    }
    with (books_root / "equity_snapshots.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap, sort_keys=True) + "\n")

    result["epoch"] = epoch.to_dict()
    result["books_root"] = str(books_root)
    result["archive_path"] = str(archive_root)
    result["status"] = "LIVE1B_EPOCH_ACTIVATED"
    out_path = cfg.epochs_root / f"cutover_{stamp}.json"
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
