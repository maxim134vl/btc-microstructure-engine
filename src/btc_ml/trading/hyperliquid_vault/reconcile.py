"""Pair LIVE1B paper fills with Hyperliquid vault fills on manager_command_id."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from .ledger import VaultLedger, utc_now


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def load_paper_fills(paper_epoch_books: Path) -> list[dict[str, Any]]:
    return _jsonl(Path(paper_epoch_books) / "fills.jsonl")


def paper_fill_price(row: dict[str, Any]) -> float | None:
    for key in ("paper_fill_price", "gross_entry_price", "gross_exit_price", "execution_price"):
        if row.get(key) is not None:
            return float(row[key])
    return None


def paper_command_id(row: dict[str, Any]) -> str:
    return str(row.get("manager_command_id") or row.get("command_id") or "").strip()


def basis_bps(*, paper_px: float, hl_px: float) -> float:
    if paper_px == 0:
        return 0.0
    return ((hl_px - paper_px) / paper_px) * 10_000.0


def pair_fills(
    *,
    paper_fills: list[dict[str, Any]],
    hl_fills: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    paper_by_cmd: dict[str, list[dict[str, Any]]] = {}
    for row in paper_fills:
        cid = paper_command_id(row)
        if cid:
            paper_by_cmd.setdefault(cid, []).append(row)
    pairs: list[dict[str, Any]] = []
    for hl in hl_fills:
        cid = str(hl.get("manager_command_id") or "").strip()
        if not cid:
            continue
        action = str(hl.get("action") or "").upper()
        candidates = [
            row
            for row in paper_by_cmd.get(cid, [])
            if str(row.get("action") or "").upper() == action or action == ""
        ]
        paper = candidates[0] if candidates else (paper_by_cmd.get(cid) or [None])[0]
        paper_px = paper_fill_price(paper) if paper else None
        hl_px = float(hl["avg_px"]) if hl.get("avg_px") is not None else None
        row = {
            "manager_command_id": cid,
            "timeframe": hl.get("timeframe"),
            "action": action,
            "paired": paper is not None and paper_px is not None and hl_px is not None,
            "paper_px": paper_px,
            "hl_px": hl_px,
            "hl_mid": hl.get("hl_mid"),
            "quantity": hl.get("quantity"),
            "basis_bps": basis_bps(paper_px=paper_px, hl_px=hl_px) if paper_px and hl_px else None,
        }
        pairs.append(row)
    return pairs


def summarize_pairs(pairs: list[dict[str, Any]], *, attempted_commands: int | None = None) -> dict[str, Any]:
    paired = [p for p in pairs if p.get("paired")]
    basis = [float(p["basis_bps"]) for p in paired if p.get("basis_bps") is not None]
    attempted = attempted_commands if attempted_commands is not None else max(len(pairs), 1)
    fill_rate = (len(pairs) / attempted) if attempted else 0.0
    return {
        "pair_count": len(pairs),
        "paired_count": len(paired),
        "unpaired_count": len(pairs) - len(paired),
        "fill_rate": fill_rate,
        "median_basis_bps": statistics.median(basis) if basis else None,
        "median_abs_basis_bps": statistics.median([abs(x) for x in basis]) if basis else None,
        "max_abs_basis_bps": max((abs(x) for x in basis), default=None),
        "updated_at": utc_now(),
    }


def reconcile_epoch(
    *,
    ledger: VaultLedger,
    paper_epoch_books: Path,
    attempted_commands: int | None = None,
) -> dict[str, Any]:
    paper_fills = load_paper_fills(paper_epoch_books)
    hl_fills = ledger.read_all("fills")
    pairs = pair_fills(paper_fills=paper_fills, hl_fills=hl_fills)
    summary = summarize_pairs(pairs, attempted_commands=attempted_commands)
    for row in pairs:
        ledger.append("pairs", row)
    return {"summary": summary, "pairs": pairs}
