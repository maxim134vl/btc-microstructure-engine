#!/usr/bin/env python3
"""Sync live Hybrid tick books → MaksTiger durable archive (incremental + final).

Use while a Hybrid oneshot is already running (in-memory code may not have
Tiger archive yet). Safe to leave running until process exits.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = ROOT / "data/research/external_traders/etll_hybrid_tick"
DEFAULT_DURABLE = Path("/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive")


def _latest_epoch_books() -> tuple[str, Path] | None:
    root = SANDBOX / "data" / "trading" / "intrabar_paper"
    if not root.exists():
        return None
    epochs = sorted(
        [p for p in root.glob("ETLL_HYBRID_TICK_V1_*") if (p / "books").exists()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not epochs:
        return None
    ep = epochs[0]
    return ep.name, ep / "books"


def _sync_once(*, durable_root: Path) -> dict:
    found = _latest_epoch_books()
    if not found:
        return {"status": "NO_EPOCH"}
    epoch_id, books_src = found
    dest = durable_root / epoch_id
    dest.mkdir(parents=True, exist_ok=True)
    dest_books = dest / "books"
    dest_books.mkdir(parents=True, exist_ok=True)
    # Incremental copy of jsonl books (overwrite growing files)
    copied = []
    for src in books_src.iterdir():
        if src.is_file():
            shutil.copy2(src, dest_books / src.name)
            copied.append(src.name)
    # Also pull lived_replay artefacts if present
    lived = SANDBOX / "lived_replay"
    for name in ("lived_trades.parquet", "manager_commands.parquet", "lived_replay_summary.json"):
        src = lived / name
        if src.exists():
            shutil.copy2(src, dest / name)
    summary = SANDBOX / "summary.json"
    if summary.exists():
        shutil.copy2(summary, dest / "summary.json")
    n_trades = 0
    tj = dest_books / "trades.jsonl"
    if tj.exists():
        with tj.open("r", encoding="utf-8") as fh:
            n_trades = sum(1 for line in fh if line.strip())
    (dest / "SYNC_NOTE.txt").write_text(
        f"synced_at={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"paper_epoch_id={epoch_id}\n"
        f"books_src={books_src}\n"
        f"trades={n_trades}\n"
        f"files={copied}\n",
        encoding="utf-8",
    )
    # local mirror too
    local = SANDBOX / "archive" / epoch_id
    local.mkdir(parents=True, exist_ok=True)
    local_books = local / "books"
    if local_books.exists():
        shutil.rmtree(local_books)
    shutil.copytree(dest_books, local_books)
    return {
        "status": "SYNCED",
        "epoch_id": epoch_id,
        "durable": str(dest),
        "trades": n_trades,
        "files": copied,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--durable-root", type=Path, default=DEFAULT_DURABLE)
    ap.add_argument("--interval-s", type=int, default=300)
    ap.add_argument("--once", action="store_true")
    ap.add_argument(
        "--until-hybrid-exits",
        action="store_true",
        help="Keep syncing while run_etll_hybrid_tick_lived_replay.py is alive",
    )
    args = ap.parse_args()

    def hybrid_alive() -> bool:
        import subprocess

        r = subprocess.run(
            ["pgrep", "-f", "run_etll_hybrid_tick_lived_replay.py"],
            capture_output=True,
            text=True,
        )
        return r.returncode == 0 and bool(r.stdout.strip())

    if args.once:
        print(json.dumps(_sync_once(durable_root=args.durable_root), indent=2))
        return 0

    last = None
    while True:
        info = _sync_once(durable_root=args.durable_root)
        if info != last:
            print(json.dumps(info), flush=True)
            last = info
        if args.until_hybrid_exits and not hybrid_alive():
            # final sync after exit
            info = _sync_once(durable_root=args.durable_root)
            print(json.dumps({"final": True, **info}), flush=True)
            break
        if not args.until_hybrid_exits and args.once:
            break
        time.sleep(max(30, int(args.interval_s)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
