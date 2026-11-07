"""ETLL Shadow Lab helpers: lived books → synthetic paper JSONL + lab paths.

Isolated under market pack lived_replay/shadow_lab. Does not touch live shadows.
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

EPOCH_ID = "ETLL_LIVED_M15_V1"
LAB_NAME = "shadow_lab"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.isoformat().replace("+00:00", "Z")
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _row_dict(row: pd.Series) -> dict[str, Any]:
    return {k: _jsonable(v) for k, v in row.to_dict().items()}


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return {}


def _side_long_short(*, order_side: Any, direction: Any = None, meta_side: Any = None) -> str:
    for raw in (direction, meta_side):
        text = str(raw or "").upper()
        if text in {"LONG", "SHORT"}:
            return text
    text = str(order_side or "").upper()
    if text in {"BUY", "LONG"}:
        return "LONG"
    if text in {"SELL", "SHORT"}:
        return "SHORT"
    return text or "UNKNOWN"


def pack_paths(pack_dir: Path) -> dict[str, Path]:
    lived = pack_dir / "lived_replay"
    lab = lived / LAB_NAME
    paper_repo = lab / "paper_repo"
    return {
        "pack": pack_dir,
        "lived": lived,
        "books_parquet": lived / "books" / "M15",
        "commands_parquet": lived / "manager_commands.parquet",
        "lived_trades": lived / "lived_trades.parquet",
        "lab": lab,
        "paper_repo": paper_repo,
        "paper_books": paper_repo / "data" / "trading" / "intrabar_paper" / EPOCH_ID / "books",
        "shadow_eqcorr": paper_repo / "data" / "trading" / "shadow_economic_correlation" / "epochs" / EPOCH_ID,
        # Nested under paper_repo so AES validate_storage(repo=paper_repo) accepts it.
        "shadow_auction": paper_repo / "data" / "trading" / "shadow_auction",
        "reports": lab / "reports",
        "context": pack_dir / "context",
    }


def ensure_lab_dirs(paths: dict[str, Path]) -> None:
    for key in ("lab", "paper_books", "shadow_eqcorr", "shadow_auction", "reports"):
        paths[key].mkdir(parents=True, exist_ok=True)
    for name in ("memory", "manifests", "logs", "health", "replay", "archive"):
        (paths["shadow_auction"] / name).mkdir(parents=True, exist_ok=True)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return len(rows)


def adapt_lived_books_to_jsonl(*, pack_dir: Path, limit_trades: int | None = None) -> dict[str, Any]:
    """Convert lived M15 parquet books into EQCORR/AES-shaped JSONL under shadow_lab."""
    paths = pack_paths(pack_dir)
    ensure_lab_dirs(paths)
    books = paths["books_parquet"]
    if not books.exists():
        raise FileNotFoundError(books)

    signals = pd.read_parquet(books / "signals.parquet")
    orders = pd.read_parquet(books / "orders.parquet")
    fills = pd.read_parquet(books / "fills.parquet")
    positions = pd.read_parquet(books / "positions.parquet")
    trades = pd.read_parquet(books / "trades.parquet")
    commands = (
        pd.read_parquet(paths["commands_parquet"])
        if paths["commands_parquet"].exists()
        else pd.DataFrame()
    )

    if limit_trades is not None and limit_trades > 0:
        keep_pos = set(trades.head(int(limit_trades))["position_id"].astype(str).tolist())
        trades = trades[trades["position_id"].astype(str).isin(keep_pos)].copy()
        positions = positions[positions["position_id"].astype(str).isin(keep_pos)].copy()
        fill_ids = set()
        for col in ("entry_fill_id", "exit_fill_id"):
            if col in trades.columns:
                fill_ids |= set(trades[col].dropna().astype(str).tolist())
        fills = fills[fills["paper_trade_id"].astype(str).isin(fill_ids)].copy()
        order_ids = set(fills["paper_order_id"].dropna().astype(str).tolist()) if len(fills) else set()
        orders = orders[orders["paper_order_id"].astype(str).isin(order_ids)].copy()
        cmd_ids: set[str] = set()
        for frame in (fills, trades, positions):
            if "command_id" in frame.columns:
                cmd_ids |= {str(x) for x in frame["command_id"].dropna().tolist()}
        if "command_id" in signals.columns and cmd_ids:
            signals = signals[signals["command_id"].astype(str).isin(cmd_ids)].copy()
        if len(commands) and "command_id" in commands.columns and cmd_ids:
            commands = commands[commands["command_id"].astype(str).isin(cmd_ids)].copy()

    entry_by_pos = {
        str(r["position_id"]): str(r["entry_fill_id"])
        for _, r in trades.iterrows()
        if r.get("position_id") is not None and r.get("entry_fill_id") is not None
    }
    exit_by_pos = {
        str(r["position_id"]): str(r["exit_fill_id"])
        for _, r in trades.iterrows()
        if r.get("position_id") is not None and r.get("exit_fill_id") is not None
    }
    entry_fill_ids = set(entry_by_pos.values())
    exit_fill_ids = set(exit_by_pos.values())

    signal_rows: list[dict[str, Any]] = []
    for _, row in signals.iterrows():
        rec = _row_dict(row)
        rec["context_event_id"] = rec.get("context_episode_id") or rec.get("context_event_id")
        rec["lifecycle_episode_id"] = rec.get("context_episode_id") or rec.get("lifecycle_episode_id")
        signal_rows.append(rec)

    order_rows: list[dict[str, Any]] = []
    for _, row in orders.iterrows():
        rec = _row_dict(row)
        meta = _parse_meta(rec.get("metadata_json"))
        rec["order_id"] = rec.get("paper_order_id") or rec.get("order_id")
        rec["ts"] = rec.get("candle_timestamp") or meta.get("fill_timestamp") or rec.get("created_at")
        order_rows.append(rec)

    fill_rows: list[dict[str, Any]] = []
    for _, row in fills.iterrows():
        rec = _row_dict(row)
        meta = _parse_meta(rec.get("metadata_json"))
        fill_id = str(rec.get("paper_trade_id") or "")
        pos_id = str(rec.get("position_id") or meta.get("paper_position_id") or "")
        if fill_id in entry_fill_ids:
            action = "ENTRY"
        elif fill_id in exit_fill_ids:
            action = "EXIT"
        else:
            # Fallback: open metadata → ENTRY
            action = "ENTRY" if str(meta.get("position_status") or "").upper() == "OPEN" else "EXIT"
        side = _side_long_short(
            order_side=rec.get("side"),
            direction=meta.get("timeframe_direction"),
            meta_side=meta.get("side"),
        )
        fill_rows.append(
            {
                **rec,
                "fill_id": fill_id,
                "order_id": rec.get("paper_order_id"),
                "action": action,
                "ts": rec.get("timestamp") or meta.get("fill_timestamp"),
                "paper_fill_price": rec.get("price"),
                "gross_entry_price": rec.get("price"),
                "side": side,
                "lifecycle_episode_id": meta.get("lifecycle_episode_id"),
                "context_event_id": meta.get("lifecycle_episode_id"),
                "stop_loss_price": meta.get("stop_loss_price"),
                "take_profit_price": meta.get("take_profit_price"),
                "risk_amount_usd": meta.get("approved_risk_usd") or meta.get("requested_risk_usd"),
            }
        )

    position_rows: list[dict[str, Any]] = []
    for _, row in positions.iterrows():
        rec = _row_dict(row)
        meta = _parse_meta(rec.get("metadata_json"))
        pos_id = str(rec.get("position_id") or "")
        side = _side_long_short(
            order_side=None,
            direction=rec.get("direction"),
            meta_side=meta.get("side"),
        )
        position_rows.append(
            {
                **rec,
                "side": side,
                "entry_fill_id": entry_by_pos.get(pos_id) or meta.get("parent_trade_id"),
                "exit_fill_id": exit_by_pos.get(pos_id),
                "lifecycle_episode_id": meta.get("lifecycle_episode_id") or rec.get("lifecycle_episode_id"),
                "entry_context_event_id": meta.get("lifecycle_episode_id"),
                "entry_command_id": rec.get("command_id") or meta.get("command_id"),
                "stop_loss_price": meta.get("stop_loss_price") or rec.get("stop_loss_price"),
                "take_profit_price": meta.get("take_profit_price") or rec.get("take_profit_price"),
                "risk_amount_usd": meta.get("approved_risk_usd") or meta.get("requested_risk_usd") or 250.0,
                "risk_budget_usd": meta.get("approved_risk_usd") or 250.0,
                "notional_usd": rec.get("notional") or meta.get("notional_usd"),
                "stop_distance_usd": (meta.get("sizing") or {}).get("stop_distance")
                if isinstance(meta.get("sizing"), dict)
                else None,
            }
        )

    trade_rows: list[dict[str, Any]] = []
    for _, row in trades.iterrows():
        rec = _row_dict(row)
        trade_rows.append(
            {
                **rec,
                "status": "CLOSED",
                "closed_at": rec.get("exit_ts"),
            }
        )

    command_rows: list[dict[str, Any]] = []
    if len(commands):
        # Prefer OPEN intents that actually produced fills; still dump all linked cmds.
        for _, row in commands.iterrows():
            rec = _row_dict(row)
            # Link signal_id when possible
            cmd_id = str(rec.get("command_id") or "")
            sig_match = signals[signals["command_id"].astype(str) == cmd_id] if "command_id" in signals.columns else pd.DataFrame()
            if len(sig_match):
                rec["signal_id"] = sig_match.iloc[0].get("signal_id")
            command_rows.append(rec)

    out_books = paths["paper_books"]
    counts = {
        "signals": _write_jsonl(out_books / "signals.jsonl", signal_rows),
        "orders": _write_jsonl(out_books / "orders.jsonl", order_rows),
        "fills": _write_jsonl(out_books / "fills.jsonl", fill_rows),
        "positions": _write_jsonl(out_books / "positions.jsonl", position_rows),
        "trades": _write_jsonl(out_books / "trades.jsonl", trade_rows),
        "commands": _write_jsonl(out_books / "commands.jsonl", command_rows),
    }
    entry_n = sum(1 for r in fill_rows if r.get("action") == "ENTRY")

    # Synthetic mini-repo scaffolding for EQCORR
    repo = paths["paper_repo"]
    (repo / "config").mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[3]
    src_cfg = repo_root / "config" / "intrabar_paper_execution.json"
    if src_cfg.exists():
        shutil.copy2(src_cfg, repo / "config" / "intrabar_paper_execution.json")
    else:
        (repo / "config" / "intrabar_paper_execution.json").write_text("{}\n", encoding="utf-8")

    epochs = repo / "data" / "trading" / "paper_epochs"
    epochs.mkdir(parents=True, exist_ok=True)
    (epochs / "active.json").write_text(
        json.dumps(
            {
                "paper_epoch_id": EPOCH_ID,
                "trading_contract_fingerprint": "etll_lived_m15_shadow_lab_v1",
                "parent_trading_contract_fingerprint": "etll_lived_m15_shadow_lab_v1",
                "epoch_status": "ACTIVE",
                "note": "Synthetic epoch for ETLL shadow lab; not a live paper epoch",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "cognition" / "intrabar_context_events" / "events.jsonl").write_text("", encoding="utf-8")
    (repo / "data" / "runtime").mkdir(parents=True, exist_ok=True)

    summary = {
        "generated_at": _utc_now(),
        "epoch_id": EPOCH_ID,
        "paper_books": str(out_books),
        "counts": counts,
        "entry_fills": entry_n,
        "exit_fills": sum(1 for r in fill_rows if r.get("action") == "EXIT"),
        "limit_trades": limit_trades,
        "external_trades_used": False,
        "status": "BOOKS_ADAPTED",
    }
    (paths["reports"] / "books_adapter_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary
