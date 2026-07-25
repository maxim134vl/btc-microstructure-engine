"""Patch 4.3 §8/§9 — canonical read-only visual trade view.

One deterministic history for the trade chart:

    archived legacy closed controller trades (before the S4 activation boundary)
    + timeframe trader trades (after the boundary)

The view never recomputes trade economics. Gross P&L, fees, slippage and net
P&L are copied from the settled ledger row, so the chart shows exactly what the
canonical books recorded (``canonical_paper_trade_economics_v1``).

Legacy rows keep ``timeframe = LEGACY_GLOBAL`` and a null manager command: the
pre-S4 global book has no proven per-timeframe lineage and must not be
retro-labelled.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

CANONICAL_VISUAL_TRADE_SCHEMA_VERSION = "canonical_visual_trade_view_v1"
ECONOMICS_VERSION = "CANONICAL_PAPER_TRADE_ECONOMICS_V1"
LEGACY_TIMEFRAME = "LEGACY_GLOBAL"
ASSET = "BTCUSDT"

S4_TIMEFRAMES = ("M15", "M30", "H1", "H4")
S4_ACTIVATION_PATH = ROOT / "data/trading/manager/activation.json"
LEGACY_MIGRATION_PATH = ROOT / "data/trading/manager/legacy_migration.json"
TRADER_BOOKS_ROOT = ROOT / "data/trading/timeframe_traders"
LIFECYCLE_MEMORY = ROOT / "data/cognition/market_context_lifecycle_memory.parquet"

PRODUCTION_VIEW_PARQUET = (
    ROOT / "data/research/paper_simulator/canonical_visual_trade_view.parquet"
)

# The legacy global book mixes controller-managed positions with one-shot manual
# probes. Only controller positions are canonical trade history; the one-shot
# rows were already excluded from render before S4.1 and stay excluded.
LEGACY_CONTROLLER_MARKER = "_CTRL_"
LEGACY_ONE_SHOT_MARKER = "_ONE_SHOT_"

VIEW_COLUMNS = [
    # §9 canonical contract
    "visual_trade_id",
    "source_trade_id",
    "source_book",
    "source_schema_version",
    "asset",
    "timeframe",
    "side",
    "entry_timestamp",
    "exit_timestamp",
    "entry_price",
    "exit_price",
    "quantity",
    "gross_pnl",
    "fees_paid",
    "slippage_paid",
    "net_pnl",
    "context_episode_id",
    "lifecycle_episode_id",
    "manager_command_id",
    "position_id",
    "economics_version",
    "lineage_status",
    "activation_epoch",
    # render-compatible aliases consumed by the visual refresher
    "trade_id",
    "context_id",
    "entry_ts",
    "exit_ts",
    "stop_loss_price",
    "take_profit_price",
    "notional_usd",
    "position_notional_usd",
    "gross_pnl_usd",
    "fees_usd",
    "slippage_usd",
    "net_pnl_usd",
    "r_multiple",
    "entry_price_source",
    "exit_price_source",
    "exit_reason",
    "context_quality_label",
    "paper_entry_basis",
    "paper_only",
    "execution_enabled",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def activation_boundary() -> str | None:
    """UTC timestamp separating the legacy book from the timeframe books."""
    payload = _read_json(S4_ACTIVATION_PATH) or {}
    value = payload.get("activation_timestamp")
    return str(value) if value else None


def legacy_archive_dir() -> Path | None:
    payload = _read_json(LEGACY_MIGRATION_PATH) or {}
    rel = payload.get("archive_dir")
    if not rel:
        return None
    path = ROOT / str(rel)
    return path if path.exists() else None


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return None if out != out else out


def _txt(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "<na>"}:
        return None
    return text


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        stamp = pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return None
    if stamp is None or pd.isna(stamp):
        return None
    return stamp.isoformat().replace("+00:00", "Z")


def _meta(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = _txt(value)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


class _ContextResolver:
    """Point-in-time context episode lookup.

    Returns the episode that was already active at ``timestamp``; never a later
    one, so a trade can not be labelled with a context it could not have seen.
    """

    def __init__(self) -> None:
        self._stamps: pd.Series | None = None
        self._episodes: pd.Series | None = None
        if not LIFECYCLE_MEMORY.exists():
            return
        try:
            frame = pd.read_parquet(
                LIFECYCLE_MEMORY, columns=["timestamp", "context_episode_id"]
            )
        except Exception:
            return
        if not len(frame):
            return
        stamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        mask = stamps.notna() & frame["context_episode_id"].notna()
        if not mask.any():
            return
        ordered = (
            pd.DataFrame(
                {"ts": stamps[mask], "episode": frame["context_episode_id"][mask]}
            )
            .sort_values("ts")
            .reset_index(drop=True)
        )
        self._stamps = ordered["ts"]
        self._episodes = ordered["episode"]

    def resolve(self, timestamp: Any) -> str | None:
        if self._stamps is None or self._episodes is None:
            return None
        stamp = pd.to_datetime(timestamp, utc=True, errors="coerce")
        if stamp is None or pd.isna(stamp):
            return None
        position = int(self._stamps.searchsorted(stamp, side="right")) - 1
        if position < 0:
            return None
        episode = self._episodes.iloc[position]
        if pd.isna(episode):
            return None
        return str(int(episode)) if float(episode).is_integer() else str(episode)


def _row(
    *,
    visual_trade_id: str,
    source_trade_id: str | None,
    source_book: str,
    source_schema_version: str,
    timeframe: str,
    side: str,
    entry_ts: str | None,
    exit_ts: str | None,
    entry_price: float | None,
    exit_price: float | None,
    quantity: float | None,
    gross_pnl: float | None,
    fees_paid: float | None,
    slippage_paid: float | None,
    net_pnl: float | None,
    context_episode_id: str | None,
    lifecycle_episode_id: str | None,
    manager_command_id: str | None,
    position_id: str | None,
    lineage_status: str,
    activation_epoch: str,
    stop_loss_price: float | None,
    take_profit_price: float | None,
    notional_usd: float | None,
    r_multiple: float | None,
    entry_price_source: str | None,
    exit_price_source: str | None,
    exit_reason: str | None,
) -> dict[str, Any]:
    return {
        "visual_trade_id": visual_trade_id,
        "source_trade_id": source_trade_id,
        "source_book": source_book,
        "source_schema_version": source_schema_version,
        "asset": ASSET,
        "timeframe": timeframe,
        "side": side,
        "entry_timestamp": entry_ts,
        "exit_timestamp": exit_ts,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "gross_pnl": gross_pnl,
        "fees_paid": fees_paid,
        "slippage_paid": slippage_paid,
        "net_pnl": net_pnl,
        "context_episode_id": context_episode_id,
        "lifecycle_episode_id": lifecycle_episode_id,
        "manager_command_id": manager_command_id,
        "position_id": position_id,
        "economics_version": ECONOMICS_VERSION,
        "lineage_status": lineage_status,
        "activation_epoch": activation_epoch,
        # render-compatible aliases
        "trade_id": visual_trade_id,
        "context_id": context_episode_id,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "notional_usd": notional_usd,
        "position_notional_usd": notional_usd,
        "gross_pnl_usd": gross_pnl,
        "fees_usd": fees_paid,
        "slippage_usd": slippage_paid,
        "net_pnl_usd": net_pnl,
        "r_multiple": r_multiple,
        "entry_price_source": entry_price_source,
        "exit_price_source": exit_price_source,
        "exit_reason": exit_reason,
        "context_quality_label": None,
        "paper_entry_basis": "CANONICAL_LEDGER_FILL",
        "paper_only": True,
        "execution_enabled": False,
    }


def build_legacy_segment(resolver: _ContextResolver | None = None) -> list[dict[str, Any]]:
    """Closed controller positions from the archived legacy global book."""
    archive = legacy_archive_dir()
    if archive is None:
        return []
    positions_path = archive / "paper_positions.parquet"
    if not positions_path.exists():
        return []
    resolver = resolver or _ContextResolver()
    frame = pd.read_parquet(positions_path)
    rows: list[dict[str, Any]] = []
    for _, raw in frame.iterrows():
        position_id = _txt(raw.get("position_id"))
        if not position_id:
            continue
        if LEGACY_ONE_SHOT_MARKER in position_id:
            continue
        if LEGACY_CONTROLLER_MARKER not in position_id:
            continue
        if (_txt(raw.get("status")) or "").upper() != "CLOSED":
            continue
        meta = _meta(raw.get("metadata_json"))
        side = (_txt(raw.get("direction")) or "LONG").upper()
        quantity = _f(raw.get("quantity"))
        entry_price = _f(raw.get("entry_price"))
        exit_price = _f(raw.get("exit_price"))
        gross = None
        if None not in (quantity, entry_price, exit_price):
            gross = (
                (exit_price - entry_price) * quantity
                if side in {"LONG", "BUY"}
                else (entry_price - exit_price) * quantity
            )
        entry_ts = _iso(raw.get("opened_at"))
        rows.append(
            _row(
                visual_trade_id=f"VIS_{position_id}",
                source_trade_id=_txt(meta.get("parent_trade_id")) or position_id,
                source_book="LEGACY_GLOBAL_PAPER_LEDGER_ARCHIVE",
                source_schema_version="paper_positions_v1",
                timeframe=LEGACY_TIMEFRAME,
                side=side,
                entry_ts=entry_ts,
                exit_ts=_iso(raw.get("closed_at")),
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                gross_pnl=gross,
                fees_paid=_f(raw.get("fees_paid")),
                slippage_paid=_f(raw.get("slippage_paid")),
                net_pnl=_f(raw.get("realized_pnl")),
                context_episode_id=resolver.resolve(entry_ts),
                lifecycle_episode_id=None,
                manager_command_id=None,
                position_id=position_id,
                lineage_status="LEGACY_GLOBAL_NO_TIMEFRAME_LINEAGE",
                activation_epoch="PRE_S4_ACTIVATION",
                stop_loss_price=_f(meta.get("stop_loss_price")),
                take_profit_price=_f(meta.get("take_profit_price")),
                notional_usd=_f(raw.get("notional")) or _f(meta.get("notional_usd")),
                r_multiple=None,
                entry_price_source=_txt(meta.get("entry_price_source")),
                exit_price_source=_txt(meta.get("exit_price_source")),
                exit_reason=_txt(meta.get("exit_reason")),
            )
        )
    return rows


def build_s4_segment(resolver: _ContextResolver | None = None) -> list[dict[str, Any]]:
    """Closed trades from the four independent timeframe trader books."""
    resolver = resolver or _ContextResolver()
    rows: list[dict[str, Any]] = []
    for timeframe in S4_TIMEFRAMES:
        trades_path = TRADER_BOOKS_ROOT / timeframe / "trades.parquet"
        if not trades_path.exists():
            continue
        try:
            frame = pd.read_parquet(trades_path)
        except Exception:
            continue
        for _, raw in frame.iterrows():
            trade_id = _txt(raw.get("trade_id"))
            if not trade_id:
                continue
            entry_ts = _iso(raw.get("entry_ts"))
            exit_ts = _iso(raw.get("exit_ts"))
            if not exit_ts:
                # Still-open trades are positions, never closed-trade markers.
                continue
            rows.append(
                _row(
                    visual_trade_id=f"VIS_{trade_id}",
                    source_trade_id=trade_id,
                    source_book=f"TIMEFRAME_TRADER_{timeframe}",
                    source_schema_version="timeframe_trader_closed_trade_v1",
                    timeframe=(_txt(raw.get("timeframe")) or timeframe).upper(),
                    side=(_txt(raw.get("side")) or "LONG").upper(),
                    entry_ts=entry_ts,
                    exit_ts=exit_ts,
                    entry_price=_f(raw.get("entry_price")),
                    exit_price=_f(raw.get("exit_price")),
                    quantity=_f(raw.get("quantity")),
                    gross_pnl=_f(raw.get("gross_pnl_usd")),
                    fees_paid=_f(raw.get("fees_usd")),
                    slippage_paid=_f(raw.get("slippage_usd")),
                    net_pnl=_f(raw.get("net_pnl_usd")),
                    context_episode_id=resolver.resolve(entry_ts),
                    lifecycle_episode_id=_txt(raw.get("lifecycle_episode_id")),
                    manager_command_id=_txt(raw.get("command_id")),
                    position_id=_txt(raw.get("position_id")),
                    lineage_status="S4_TIMEFRAME_LINEAGE",
                    activation_epoch="POST_S4_ACTIVATION",
                    stop_loss_price=_f(raw.get("stop_loss_price")),
                    take_profit_price=_f(raw.get("take_profit_price")),
                    notional_usd=_f(raw.get("notional_usd")),
                    r_multiple=_f(raw.get("r_multiple")),
                    entry_price_source="TIMEFRAME_TRADER_FILL",
                    exit_price_source="TIMEFRAME_TRADER_FILL",
                    exit_reason=_txt(raw.get("exit_reason")),
                )
            )
    return rows


def build_canonical_visual_trades() -> pd.DataFrame:
    """Deterministic, deduplicated union of both segments, ordered by exit time."""
    resolver = _ContextResolver()
    rows = build_legacy_segment(resolver) + build_s4_segment(resolver)
    frame = pd.DataFrame(rows, columns=VIEW_COLUMNS)
    if not len(frame):
        return frame
    frame = frame.drop_duplicates(subset=["visual_trade_id"], keep="first")
    order = pd.to_datetime(frame["exit_timestamp"], utc=True, errors="coerce")
    frame = frame.assign(_order=order).sort_values(
        ["_order", "visual_trade_id"], kind="stable"
    )
    return frame.drop(columns=["_order"]).reset_index(drop=True)


def reconcile(frame: pd.DataFrame | None = None) -> dict[str, Any]:
    """Invariant report used by the activation gates and the parity tests."""
    frame = build_canonical_visual_trades() if frame is None else frame
    boundary = activation_boundary()
    boundary_ts = pd.to_datetime(boundary, utc=True, errors="coerce") if boundary else None

    legacy = frame[frame["timeframe"] == LEGACY_TIMEFRAME]
    s4 = frame[frame["timeframe"] != LEGACY_TIMEFRAME]

    entry = pd.to_datetime(frame["entry_timestamp"], utc=True, errors="coerce")
    exit_ = pd.to_datetime(frame["exit_timestamp"], utc=True, errors="coerce")

    legacy_after_boundary = 0
    s4_before_boundary = 0
    if boundary_ts is not None and len(frame):
        legacy_exit = pd.to_datetime(legacy["exit_timestamp"], utc=True, errors="coerce")
        s4_entry = pd.to_datetime(s4["entry_timestamp"], utc=True, errors="coerce")
        legacy_after_boundary = int((legacy_exit > boundary_ts).sum())
        s4_before_boundary = int((s4_entry < boundary_ts).sum())

    pnl_errors = 0
    for _, row in frame.iterrows():
        gross, fees, slip, net = (
            row.get("gross_pnl"),
            row.get("fees_paid"),
            row.get("slippage_paid"),
            row.get("net_pnl"),
        )
        if None in (gross, fees, slip, net) or any(
            pd.isna(v) for v in (gross, fees, slip, net)
        ):
            continue
        if abs((float(gross) - float(fees) - float(slip)) - float(net)) > 1e-6:
            pnl_errors += 1

    return {
        "generated_at": utc_now(),
        "schema_version": CANONICAL_VISUAL_TRADE_SCHEMA_VERSION,
        "economics_version": ECONOMICS_VERSION,
        "activation_boundary": boundary,
        "total_trades": int(len(frame)),
        "legacy_trades": int(len(legacy)),
        "s4_trades": int(len(s4)),
        "duplicate_visual_trade_ids": int(
            len(frame) - frame["visual_trade_id"].astype(str).nunique()
        )
        if len(frame)
        else 0,
        "duplicate_source_trade_ids": int(
            len(frame) - frame["source_trade_id"].astype(str).nunique()
        )
        if len(frame)
        else 0,
        "cutover_overlap": int(legacy_after_boundary + s4_before_boundary),
        "legacy_rows_after_boundary": legacy_after_boundary,
        "s4_rows_before_boundary": s4_before_boundary,
        "inverted_timestamps": int((exit_ <= entry).sum()) if len(frame) else 0,
        "missing_exit_timestamp": int(exit_.isna().sum()) if len(frame) else 0,
        "pnl_reconciliation_errors": pnl_errors,
        "legacy_timeframe_label": LEGACY_TIMEFRAME,
        "legacy_manager_command_ids_null": bool(
            legacy["manager_command_id"].isna().all()
        )
        if len(legacy)
        else True,
    }


def write_canonical_visual_trades(path: Path | None = None) -> dict[str, Any]:
    """Atomically write the view plus a metadata sidecar. Read-only upstream."""
    path = path or PRODUCTION_VIEW_PARQUET
    frame = build_canonical_visual_trades()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)
    meta = reconcile(frame)
    meta["path"] = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    meta["rows"] = int(len(frame))
    meta["read_only_view"] = True
    meta["recomputes_economics"] = False
    sidecar = Path(str(path) + ".meta.json")
    sidecar.write_text(json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")
    return meta
