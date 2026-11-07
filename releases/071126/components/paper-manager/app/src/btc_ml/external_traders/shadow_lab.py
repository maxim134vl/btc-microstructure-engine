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

EPOCH_ID = "ETLL_LIVED_M15_V1"  # legacy default
MULTI_TF_EPOCH_ID = "ETLL_LIVED_MULTI_TF_V1"
MULTI_TF_TIMEFRAMES = ("M15", "M30", "H1", "H4")
LAB_NAME = "shadow_lab"


def epoch_id_for(timeframe: str) -> str:
    tf = str(timeframe or "M15").upper()
    return f"ETLL_LIVED_{tf}_V1"


def default_pack_dir(timeframe: str) -> Path:
    tf = str(timeframe or "M15").upper()
    root = Path(__file__).resolve().parents[3]
    if tf == "M15":
        return root / "data/research/external_traders/market_pack_btc_m15"
    return root / f"data/research/external_traders/market_pack_btc_{tf.lower()}"


def multi_tf_root() -> Path:
    return Path(__file__).resolve().parents[3] / "data/research/external_traders/etll_multi_tf"


def multi_tf_paths() -> dict[str, Path]:
    root = multi_tf_root()
    epoch = MULTI_TF_EPOCH_ID
    lived = root / "lived_replay"
    lab = lived / LAB_NAME
    paper_repo = lab / "paper_repo"
    return {
        "pack": root,
        "timeframe": "MULTI",
        "epoch_id": epoch,
        "lived": lived,
        "lived_trades": lived / "lived_trades.parquet",
        "lab": lab,
        "paper_repo": paper_repo,
        "paper_books": paper_repo / "data" / "trading" / "intrabar_paper" / epoch / "books",
        "shadow_eqcorr": paper_repo / "data" / "trading" / "shadow_economic_correlation" / "epochs" / epoch,
        "shadow_auction": paper_repo / "data" / "trading" / "shadow_auction",
        "reports": lab / "reports",
        "context": default_pack_dir("M15") / "context",
    }


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


