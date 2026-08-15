"""S4.1 fill pricing aligned to LIVE1B execution contract.

LIVE1B rules (source of truth):
  - ENTRY/EXIT fill at execution-time BBO via fill_price_for
    LONG ENTRY=ask, SHORT ENTRY=bid; EXIT opposite
  - opened_at / fill timestamp = execution wall-clock now
  - context_origin_price / context_event_price = provenance only (never fill)
  - never wait for the next completed candle close

S4.1 previously used first M15 bar close strictly after the command
(live_market_feed_completed_bar_close). That path is replaced here.

Note: live book_ticker is read from raw_market_events_v2 parquet batches
(~60s file cadence), so the freshness gate is wider than LIVE1B's in-process
websocket ``max_bbo_age_ms=2000``. Policy (ask/bid + immediate execution clock)
still matches LIVE1B.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
BOOK_TICKER_ROOT = ROOT / "data" / "raw_market_events_v2" / "book_ticker"
# File-backed book_ticker batches ~60s; keep headroom above one batch gap.
DEFAULT_MAX_BBO_AGE_MS = 120_000.0


@dataclass(frozen=True)
class CausalBBO:
    book_update_id: str | None
    best_bid: float
    best_ask: float
    receive_timestamp: str | None
    receive_monotonic_ns: int
    source_event_id: str | None = None


def fill_price_for(*, side: str, action: str, bbo: CausalBBO) -> float:
    """Same policy as LIVE1B ``intrabar_paper.bbo.fill_price_for``."""
    side_u = str(side).upper()
    act = str(action).upper()
    if act == "ENTRY":
        return bbo.best_ask if side_u == "LONG" else bbo.best_bid
    if act == "EXIT":
        return bbo.best_bid if side_u == "LONG" else bbo.best_ask
    raise ValueError(f"unknown action {action}")


@dataclass(frozen=True)
class Live1bStyleFill:
    available: bool
    price: float | None
    timestamp: str | None
    best_bid: float | None
    best_ask: float | None
    book_update_id: str | None
    bbo_receive_timestamp: str | None
    bbo_age_ms: float | None
    reason: str | None
    source: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _latest_book_ticker_file(root: Path = BOOK_TICKER_ROOT) -> Path | None:
    if not root.exists():
        return None
    files = sorted(root.rglob("book_ticker__*.parquet"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def load_latest_execution_bbo(
    *,
    root: Path = BOOK_TICKER_ROOT,
    now: datetime | None = None,
    max_age_ms: float = DEFAULT_MAX_BBO_AGE_MS,
) -> tuple[CausalBBO | None, float | None, str | None]:
    """Load the freshest book_ticker quote for paper fill."""
    path = _latest_book_ticker_file(root)
    if path is None:
        return None, None, "ENTRY_BLOCKED_NO_CAUSAL_BBO"
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return None, None, "ENTRY_BLOCKED_NO_CAUSAL_BBO"
    if frame is None or not len(frame):
        return None, None, "ENTRY_BLOCKED_NO_CAUSAL_BBO"
    row = frame.iloc[-1]
    try:
        bid = float(row["best_bid_price"])
        ask = float(row["best_ask_price"])
    except Exception:
        return None, None, "ENTRY_BLOCKED_NO_CAUSAL_BBO"
    if bid <= 0 or ask <= 0 or ask < bid:
        return None, None, "ENTRY_BLOCKED_NO_CAUSAL_BBO"
    recv_raw = row.get("local_receive_timestamp")
    try:
        recv_ts = pd.Timestamp(recv_raw, tz="UTC")
    except Exception:
        return None, None, "ENTRY_BLOCKED_NO_CAUSAL_BBO"
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    age_ms = (clock - recv_ts.to_pydatetime()).total_seconds() * 1000.0
    if age_ms < 0:
        age_ms = 0.0
    if age_ms > float(max_age_ms):
        return None, age_ms, "ENTRY_BLOCKED_STALE_BBO"
    mono = row.get("local_receive_monotonic_ns")
    try:
        mono_i = int(mono) if mono is not None and str(mono) not in {"", "nan", "NaT"} else 0
    except Exception:
        mono_i = 0
    update_id = row.get("update_id")
    bbo = CausalBBO(
        book_update_id=None if update_id is None else str(update_id),
        best_bid=bid,
        best_ask=ask,
        receive_timestamp=str(recv_raw),
        receive_monotonic_ns=mono_i,
        source_event_id=path.name,
    )
    return bbo, age_ms, None


def resolve_live1b_style_fill(
    *,
    side: str,
    action: str,
    max_age_ms: float = DEFAULT_MAX_BBO_AGE_MS,
    book_ticker_root: Path = BOOK_TICKER_ROOT,
    now: datetime | None = None,
) -> Live1bStyleFill:
    """Immediate LIVE1B-style BBO fill; never next-candle close."""
    bbo, age_ms, reason = load_latest_execution_bbo(
        root=book_ticker_root, now=now, max_age_ms=max_age_ms
    )
    if bbo is None:
        return Live1bStyleFill(
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            age_ms,
            reason or "ENTRY_BLOCKED_NO_CAUSAL_BBO",
            "execution_market_bbo",
        )
    price = float(fill_price_for(side=side, action=action, bbo=bbo))
    return Live1bStyleFill(
        True,
        price,
        _utc_now(),
        float(bbo.best_bid),
        float(bbo.best_ask),
        bbo.book_update_id,
        bbo.receive_timestamp,
        age_ms,
        None,
        "execution_market_bbo",
    )


def context_provenance(command: dict[str, Any] | None) -> dict[str, Any]:
    """Attach context occurrence fields for audit; never use as fill."""
    cmd = command or {}
    return {
        "context_origin_price": cmd.get("context_origin_price"),
        "context_entered_at": cmd.get("context_started_at") or cmd.get("context_entered_at"),
        "context_reference_price": cmd.get("context_origin_price"),
        "context_reference_timestamp": cmd.get("context_started_at") or cmd.get("source_event_timestamp"),
    }
