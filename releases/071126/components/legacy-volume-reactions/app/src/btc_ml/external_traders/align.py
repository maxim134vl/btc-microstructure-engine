"""ETLL Align: compare lived model trades vs canonical external BTC positions.

Offline only. Does not write Toxic Box or live books.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

ALIGN_VERSION = "etll_align_v1"
BAR_SECONDS_M15 = 15 * 60

CLASS_WE_AGREED = "WE_AGREED"
CLASS_THEY_TOOK_WE_SKIPPED = "THEY_TOOK_WE_SKIPPED"
CLASS_WE_TOOK_THEY_SKIPPED = "WE_TOOK_THEY_SKIPPED"
CLASS_OPPOSITE = "OPPOSITE"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def _side(value: Any) -> str:
    return str(value or "").strip().upper()


@dataclass(frozen=True)
class AlignConfig:
    match_bars: int = 4  # ±N M15 bars around external entry
    require_interval_overlap: bool = False


def _prepare_lived(lived: pd.DataFrame) -> pd.DataFrame:
    out = lived.copy()
    out["side"] = out["side"].map(_side)
    out["entry_ts"] = _ts(out["entry_ts"])
    out["exit_ts"] = _ts(out["exit_ts"])
    out["net_pnl_usd"] = pd.to_numeric(out.get("net_pnl_usd"), errors="coerce")
    out["entry_price"] = pd.to_numeric(out.get("entry_price"), errors="coerce")
    out["exit_price"] = pd.to_numeric(out.get("exit_price"), errors="coerce")
    out = out.dropna(subset=["entry_ts", "exit_ts", "side"]).sort_values("entry_ts").reset_index(drop=True)
    out["_lived_idx"] = np.arange(len(out), dtype=np.int64)
    return out


def _prepare_external(external: pd.DataFrame) -> pd.DataFrame:
    out = external.copy()
    out = out[out["symbol"].astype(str).str.upper() == "BTCUSDT"]
    out = out[out["quality_status"].astype(str).str.upper() == "OK"]
    out["side"] = out["side"].map(_side)
    out["entry_ts"] = _ts(out["entry_ts"])
    out["exit_ts"] = _ts(out["exit_ts"])
    out["pnl_quote"] = pd.to_numeric(out.get("pnl_quote"), errors="coerce")
    out["entry_price"] = pd.to_numeric(out.get("entry_price"), errors="coerce")
    out["exit_price"] = pd.to_numeric(out.get("exit_price"), errors="coerce")
    out = out.dropna(subset=["entry_ts", "exit_ts", "side"]).sort_values("entry_ts").reset_index(drop=True)
    out["_ext_idx"] = np.arange(len(out), dtype=np.int64)
    return out


def _intervals_overlap(a0: pd.Timestamp, a1: pd.Timestamp, b0: pd.Timestamp, b1: pd.Timestamp) -> bool:
    return bool(a0 < b1 and b0 < a1)


def align_positions(
    *,
    lived: pd.DataFrame,
    external: pd.DataFrame,
    config: AlignConfig | None = None,
) -> dict[str, Any]:
    """Match external BTC positions to lived M15 trades by entry proximity + side."""
    cfg = config or AlignConfig()
    window = pd.Timedelta(seconds=cfg.match_bars * BAR_SECONDS_M15)

    L = _prepare_lived(lived)
    E = _prepare_external(external)
    if not len(L) or not len(E):
        raise ValueError("align requires non-empty lived and external OK BTC rows")

    lived_entry = L["entry_ts"].to_numpy(dtype="datetime64[ns]")
    pairs: list[dict[str, Any]] = []
    matched_lived: set[int] = set()
    matched_ext: set[int] = set()

    for _, ext in E.iterrows():
        lo = (ext["entry_ts"] - window).to_datetime64()
        hi = (ext["entry_ts"] + window).to_datetime64()
        left = int(np.searchsorted(lived_entry, lo, side="left"))
        right = int(np.searchsorted(lived_entry, hi, side="right"))
        candidates = L.iloc[left:right]
        if not len(candidates):
            continue

        same = candidates[candidates["side"] == ext["side"]]
        opp = candidates[candidates["side"] != ext["side"]]

        if cfg.require_interval_overlap:
            same = same[
                same.apply(
                    lambda r: _intervals_overlap(r["entry_ts"], r["exit_ts"], ext["entry_ts"], ext["exit_ts"]),
                    axis=1,
                )
            ]
            opp = opp[
                opp.apply(
                    lambda r: _intervals_overlap(r["entry_ts"], r["exit_ts"], ext["entry_ts"], ext["exit_ts"]),
                    axis=1,
                )
            ]

        best_same = None
        if len(same):
            delta = (same["entry_ts"] - ext["entry_ts"]).abs()
            best_same = same.loc[delta.idxmin()]

        best_opp = None
        if len(opp):
            delta = (opp["entry_ts"] - ext["entry_ts"]).abs()
            best_opp = opp.loc[delta.idxmin()]

        if best_same is not None:
            lived_row = best_same
            align_class = CLASS_WE_AGREED
        elif best_opp is not None:
            lived_row = best_opp
            align_class = CLASS_OPPOSITE
        else:
            continue

        lived_idx = int(lived_row["_lived_idx"])
        ext_idx = int(ext["_ext_idx"])
        matched_lived.add(lived_idx)
        matched_ext.add(ext_idx)
        entry_delta_s = float((lived_row["entry_ts"] - ext["entry_ts"]).total_seconds())
        overlap = _intervals_overlap(
            lived_row["entry_ts"], lived_row["exit_ts"], ext["entry_ts"], ext["exit_ts"]
        )
        our_pnl = float(lived_row["net_pnl_usd"]) if pd.notna(lived_row["net_pnl_usd"]) else None
        their_pnl = float(ext["pnl_quote"]) if pd.notna(ext["pnl_quote"]) else None
        pairs.append(
            {
                "align_class": align_class,
                "entry_delta_seconds": entry_delta_s,
                "entry_delta_bars_m15": entry_delta_s / BAR_SECONDS_M15,
                "interval_overlap": bool(overlap),
                "lived_trade_id": lived_row.get("trade_id"),
                "lived_side": lived_row["side"],
                "lived_entry_ts": lived_row["entry_ts"].isoformat().replace("+00:00", "Z"),
                "lived_exit_ts": lived_row["exit_ts"].isoformat().replace("+00:00", "Z"),
                "lived_entry_price": None if pd.isna(lived_row["entry_price"]) else float(lived_row["entry_price"]),
                "lived_exit_price": None if pd.isna(lived_row["exit_price"]) else float(lived_row["exit_price"]),
                "lived_net_pnl_usd": our_pnl,
                "lived_win": None if our_pnl is None else our_pnl > 0,
                "external_position_uid": ext.get("position_uid"),
                "external_trader_id": ext.get("trader_id"),
                "external_source": ext.get("source"),
                "external_side": ext["side"],
                "external_entry_ts": ext["entry_ts"].isoformat().replace("+00:00", "Z"),
                "external_exit_ts": ext["exit_ts"].isoformat().replace("+00:00", "Z"),
                "external_entry_price": None if pd.isna(ext["entry_price"]) else float(ext["entry_price"]),
                "external_exit_price": None if pd.isna(ext["exit_price"]) else float(ext["exit_price"]),
                "external_pnl_quote": their_pnl,
                "external_win": None if their_pnl is None else their_pnl > 0,
                "both_win": bool(our_pnl is not None and their_pnl is not None and our_pnl > 0 and their_pnl > 0),
                "both_lose": bool(our_pnl is not None and their_pnl is not None and our_pnl < 0 and their_pnl < 0),
                "pnl_sign_agree": bool(
                    our_pnl is not None and their_pnl is not None and ((our_pnl > 0) == (their_pnl > 0))
                ),
            }
        )

    they_skipped_rows: list[dict[str, Any]] = []
    for _, ext in E.iterrows():
        if int(ext["_ext_idx"]) in matched_ext:
            continue
        their_pnl = float(ext["pnl_quote"]) if pd.notna(ext["pnl_quote"]) else None
        they_skipped_rows.append(
            {
                "align_class": CLASS_THEY_TOOK_WE_SKIPPED,
                "external_position_uid": ext.get("position_uid"),
                "external_trader_id": ext.get("trader_id"),
                "external_source": ext.get("source"),
                "external_side": ext["side"],
                "external_entry_ts": ext["entry_ts"].isoformat().replace("+00:00", "Z"),
                "external_exit_ts": ext["exit_ts"].isoformat().replace("+00:00", "Z"),
                "external_entry_price": None if pd.isna(ext["entry_price"]) else float(ext["entry_price"]),
                "external_exit_price": None if pd.isna(ext["exit_price"]) else float(ext["exit_price"]),
                "external_pnl_quote": their_pnl,
                "external_win": None if their_pnl is None else their_pnl > 0,
            }
        )

    we_skipped_rows: list[dict[str, Any]] = []
    for _, lived_row in L.iterrows():
        if int(lived_row["_lived_idx"]) in matched_lived:
            continue
        our_pnl = float(lived_row["net_pnl_usd"]) if pd.notna(lived_row["net_pnl_usd"]) else None
        we_skipped_rows.append(
            {
                "align_class": CLASS_WE_TOOK_THEY_SKIPPED,
                "lived_trade_id": lived_row.get("trade_id"),
                "lived_side": lived_row["side"],
                "lived_entry_ts": lived_row["entry_ts"].isoformat().replace("+00:00", "Z"),
                "lived_exit_ts": lived_row["exit_ts"].isoformat().replace("+00:00", "Z"),
                "lived_entry_price": None if pd.isna(lived_row["entry_price"]) else float(lived_row["entry_price"]),
                "lived_exit_price": None if pd.isna(lived_row["exit_price"]) else float(lived_row["exit_price"]),
                "lived_net_pnl_usd": our_pnl,
                "lived_win": None if our_pnl is None else our_pnl > 0,
                "lifecycle_episode_id": lived_row.get("lifecycle_episode_id"),
                "exit_reason": lived_row.get("exit_reason"),
            }
        )

    pairs_df = pd.DataFrame(pairs) if pairs else pd.DataFrame()
    they_df = pd.DataFrame(they_skipped_rows) if they_skipped_rows else pd.DataFrame()
    we_df = pd.DataFrame(we_skipped_rows) if we_skipped_rows else pd.DataFrame()

    agreed = pairs_df[pairs_df["align_class"] == CLASS_WE_AGREED] if len(pairs_df) else pairs_df
    opposite = pairs_df[pairs_df["align_class"] == CLASS_OPPOSITE] if len(pairs_df) else pairs_df

    def _win_rate(frame: pd.DataFrame, col: str) -> float | None:
        if not len(frame) or col not in frame.columns:
            return None
        s = frame[col].dropna()
        if not len(s):
            return None
        return float(s.mean())

    summary = {
        "generated_at": _utc_now(),
        "align_version": ALIGN_VERSION,
        "stage": "ETLL_BTC_M15_ALIGN",
        "config": {
            "match_bars": cfg.match_bars,
            "match_window_minutes": cfg.match_bars * 15,
            "require_interval_overlap": cfg.require_interval_overlap,
            "timeframe": "M15",
        },
        "counts": {
            "lived_trades": int(len(L)),
            "external_ok_btc": int(len(E)),
            "WE_AGREED": int(len(agreed)),
            "OPPOSITE": int(len(opposite)),
            "THEY_TOOK_WE_SKIPPED": int(len(they_df)),
            "WE_TOOK_THEY_SKIPPED": int(len(we_df)),
            "lived_matched": int(len(matched_lived)),
            "external_matched": int(len(matched_ext)),
        },
        "coverage": {
            "external_match_rate": float(len(matched_ext) / len(E)) if len(E) else None,
            "lived_match_rate": float(len(matched_lived) / len(L)) if len(L) else None,
        },
        "agreed_outcomes": {
            "pairs": int(len(agreed)),
            "unique_lived_trades": int(agreed["lived_trade_id"].nunique()) if len(agreed) else 0,
            "unique_external_positions": int(agreed["external_position_uid"].nunique()) if len(agreed) else 0,
            "both_win": int(agreed["both_win"].sum()) if len(agreed) else 0,
            "both_lose": int(agreed["both_lose"].sum()) if len(agreed) else 0,
            "pnl_sign_agree": int(agreed["pnl_sign_agree"].sum()) if len(agreed) else 0,
            "pnl_sign_agree_rate": float(agreed["pnl_sign_agree"].mean()) if len(agreed) else None,
            "lived_win_rate_pairs": _win_rate(agreed, "lived_win"),
            "lived_win_rate_unique": (
                float(agreed.drop_duplicates("lived_trade_id")["lived_win"].mean())
                if len(agreed)
                else None
            ),
            "external_win_rate": _win_rate(agreed, "external_win"),
            "lived_net_pnl_usd_sum_unique": (
                float(agreed.drop_duplicates("lived_trade_id")["lived_net_pnl_usd"].sum())
                if len(agreed)
                else 0.0
            ),
            "external_pnl_quote_sum": float(agreed["external_pnl_quote"].sum()) if len(agreed) else 0.0,
            "median_abs_entry_delta_bars": (
                float(agreed["entry_delta_bars_m15"].abs().median()) if len(agreed) else None
            ),
            "interval_overlap_rate": float(agreed["interval_overlap"].mean()) if len(agreed) else None,
        },
        "they_skipped_outcomes": {
            "external_win_rate": _win_rate(they_df, "external_win"),
            "external_pnl_quote_sum": float(they_df["external_pnl_quote"].sum()) if len(they_df) else 0.0,
            "external_wins": int((they_df["external_win"] == True).sum()) if len(they_df) else 0,  # noqa: E712
            "external_losses": int((they_df["external_win"] == False).sum()) if len(they_df) else 0,  # noqa: E712
        },
        "we_skipped_outcomes": {
            "lived_win_rate": _win_rate(we_df, "lived_win"),
            "lived_net_pnl_usd_sum": float(we_df["lived_net_pnl_usd"].sum()) if len(we_df) else 0.0,
        },
        "by_trader_agreed": (
            agreed.groupby("external_trader_id")
            .size()
            .sort_values(ascending=False)
            .head(20)
            .to_dict()
            if len(agreed)
            else {}
        ),
        "by_trader_they_skipped_wins": (
            they_df[they_df["external_win"] == True]  # noqa: E712
            .groupby("external_trader_id")
            .size()
            .sort_values(ascending=False)
            .head(20)
            .to_dict()
            if len(they_df)
            else {}
        ),
        "status": "ALIGN_DONE",
        "note_ru": (
            "Только стыковка по окну входа ±N M15. Distill good/bad и Toxic Box — отдельно."
        ),
    }
    return {
        "summary": summary,
        "pairs": pairs_df,
        "they_took_we_skipped": they_df,
        "we_took_they_skipped": we_df,
    }