def pack_paths(pack_dir: Path, timeframe: str = "M15") -> dict[str, Path]:
    tf = str(timeframe or "M15").upper()
    epoch = epoch_id_for(tf)
    lived = pack_dir / "lived_replay"
    lab = lived / LAB_NAME
    paper_repo = lab / "paper_repo"
    return {
        "pack": pack_dir,
        "timeframe": tf,
        "epoch_id": epoch,
        "lived": lived,
        "books_parquet": lived / "books" / tf,
        "commands_parquet": lived / "manager_commands.parquet",
        "lived_trades": lived / "lived_trades.parquet",
        "lab": lab,
        "paper_repo": paper_repo,
        "paper_books": paper_repo / "data" / "trading" / "intrabar_paper" / epoch / "books",
        "shadow_eqcorr": paper_repo / "data" / "trading" / "shadow_economic_correlation" / "epochs" / epoch,
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


def link_pack_cognition_for_eqcorr(paths: dict[str, Path]) -> None:
    """Symlink pack context planes into paper_repo for causal enrichment."""
    repo_cog = paths["paper_repo"] / "data" / "cognition"
    repo_cog.mkdir(parents=True, exist_ok=True)
    ctx = paths["context"]
    tf = str(paths.get("timeframe") or "M15").upper()

    volume_src = ctx / "volume_response_state.parquet"
    if not volume_src.exists():
        volume_src = ctx / "volume_response_state_proxy.parquet"

    mapping: dict[str, Path] = {
        "candle_structure_memory.parquet": ctx / "candle_structure_memory.parquet",
        "volume_response_state.parquet": volume_src,
        "volume_classification_memory.parquet": ctx / "volume_classification_memory.parquet",
        # Best-effort proxies for live cognition planes (partial columns).
        "runtime_cognition_memory.parquet": ctx / "cognitive_market_state_memory.parquet",
        "multi_timeframe_synthesis.parquet": ctx / "final_market_context_memory.parquet",
    }
    for name, src in mapping.items():
        if not src.exists():
            continue
        dest = repo_cog / name
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        dest.symlink_to(src.resolve())

    # volume_response expects source_timeframe for per-TF join — inject if missing.
    vr_dest = repo_cog / "volume_response_state.parquet"
    if vr_dest.exists() and vr_dest.suffix == ".parquet":
        pass  # symlink only; EQCORR enricher tolerates missing source_timeframe as global
    (paths["paper_repo"] / "data" / "runtime").mkdir(parents=True, exist_ok=True)


def _ts_sort_key(row: dict[str, Any]) -> tuple[str, int]:
    ts = str(row.get("ts") or row.get("timestamp") or row.get("entry_ts") or row.get("exit_ts") or "")
    action = str(row.get("action") or "").upper()
    # ENTRY before EXIT when timestamps tie.
    return ts, 1 if action == "EXIT" else 0


def _convert_book_frames(
    *,
    signals: pd.DataFrame,
    orders: pd.DataFrame,
    fills: pd.DataFrame,
    positions: pd.DataFrame,
    trades: pd.DataFrame,
    commands: pd.DataFrame,
) -> dict[str, list[dict[str, Any]]]:
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
        if fill_id in entry_fill_ids:
            action = "ENTRY"
        elif fill_id in exit_fill_ids:
            action = "EXIT"
        else:
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
        for _, row in commands.iterrows():
            rec = _row_dict(row)
            cmd_id = str(rec.get("command_id") or "")
            sig_match = signals[signals["command_id"].astype(str) == cmd_id] if "command_id" in signals.columns else pd.DataFrame()
            if len(sig_match):
                rec["signal_id"] = sig_match.iloc[0].get("signal_id")
            command_rows.append(rec)

    fill_rows.sort(key=_ts_sort_key)
    order_rows.sort(key=_ts_sort_key)
    trade_rows.sort(key=_ts_sort_key)

    return {
        "signals": signal_rows,
        "orders": order_rows,
        "fills": fill_rows,
        "positions": position_rows,
        "trades": trade_rows,
        "commands": command_rows,
    }


def _write_paper_repo_scaffold(*, paths: dict[str, Path], epoch: str, note: str, contract_tag: str) -> None:
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
                "paper_epoch_id": epoch,
                "trading_contract_fingerprint": contract_tag,
                "parent_trading_contract_fingerprint": contract_tag,
                "epoch_status": "ACTIVE",
                "note": note,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "cognition" / "intrabar_context_events" / "events.jsonl").write_text("", encoding="utf-8")
    (repo / "data" / "runtime").mkdir(parents=True, exist_ok=True)


