"""BTC M15 Market Pack for ETLL lived replay.

Builds a causal bar pack aligned to external BTC trader coverage.
Does not invent cognition/lifecycle — those are a later plane.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PACK_VERSION = "btc_m15_market_pack_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_utc_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, utc=True, errors="coerce")


def resolve_external_window(positions: pd.DataFrame) -> dict[str, Any]:
    btc = positions[
        (positions["symbol"].astype(str).str.upper() == "BTCUSDT")
        & (positions["quality_status"].astype(str).str.upper() == "OK")
    ].copy()
    if btc.empty:
        raise ValueError("no BTCUSDT OK external positions")
    entry = _to_utc_series(btc["entry_ts"])
    exit_ = _to_utc_series(btc["exit_ts"])
    start = pd.concat([entry, exit_], ignore_index=True).dropna().min()
    end = exit_.dropna().max()
    if pd.isna(end):
        end = entry.dropna().max()
    return {
        "external_btc_ok_rows": int(len(btc)),
        "external_start": start.isoformat().replace("+00:00", "Z"),
        "external_end": end.isoformat().replace("+00:00", "Z"),
        "by_source": {str(k): int(v) for k, v in btc.groupby("source").size().items()},
        "frame": btc,
        "start_ts": start,
        "end_ts": end,
    }


def build_bars_slice(
    bars: pd.DataFrame,
    *,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    frame = bars.copy()
    frame["timestamp"] = _to_utc_series(frame["timestamp"])
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    # Include bars from the M15 open that contains start through end.
    sliced = frame[(frame["timestamp"] >= start_ts.floor("15min")) & (frame["timestamp"] <= end_ts)].copy()
    if sliced.empty:
        raise ValueError("no bars in external window")
    # Causal evaluation clock = bar close = open + 15m
    sliced["bar_open"] = sliced["timestamp"]
    sliced["bar_close"] = sliced["timestamp"] + pd.Timedelta(minutes=15)
    sliced["symbol"] = "BTCUSDT"
    sliced["timeframe"] = "M15"
    cols = [
        "symbol",
        "timeframe",
        "bar_open",
        "bar_close",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    return sliced.loc[:, cols].reset_index(drop=True)


def build_btc_m15_market_pack(
    *,
    bars_path: Path,
    positions_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    positions = pd.read_parquet(positions_path)
    window = resolve_external_window(positions)
    bars_raw = pd.read_parquet(bars_path)
    bars = build_bars_slice(bars_raw, start_ts=window["start_ts"], end_ts=window["end_ts"])

    pack_end = bars["bar_close"].max()
    external_end = window["end_ts"]
    coverage_gap_after_bars = bool(external_end > pack_end)

    # External BTC OK clipped to pack-covered time (exit within bars, or open entry within).
    btc = window["frame"].copy()
    btc["_entry"] = _to_utc_series(btc["entry_ts"])
    btc["_exit"] = _to_utc_series(btc["exit_ts"])
    covered = btc[(btc["_exit"].notna() & (btc["_exit"] <= pack_end)) | (btc["_exit"].isna() & (btc["_entry"] <= pack_end))].copy()
    covered = covered.drop(columns=["_entry", "_exit"])

    # Evaluation clock for future lived replay (one row per completed M15 bar).
    clock = pd.DataFrame(
        {
            "evaluation_timestamp": bars["bar_close"],
            "timeframe": "M15",
            "source_bar_open": bars["bar_open"],
            "source_bar_close": bars["bar_close"],
            "availability_status": "FRESH_EVENT",
            "symbol": "BTCUSDT",
        }
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    bars_out = output_dir / "bars_m15.parquet"
    clock_out = output_dir / "evaluation_clock_m15.parquet"
    external_out = output_dir / "external_positions_btcusdt_ok.parquet"
    feed_out = output_dir / "feed_m15.parquet"  # S4.1-style feed alias
    manifest_out = output_dir / "manifest.json"

    bars.to_parquet(bars_out, index=False)
    clock.to_parquet(clock_out, index=False)
    covered.to_parquet(external_out, index=False)

    feed = bars.rename(columns={"bar_open": "timestamp"})[
        ["timestamp", "open", "high", "low", "close", "volume"]
    ].copy()
    feed.to_parquet(feed_out, index=False)

    manifest = {
        "pack_version": PACK_VERSION,
        "generated_at": _utc_now(),
        "symbol": "BTCUSDT",
        "timeframe": "M15",
        "note_ru": (
            "Это подготовленная история BTC M15 для прогона. "
            "Сама торговля модели ещё не запущена: для честного 'как сейчас' "
            "нужны исторические context/lifecycle плоскости (их с 2023 на диске нет)."
        ),
        "inputs": {
            "bars_path": str(bars_path),
            "positions_path": str(positions_path),
        },
        "window": {
            "external_start": window["external_start"],
            "external_end": window["external_end"],
            "pack_bar_open_first": bars["bar_open"].min().isoformat().replace("+00:00", "Z"),
            "pack_bar_close_last": pack_end.isoformat().replace("+00:00", "Z"),
            "external_btc_ok_rows_total": window["external_btc_ok_rows"],
            "external_btc_ok_rows_in_pack": int(len(covered)),
            "bars_in_pack": int(len(bars)),
            "by_source_total": window["by_source"],
            "coverage_gap_after_bars": coverage_gap_after_bars,
            "coverage_gap_note_ru": (
                "У чужих сделок хвост позже последнего бара btc_15m.parquet — "
                "эти сделки не попали в pack-окно, пока не докачаем свечи."
                if coverage_gap_after_bars
                else "Окно баров покрывает внешние OK-сделки в этом срезе."
            ),
        },
        "outputs": {
            "bars_m15": str(bars_out),
            "feed_m15": str(feed_out),
            "evaluation_clock_m15": str(clock_out),
            "external_positions_btcusdt_ok": str(external_out),
            "manifest": str(manifest_out),
        },
        "next_step_ru": (
            "Следующий шаг: восстановить/собрать historical cognition+lifecycle "
            "на этих M15 барах (или урезанный S4.1 lived replay, если решим так), "
            "затем сравнить с external_positions_btcusdt_ok."
        ),
        "status": "PACK_READY_LIVED_REPLAY_PENDING_CONTEXT",
    }
    manifest_out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest
