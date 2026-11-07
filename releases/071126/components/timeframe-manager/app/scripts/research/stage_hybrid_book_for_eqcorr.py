#!/usr/bin/env python3
"""Stage the canonical Hybrid tick book into an EQCORR paper-repo layout on market time.

Why this exists
---------------
The Hybrid replay compresses ~2.6 years of market into a few wall-clock hours, so
every LIVE1B book field that records "when this happened" holds the moment the
replay ran, not the moment the market moved. Policy decisions survive that (they
read open-position state in processing order, and the book is written in market
chronological order), but EQCORR's CausalFeatureEnricher does as-of joins against
the cognition planes on the candidate timestamp. Fed wall-clock stamps it would
match the newest row of every plane for all 6172 candidates — look-ahead by
construction, and the enricher's own lookahead_detected counter would fire.

So: copy the books, replace wall-clock stamps with the row's market timestamp, and
symlink the pack cognition planes in. Nothing is written back to the source epoch.

Wall-clock detection is by value, not by a hardcoded field list: the book's market
span ends 2026-07-24 while the replay ran later, so any timestamp at or after the
run start is unambiguously a wall-clock artifact.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.shadow_lab import default_pack_dir  # noqa: E402

DEFAULT_ARCHIVE = Path("/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive")
STAGE_ROOT = ROOT / "data/research/external_traders/etll_hybrid_eqcorr"

TABLES = ("signals", "commands", "orders", "fills", "positions", "trades")
MARKET_TS_FIELD = "context_occurrence_timestamp"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return len(rows)


def _is_wall_clock(value: Any, cutoff: pd.Timestamp) -> bool:
    if not isinstance(value, str) or len(value) < 20 or "T" not in value:
        return False
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp >= cutoff


def _position_market_times(
    positions: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    """(entry_by_position, exit_by_position) market timestamps.

    trades.jsonl carries entry_ts=None and orders.jsonl carries no market stamp at
    all, so for those tables the market moment only exists on the position rows:
    the OPEN record for entries, the CLOSED record for exits.
    """
    entry: dict[str, str] = {}
    exit_: dict[str, str] = {}
    for row in positions:
        pid = str(row.get("position_id") or "")
        stamp = row.get(MARKET_TS_FIELD)
        if not pid or not isinstance(stamp, str):
            continue
        if str(row.get("status") or "").upper() == "OPEN":
            entry.setdefault(pid, stamp)
        else:
            exit_.setdefault(pid, stamp)
    return entry, exit_


def stage(
    *,
    epoch_id: str,
    archive_root: Path,
    fresh: bool = True,
) -> dict[str, Any]:
    src_books = archive_root / epoch_id / "books"
    if not src_books.exists():
        raise FileNotFoundError(src_books)

    paper_repo = STAGE_ROOT / "paper_repo"
    dest_books = paper_repo / "data" / "trading" / "intrabar_paper" / epoch_id / "books"
    if fresh and STAGE_ROOT.exists():
        shutil.rmtree(STAGE_ROOT)
    dest_books.mkdir(parents=True, exist_ok=True)

    positions = _read_jsonl(src_books / "positions.jsonl")
    entry_times, exit_times = _position_market_times(positions)

    # EXIT orders carry only command_id (no position_id), so the position-keyed maps
    # above cannot reach them. Fills cover both legs and always carry a market stamp.
    by_command: dict[str, str] = {}
    by_order: dict[str, str] = {}
    for row in _read_jsonl(src_books / "fills.jsonl"):
        stamp = row.get(MARKET_TS_FIELD)
        if not isinstance(stamp, str):
            continue
        cid = str(row.get("command_id") or "")
        oid = str(row.get("order_id") or "")
        if cid:
            by_command.setdefault(cid, stamp)
        if oid:
            by_order.setdefault(oid, stamp)

    # The run started after the market span ended, so this cleanly separates the
    # two clocks without having to enumerate field names per table.
    stamps = [
        pd.Timestamp(r[MARKET_TS_FIELD])
        for r in positions
        if isinstance(r.get(MARKET_TS_FIELD), str)
    ]
    market_end = max(stamps)
    cutoff = market_end + pd.Timedelta(days=1)

    summary: dict[str, Any] = {
        "epoch_id": epoch_id,
        "source": str(src_books),
        "paper_repo": str(paper_repo),
        "market_end": str(market_end),
        "wall_clock_cutoff": str(cutoff),
        "tables": {},
    }

    for table in TABLES:
        rows = _read_jsonl(src_books / f"{table}.jsonl")
        rewritten = 0
        dropped_no_market_ts = 0
        out_rows: list[dict[str, Any]] = []
        for row in rows:
            market = row.get(MARKET_TS_FIELD)
            if not isinstance(market, str):
                # No market stamp on the row itself (orders): recover it through the
                # position it belongs to, keyed by whether this is the entry or exit
                # leg. Keeping the wall-clock value would reintroduce the leak, and
                # dropping the row would silently truncate the table.
                pid = str(row.get("position_id") or "")
                action = str(row.get("action") or "").upper()
                market = (exit_times if action == "EXIT" else entry_times).get(pid)
                if not isinstance(market, str):
                    market = by_command.get(str(row.get("command_id") or "")) or by_order.get(
                        str(row.get("order_id") or "")
                    )
            if not isinstance(market, str):
                dropped_no_market_ts += 1
                continue
            new_row = dict(row)
            # Make every staged row self-describing on the market clock, including
            # the ones whose stamp had to be recovered through the position.
            new_row[MARKET_TS_FIELD] = market
            for key, value in row.items():
                if key == MARKET_TS_FIELD:
                    continue
                if _is_wall_clock(value, cutoff):
                    new_row[key] = market
                    rewritten += 1
            if table == "trades":
                pid = str(row.get("position_id") or "")
                if not new_row.get("entry_ts") and pid in entry_times:
                    new_row["entry_ts"] = entry_times[pid]
                if not new_row.get("exit_ts"):
                    new_row["exit_ts"] = market
            out_rows.append(new_row)
        n = _write_jsonl(dest_books / f"{table}.jsonl", out_rows)
        summary["tables"][table] = {
            "rows": n,
            "timestamps_rewritten": rewritten,
            "dropped_without_market_ts": dropped_no_market_ts,
        }

    # Cognition planes for the causal enricher. These are the research packs, which
    # cover the full book span; the production paths cover only mid-2026.
    cognition = paper_repo / "data" / "cognition"
    cognition.mkdir(parents=True, exist_ok=True)
    ctx = default_pack_dir("M15") / "context"
    volume_src = ctx / "volume_response_state.parquet"
    if not volume_src.exists():
        volume_src = ctx / "volume_response_state_proxy.parquet"
    mapping = {
        "candle_structure_memory.parquet": ctx / "candle_structure_memory.parquet",
        "volume_response_state.parquet": volume_src,
        "volume_classification_memory.parquet": ctx / "volume_classification_memory.parquet",
        "runtime_cognition_memory.parquet": ctx / "cognitive_market_state_memory.parquet",
        "multi_timeframe_synthesis.parquet": ctx / "final_market_context_memory.parquet",
    }
    linked: dict[str, str] = {}
    for name, src in mapping.items():
        if not src.exists():
            continue
        dest = cognition / name
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        dest.symlink_to(src.resolve())
        linked[name] = str(src)
    summary["cognition_linked"] = linked
    (paper_repo / "data" / "runtime").mkdir(parents=True, exist_ok=True)

    # The engine resolves execution config relative to its repo root. Copy rather
    # than symlink so the run stays pinned to the config as it was at stage time.
    cfg_dir = paper_repo / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in ("intrabar_paper_execution.json", "intrabar_supervision.json"):
        src = ROOT / "config" / name
        if src.exists():
            shutil.copy2(src, cfg_dir / name)
            copied.append(name)
    summary["config_copied"] = copied
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epoch-id", default="ETLL_HYBRID_TICK_V1_20260905_092610")
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--no-fresh", action="store_true")
    args = parser.parse_args()
    out = stage(
        epoch_id=args.epoch_id,
        archive_root=args.archive_root,
        fresh=not args.no_fresh,
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
