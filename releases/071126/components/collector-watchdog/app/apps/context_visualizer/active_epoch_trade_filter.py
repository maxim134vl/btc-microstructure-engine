"""Active paper-epoch filter for chart/trade overlays (LIVE1B.2).

Canonical rule for active chart trade overlays:
  paper_epoch_id == active_paper_epoch_id
  AND status != VOID_PRE_INTRABAR_RULE_CONTRACT

Missing paper_epoch_id ⇒ exclude from active view (never include).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_EPOCH_PATH = ROOT / "data" / "trading" / "paper_epochs" / "active.json"
VOID_STATUS = "VOID_PRE_INTRABAR_RULE_CONTRACT"


def load_active_paper_epoch() -> dict[str, Any] | None:
    if not ACTIVE_EPOCH_PATH.exists():
        return None
    try:
        payload = json.loads(ACTIVE_EPOCH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("epoch_status") or "").upper() != "ACTIVE":
        return None
    if not str(payload.get("rule_contract_version") or "").startswith("INTRABAR_RULES"):
        return None
    return payload


def active_paper_epoch_id() -> str | None:
    epoch = load_active_paper_epoch()
    if not epoch:
        return None
    eid = str(epoch.get("paper_epoch_id") or "").strip()
    return eid or None


def live1b_paper_active() -> bool:
    return active_paper_epoch_id() is not None


def is_active_epoch_trade_row(row: dict[str, Any] | None, *, active_epoch_id: str | None = None) -> bool:
    """Return True only when the row belongs to the active paper epoch."""
    if not isinstance(row, dict):
        return False
    eid = active_epoch_id if active_epoch_id is not None else active_paper_epoch_id()
    if not eid:
        # No active LIVE1B epoch → do not apply this gate (legacy S4 path).
        return True
    row_epoch = str(row.get("paper_epoch_id") or "").strip()
    if not row_epoch:
        return False
    if row_epoch != eid:
        return False
    status = str(row.get("status") or row.get("void_status") or "").upper()
    if status == VOID_STATUS or status.startswith("VOID_"):
        return False
    return True


def filter_active_epoch_rows(
    rows: list[dict[str, Any]] | None,
    *,
    active_epoch_id: str | None = None,
) -> list[dict[str, Any]]:
    eid = active_epoch_id if active_epoch_id is not None else active_paper_epoch_id()
    if not eid:
        return list(rows or [])
    return [r for r in (rows or []) if is_active_epoch_trade_row(r, active_epoch_id=eid)]


def empty_trade_overlay_payload(*, active_epoch_id: str | None = None) -> dict[str, Any]:
    eid = active_epoch_id if active_epoch_id is not None else active_paper_epoch_id()
    return {
        "active_paper_epoch_id": eid,
        "trade_overlay_source": "LIVE1B_INTRABAR_PAPER_EPOCH",
        "legacy_excluded": True,
        "entries": [],
        "exits": [],
        "trade_shapes": [],
        "closed_trades": [],
        "open_positions": [],
        "restated_trades": [],
        "superseded_paper_trades": [],
        "counts": {
            "entry_markers": 0,
            "exit_markers": 0,
            "closed_trade_overlays": 0,
            "open_position_overlays": 0,
            "trade_shapes": 0,
            "trade_marker_count": 0,
            "open_position_overlay_count": 0,
            "closed_trade_overlay_count": 0,
            "visible_stop_loss_line_count": 0,
            "visible_take_profit_line_count": 0,
        },
    }
