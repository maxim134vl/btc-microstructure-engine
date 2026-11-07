"""Causal S4.1 paper book on rebuilt living-process lifecycle.

Fill = closed-bar close. Stop/take = next bars' high/low via evaluate_exit_preview.
OBSERVE holds. Opposite CHALLENGED holds. Opposite ACTIVE closes (early).
Does not touch live cognition. Not a tick book.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from btc_ml.trading.paper_core import (
    MAX_RISK_USD,
    closed_trade_economics,
    evaluate_exit_preview,
    resolve_risk_sizing,
    stop_take_prices,
)
from btc_ml.trading.timeframe_manager import (
    ENTRY_REQUIRES_CONFIRMED_RAW_STATUS,
    _preview_context_for_open_position,
    _raw_status_blocks_new_entry,
    _strength_too_weak,
)

ROOT = Path(__file__).resolve().parents[3]
PACK_ROOTS = (
    ROOT / "data/research/external_traders",
    Path("/Volumes/MaksTiger/btc-ml/from-mac-20260907/btc-ml-cold/research/external_traders"),
)
RISK_PATH = ROOT / "config/timeframe_trader_risk.json"
TIMEFRAMES = ("M15", "M30", "H1", "H4")
INITIAL_EQUITY = 100_000.0
DIRECTIONAL = {"LONG_CONTEXT", "SHORT_CONTEXT", "LONG", "SHORT"}


def resolve_pack_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    for root in PACK_ROOTS:
        if (root / "market_pack_btc_m15" / "feed_m15.parquet").exists():
            return root
    return PACK_ROOTS[0]


def load_risk() -> dict[str, float]:
    payload = json.loads(RISK_PATH.read_text(encoding="utf-8"))
    raw = payload.get("per_trader_max_risk_usd") or {}
    return {str(k).upper(): float(v) for k, v in raw.items()}


def _side_from_context(ctx: str) -> str | None:
    text = str(ctx or "").upper()
    if text in {"LONG", "LONG_CONTEXT"}:
        return "LONG"
    if text in {"SHORT", "SHORT_CONTEXT"}:
        return "SHORT"
    return None


def _exit_bucket(reason: str) -> str:
    text = str(reason or "").upper()
    if "STOP" in text:
        return "STOP"
    if "TAKE" in text:
        return "TAKE"
    return "EARLY"


def _can_open(
    *,
    phase: str,
    ctx: str,
    raw_status: str,
    atomic_flip: bool,
    process_strength: float | None = None,
    timeframe: str = "M15",
) -> bool:
    if str(phase).upper() != "ACTIVE":
        return False
    if _side_from_context(ctx) is None:
        return False
    if _strength_too_weak({"process_strength": process_strength, "timeframe": timeframe}, timeframe):
        return False
    if atomic_flip:
        return True
    if not ENTRY_REQUIRES_CONFIRMED_RAW_STATUS:
        return True
    return not _raw_status_blocks_new_entry({"raw_context_status": raw_status})


def load_tf_bars(pack_dir: Path, timeframe: str) -> pd.DataFrame:
    ctx_dir = pack_dir / "context"
    life = pd.read_parquet(ctx_dir / "market_context_lifecycle_memory.parquet")
    candle = pd.read_parquet(ctx_dir / "candle_structure_memory.parquet")
    life["timestamp"] = pd.to_datetime(life["timestamp"], utc=True, errors="coerce")
    candle["timestamp"] = pd.to_datetime(candle["timestamp"], utc=True, errors="coerce")
    keep = [c for c in ("timestamp", "open", "high", "low", "close") if c in candle.columns]
    work = life.merge(candle[keep], on="timestamp", how="left", suffixes=("", "_c"))
    if "close" not in work.columns or work["close"].isna().all():
        work["close"] = work.get("close_c")
    work = work.dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)
    work["timeframe"] = str(timeframe).upper()
    return work


def simulate_tf(bars: pd.DataFrame, *, timeframe: str, risk_usd: float) -> list[dict[str, Any]]:
    tf = str(timeframe).upper()
    n = len(bars)
    if n == 0:
        return []
    ts = pd.to_datetime(bars["timestamp"], utc=True)
    high = pd.to_numeric(bars["high"], errors="coerce").to_numpy()
    low = pd.to_numeric(bars["low"], errors="coerce").to_numpy()
    close = pd.to_numeric(bars["close"], errors="coerce").to_numpy()
    ctx = bars["active_market_context"].astype(str).str.upper().to_numpy()
    phase = bars["lifecycle_state"].astype(str).str.upper().to_numpy()
    raw = bars["raw_context_status"].astype(str).str.upper().to_numpy()
    episode = bars["context_episode_id"].astype(str).to_numpy() if "context_episode_id" in bars.columns else np.array(["?"] * n)
    strength = (
        pd.to_numeric(bars["process_strength"], errors="coerce").to_numpy()
        if "process_strength" in bars.columns
        else np.full(n, np.nan)
    )
    process = bars["living_process"].astype(str).to_numpy() if "living_process" in bars.columns else np.array([""] * n)

    pos: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    seq = 0

    def open_pos(i: int, side: str, *, reason: str) -> None:
        nonlocal pos, seq
        entry = float(close[i])
        if not np.isfinite(entry) or entry <= 0:
            return
        stop, take = stop_take_prices(side, entry)
        sizing = resolve_risk_sizing(side=side, entry_price=entry, stop_loss_price=stop, take_profit_price=take)
        if not sizing.allowed or not sizing.position_size_btc:
            return
        scale = float(risk_usd) / float(MAX_RISK_USD) if MAX_RISK_USD else 1.0
        qty = float(sizing.position_size_btc) * scale
        seq += 1
        pos = {
            "side": side,
            "entry_i": i,
            "entry_ts": ts.iloc[i],
            "entry_price": entry,
            "stop": float(stop),
            "take": float(take),
            "qty": qty,
            "risk": float(risk_usd),
            "entry_fee": float(sizing.entry_fee_usd or 0.0) * scale,
            "episode": str(episode[i]),
            "open_reason": reason,
            "trade_id": f"{tf}_{seq}",
            "process_strength": None if not np.isfinite(strength[i]) else float(strength[i]),
            "living_process": str(process[i]),
        }

    def close_pos(i: int, *, reason: str, price: float) -> dict[str, Any]:
        nonlocal pos
        assert pos is not None
        econ = closed_trade_economics(
            side=pos["side"],
            entry_price=pos["entry_price"],
            exit_price=float(price),
            position_size_btc=pos["qty"],
            stop_loss_price=pos["stop"],
            take_profit_price=pos["take"],
            risk_amount_usd=pos["risk"],
            exit_reason=reason,
            exit_execution_source="historical_completed_bar_ohlc",
        )
        row = {
            "trade_id": pos["trade_id"],
            "timeframe": tf,
            "side": pos["side"],
            "entry_ts": pos["entry_ts"],
            "exit_ts": ts.iloc[i],
            "entry_price": pos["entry_price"],
            "exit_price": float(econ["exit_price"]),
            "stop_loss_price": pos["stop"],
            "take_profit_price": pos["take"],
            "quantity": pos["qty"],
            "net_pnl_usd": float(econ["net_pnl_usd"]),
            "gross_pnl_usd": float(econ["gross_pnl_usd"]),
            "fees_usd": float(econ["fees_usd"]),
            "slippage_usd": float(econ["slippage_usd"]),
            "r_multiple": float(econ["r_multiple"]),
            "exit_reason": reason,
            "exit_bucket": _exit_bucket(reason),
            "open_reason": pos["open_reason"],
            "episode_id": pos["episode"],
            "process_strength": pos["process_strength"],
            "living_process": pos["living_process"],
            "hold_hours": float((ts.iloc[i] - pos["entry_ts"]).total_seconds() / 3600.0),
        }
        pos = None
        trades.append(row)
        return row

    i = 0
    while i < n:
        hi = float(high[i]) if np.isfinite(high[i]) else float(close[i])
        lo = float(low[i]) if np.isfinite(low[i]) else float(close[i])
        px = float(close[i])
        if pos is not None:
            preview_ctx = _preview_context_for_open_position(
                pos["side"],
                str(ctx[i]),
                str(phase[i]),
                process_strength=None if not np.isfinite(strength[i]) else float(strength[i]),
                timeframe=tf,
            )
            if preview_ctx is None:
                i += 1
                continue
            preview = evaluate_exit_preview(
                side=pos["side"],
                entry_price=pos["entry_price"],
                quantity=pos["qty"],
                stop_loss_price=pos["stop"],
                take_profit_price=pos["take"],
                entry_fee_usd=pos["entry_fee"],
                current_price=px,
                latest_high=hi,
                latest_low=lo,
                latest_context=preview_ctx,
                latest_lifecycle_state=str(phase[i]),
            )
            if preview.get("is_close"):
                reason = str(preview.get("exit_preview_reason") or "CONTEXT_EXIT")
                exit_px = float(preview.get("suggested_exit_price") or px)
                flip = bool(preview.get("exited_on_flip"))
                close_pos(i, reason=reason, price=exit_px)
                follow_side = _side_from_context(str(ctx[i]))
                if follow_side and _can_open(
                    phase=str(phase[i]),
                    ctx=str(ctx[i]),
                    raw_status=str(raw[i]),
                    atomic_flip=flip,
                    process_strength=None if not np.isfinite(strength[i]) else float(strength[i]),
                    timeframe=tf,
                ):
                    open_pos(i, follow_side, reason="ATOMIC_FLIP_OPEN" if flip else "TP_SL_CONTINUATION_OPEN")
                i += 1
                continue
        if pos is None:
            side = _side_from_context(str(ctx[i]))
            if side and _can_open(
                phase=str(phase[i]),
                ctx=str(ctx[i]),
                raw_status=str(raw[i]),
                atomic_flip=False,
                process_strength=None if not np.isfinite(strength[i]) else float(strength[i]),
                timeframe=tf,
            ):
                open_pos(i, side, reason="TIMEFRAME_DIRECTIONAL_ENTRY")
        i += 1

    if pos is not None:
        close_pos(n - 1, reason="END_OF_SAMPLE", price=float(close[-1]))
    return trades


def simulate_book(*, pack_root: Path | None = None, timeframes: tuple[str, ...] = TIMEFRAMES) -> pd.DataFrame:
    root = resolve_pack_root(pack_root)
    risk = load_risk()
    rows: list[dict[str, Any]] = []
    for tf in timeframes:
        pack = root / f"market_pack_btc_{tf.lower()}"
        if not (pack / "context" / "market_context_lifecycle_memory.parquet").exists():
            continue
        bars = load_tf_bars(pack, tf)
        rows.extend(simulate_tf(bars, timeframe=tf, risk_usd=float(risk.get(tf, MAX_RISK_USD))))
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["entry_ts"] = pd.to_datetime(out["entry_ts"], utc=True)
    out["exit_ts"] = pd.to_datetime(out["exit_ts"], utc=True)
    return out.sort_values("exit_ts").reset_index(drop=True)