def build_multi_tf_lived_trades(*, paths: dict[str, Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for tf in MULTI_TF_TIMEFRAMES:
        src = default_pack_dir(tf) / "lived_replay" / "lived_trades.parquet"
        if not src.exists():
            raise FileNotFoundError(src)
        part = pd.read_parquet(src)
        part["timeframe"] = tf
        frames.append(part)
    lived = pd.concat(frames, ignore_index=True)
    sort_col = "entry_ts" if "entry_ts" in lived.columns else lived.columns[0]
    lived = lived.sort_values(sort_col).reset_index(drop=True)
    paths["lived"].mkdir(parents=True, exist_ok=True)
    lived.to_parquet(paths["lived_trades"], index=False)
    return lived


def adapt_multi_tf_lived_books_to_jsonl(*, limit_trades: int | None = None) -> dict[str, Any]:
    """Merge canonical lived books M15+M30+H1+H4 into one EQCORR paper epoch."""
    paths = multi_tf_paths()
    epoch = paths["epoch_id"]
    ensure_lab_dirs(paths)

    signals_parts: list[pd.DataFrame] = []
    orders_parts: list[pd.DataFrame] = []
    fills_parts: list[pd.DataFrame] = []
    positions_parts: list[pd.DataFrame] = []
    trades_parts: list[pd.DataFrame] = []
    commands_parts: list[pd.DataFrame] = []

    for tf in MULTI_TF_TIMEFRAMES:
        pack = default_pack_dir(tf)
        lived = pack / "lived_replay"
        books = lived / "books" / tf
        if not books.exists():
            raise FileNotFoundError(books)
        signals_parts.append(pd.read_parquet(books / "signals.parquet"))
        orders_parts.append(pd.read_parquet(books / "orders.parquet"))
        fills_parts.append(pd.read_parquet(books / "fills.parquet"))
        positions_parts.append(pd.read_parquet(books / "positions.parquet"))
        trades_parts.append(pd.read_parquet(books / "trades.parquet"))
        cmd_path = lived / "manager_commands.parquet"
        if cmd_path.exists():
            commands_parts.append(pd.read_parquet(cmd_path))

    signals = pd.concat(signals_parts, ignore_index=True)
    orders = pd.concat(orders_parts, ignore_index=True)
    fills = pd.concat(fills_parts, ignore_index=True)
    positions = pd.concat(positions_parts, ignore_index=True)
    trades = pd.concat(trades_parts, ignore_index=True)
    commands = pd.concat(commands_parts, ignore_index=True) if commands_parts else pd.DataFrame()

    if limit_trades is not None and limit_trades > 0:
        lived = build_multi_tf_lived_trades(paths=paths)
        keep_pos = set(lived.head(int(limit_trades))["position_id"].astype(str).tolist())
        trades = trades[trades["position_id"].astype(str).isin(keep_pos)].copy()
        positions = positions[positions["position_id"].astype(str).isin(keep_pos)].copy()
        fill_ids: set[str] = set()
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
    else:
        build_multi_tf_lived_trades(paths=paths)

    rows = _convert_book_frames(
        signals=signals,
        orders=orders,
        fills=fills,
        positions=positions,
        trades=trades,
        commands=commands,
    )

    out_books = paths["paper_books"]
    counts = {name: _write_jsonl(out_books / f"{name}.jsonl", body) for name, body in rows.items()}
    entry_n = sum(1 for r in rows["fills"] if r.get("action") == "ENTRY")

    _write_paper_repo_scaffold(
        paths=paths,
        epoch=epoch,
        contract_tag="etll_lived_multi_tf_shadow_lab_v1",
        note="Synthetic multi-TF epoch (M15+M30+H1+H4 canonical lived books); not live paper",
    )

    by_tf = trades.groupby(trades["timeframe"].astype(str).str.upper()).size().to_dict() if "timeframe" in trades.columns else {}
    summary = {
        "generated_at": _utc_now(),
        "epoch_id": epoch,
        "timeframe": "MULTI",
        "timeframes": list(MULTI_TF_TIMEFRAMES),
        "trades_by_timeframe": by_tf,
        "paper_books": str(out_books),
        "counts": counts,
        "entry_fills": entry_n,
        "exit_fills": sum(1 for r in rows["fills"] if r.get("action") == "EXIT"),
        "limit_trades": limit_trades,
        "external_trades_used": False,
        "status": "MULTI_TF_BOOKS_ADAPTED",
    }
    (paths["reports"] / "books_adapter_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def adapt_lived_books_to_jsonl(
    *,
    pack_dir: Path,
    timeframe: str = "M15",
    limit_trades: int | None = None,
) -> dict[str, Any]:
    """Convert lived TF parquet books into EQCORR/AES-shaped JSONL under shadow_lab."""
    paths = pack_paths(pack_dir, timeframe=timeframe)
    epoch = paths["epoch_id"]
    tf = paths["timeframe"]
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

    rows = _convert_book_frames(
        signals=signals,
        orders=orders,
        fills=fills,
        positions=positions,
        trades=trades,
        commands=commands,
    )

    out_books = paths["paper_books"]
    counts = {name: _write_jsonl(out_books / f"{name}.jsonl", body) for name, body in rows.items()}
    entry_n = sum(1 for r in rows["fills"] if r.get("action") == "ENTRY")

    _write_paper_repo_scaffold(
        paths=paths,
        epoch=epoch,
        contract_tag=f"etll_lived_{timeframe.lower()}_shadow_lab_v1",
        note=f"Synthetic epoch for ETLL shadow lab ({tf}); not a live paper epoch",
    )

    summary = {
        "generated_at": _utc_now(),
        "epoch_id": epoch,
        "timeframe": tf,
        "paper_books": str(out_books),
        "counts": counts,
        "entry_fills": entry_n,
        "exit_fills": sum(1 for r in rows["fills"] if r.get("action") == "EXIT"),
        "limit_trades": limit_trades,
        "external_trades_used": False,
        "status": "BOOKS_ADAPTED",
    }
    (paths["reports"] / "books_adapter_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary
