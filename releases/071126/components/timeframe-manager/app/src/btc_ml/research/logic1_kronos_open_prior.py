"""Kronos OPEN prior: mockable closed-bar features and an ALLOW/BLOCK overlay.

Phase 1–2: no HuggingFace, no torch, no live S4.1. A later predictor must
implement ``predict_terminals`` with the same contract as ``mock_predict_terminals``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
CFG_PATH = ROOT / "config/research/logic1_kronos_open_prior.json"

TF_SECONDS = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}
PRED_LEN_BY_TF = {"M15": 8, "M30": 6, "H1": 4, "H4": 2}
LOOKBACK_BARS = 400
SAMPLE_COUNT = 8
FORMING_MARKERS = {"FORMING_BAR_CONTEXT"}
ATOMIC_FLIP_MARKERS = {"ATOMIC_FLIP_OPEN"}
OPEN_SIDES = {"LONG", "SHORT"}

ALLOW_ALL: dict[str, Any] = {
    "block_if_agree_frac_lt": 0.0,
    "block_if_disagreement_gt": 1.0,
    "block_if_vol_ratio_lt": 0.0,
    "block_if_sign_against": False,
    "block_challenged_unless_agree_gte": 0.0,
}

FEATURE_COLUMNS = (
    "kronos_sign",
    "kronos_agree_frac",
    "kronos_disagreement",
    "kronos_move_bps",
    "kronos_path_width_atr",
    "kronos_vol_ratio",
    "kronos_ok",
    "kronos_illegal_forming",
)


def load_candidate_config(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CFG_PATH).read_text(encoding="utf-8"))


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _reason_blob(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return " ".join(_upper(x) for x in value)
    return _upper(value)


def is_forming_context(
    reason_codes: Any = None,
    context_bar_kind: Any = None,
) -> bool:
    kind = _upper(context_bar_kind)
    if kind in FORMING_MARKERS or kind == "FORMING":
        return True
    blob = _reason_blob(reason_codes)
    return any(mark in blob for mark in FORMING_MARKERS)


def is_atomic_flip(reason_codes: Any = None, extra_reasons: Any = None) -> bool:
    blob = f"{_reason_blob(reason_codes)} {_reason_blob(extra_reasons)}"
    return any(mark in blob for mark in ATOMIC_FLIP_MARKERS)


def last_closed_bar_open(source_bar_close: Any, timeframe: str) -> pd.Timestamp | None:
    close = pd.to_datetime(source_bar_close, utc=True, errors="coerce")
    seconds = TF_SECONDS.get(_upper(timeframe))
    if pd.isna(close) or not seconds:
        return None
    return close - pd.Timedelta(seconds=int(seconds))


def select_closed_lookback(
    bars: pd.DataFrame,
    *,
    source_bar_close: Any,
    timeframe: str,
    lookback_bars: int = LOOKBACK_BARS,
) -> pd.DataFrame:
    """Bars whose open is at or before the closed bar. Next-bar open is excluded.

    Forming is not handled here: callers must refuse FORMING_BAR_CONTEXT first.
    """
    last_open = last_closed_bar_open(source_bar_close, timeframe)
    if last_open is None or bars is None or bars.empty or "timestamp" not in bars.columns:
        return pd.DataFrame(columns=list(bars.columns) if bars is not None else [])
    stamps = pd.to_datetime(bars["timestamp"], utc=True, errors="coerce")
    cutoff = pd.Timestamp(source_bar_close)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    # Closed bar open <= last_open. Never take the next bar's open (== source_bar_close).
    mask = stamps.notna() & (stamps <= last_open) & (stamps < cutoff)
    window = bars.loc[mask].sort_values("timestamp")
    n = int(lookback_bars)
    if n > 0:
        window = window.tail(n)
    return window.reset_index(drop=True)


def lookback_is_causal(
    window: pd.DataFrame,
    *,
    source_bar_close: Any,
    timeframe: str,
) -> bool:
    if window is None or window.empty:
        return True
    last_open = last_closed_bar_open(source_bar_close, timeframe)
    if last_open is None:
        return False
    stamps = pd.to_datetime(window["timestamp"], utc=True, errors="coerce")
    cutoff = pd.Timestamp(source_bar_close)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    if bool((stamps >= cutoff).any()):
        return False
    if bool((stamps > last_open).any()):
        return False
    return True


def mock_terminal_closes(
    *,
    last_close: float,
    moves_bps: Sequence[float],
) -> np.ndarray:
    last = float(last_close)
    moves = np.asarray(list(moves_bps), dtype=float)
    return last * (1.0 + moves / 1e4)


def mock_predict_terminals(
    *,
    last_close: float,
    n_paths: int = SAMPLE_COUNT,
    mode: str,
    move_bps: float = 50.0,
    vol_ratio: float = 1.0,
    lookback_volume_median: float = 100.0,
) -> dict[str, np.ndarray]:
    """Three clouds used by phase-2 tests: with / against / split, relative to LONG.

    ``with``: every path closes above last_close.
    ``against``: every path closes below last_close.
    ``split``: half up, half down.
    """
    n = int(n_paths)
    if n < 2:
        raise ValueError("n_paths must be >= 2")
    key = str(mode or "").strip().lower()
    mag = abs(float(move_bps))
    if key == "with":
        moves = np.full(n, mag, dtype=float)
    elif key == "against":
        moves = np.full(n, -mag, dtype=float)
    elif key == "split":
        half = n // 2
        moves = np.concatenate(
            [np.full(half, mag, dtype=float), np.full(n - half, -mag, dtype=float)]
        )
    else:
        raise ValueError(f"unknown mock mode: {mode}")
    terminals = mock_terminal_closes(last_close=last_close, moves_bps=moves)
    volumes = np.full(n, float(lookback_volume_median) * float(vol_ratio), dtype=float)
    return {"terminal_close": terminals, "terminal_volume": volumes, "moves_bps": moves}


def features_from_cloud(
    *,
    last_close: float,
    terminal_close: Sequence[float],
    terminal_volume: Sequence[float] | None,
    lookback_volume_median: float,
    lookback_atr: float,
    side: str,
) -> dict[str, float | int | bool]:
    closes = np.asarray(list(terminal_close), dtype=float)
    last = float(last_close)
    side_u = _upper(side)
    empty = {
        "kronos_sign": 0,
        "kronos_agree_frac": float("nan"),
        "kronos_disagreement": float("nan"),
        "kronos_move_bps": float("nan"),
        "kronos_path_width_atr": float("nan"),
        "kronos_vol_ratio": float("nan"),
        "kronos_ok": False,
        "kronos_illegal_forming": False,
    }
    if last <= 0 or closes.size == 0 or not np.isfinite(closes).all() or side_u not in OPEN_SIDES:
        return empty
    mean_close = float(np.mean(closes))
    move_bps = (mean_close / last - 1.0) * 1e4
    if move_bps > 1e-9:
        sign = 1
    elif move_bps < -1e-9:
        sign = -1
    else:
        sign = 0
    if side_u == "LONG":
        agree = float(np.mean(closes > last))
    else:
        agree = float(np.mean(closes < last))
    disagreement = 1.0 - abs(2.0 * agree - 1.0)
    p90 = float(np.quantile(closes, 0.90))
    p10 = float(np.quantile(closes, 0.10))
    atr = float(lookback_atr)
    width_atr = (p90 - p10) / atr if atr > 1e-12 else float("nan")
    vols = (
        np.asarray(list(terminal_volume), dtype=float)
        if terminal_volume is not None
        else np.asarray([], dtype=float)
    )
    vol_med = float(lookback_volume_median)
    if vols.size and np.isfinite(vols).all() and vol_med > 1e-12:
        vol_ratio = float(np.mean(vols) / vol_med)
    else:
        vol_ratio = float("nan")
    return {
        "kronos_sign": int(sign),
        "kronos_agree_frac": float(agree),
        "kronos_disagreement": float(disagreement),
        "kronos_move_bps": float(move_bps),
        "kronos_path_width_atr": float(width_atr) if np.isfinite(width_atr) else float("nan"),
        "kronos_vol_ratio": float(vol_ratio) if np.isfinite(vol_ratio) else float("nan"),
        "kronos_ok": True,
        "kronos_illegal_forming": False,
    }


def nan_features(*, illegal_forming: bool = False) -> dict[str, float | int | bool]:
    return {
        "kronos_sign": 0,
        "kronos_agree_frac": float("nan"),
        "kronos_disagreement": float("nan"),
        "kronos_move_bps": float("nan"),
        "kronos_path_width_atr": float("nan"),
        "kronos_vol_ratio": float("nan"),
        "kronos_ok": False,
        "kronos_illegal_forming": bool(illegal_forming),
    }


def attach_kronos_features(
    events: pd.DataFrame,
    clouds: Sequence[Mapping[str, Any] | None],
) -> pd.DataFrame:
    """Map one cloud per existing OPEN row. Never inserts a trade."""
    if len(clouds) != len(events):
        raise ValueError("clouds must align 1:1 with events; cannot invent or drop OPENs")
    rows: list[dict[str, float | int | bool]] = []
    for event, cloud in zip(events.itertuples(index=False), clouds):
        forming = is_forming_context(
            getattr(event, "reason_codes", None),
            getattr(event, "context_bar_kind", None),
        )
        if forming:
            rows.append(nan_features(illegal_forming=True))
            continue
        if cloud is None:
            rows.append(nan_features())
            continue
        feats = features_from_cloud(
            last_close=float(cloud["last_close"]),
            terminal_close=cloud["terminal_close"],
            terminal_volume=cloud.get("terminal_volume"),
            lookback_volume_median=float(cloud.get("lookback_volume_median") or 0.0),
            lookback_atr=float(cloud.get("lookback_atr") or 0.0),
            side=str(getattr(event, "side")),
        )
        rows.append(feats)
    extra = pd.DataFrame(rows)
    out = events.reset_index(drop=True).copy()
    for col in FEATURE_COLUMNS:
        out[col] = extra[col].to_numpy()
    return out


def allow_mask(frame: pd.DataFrame, policy: Mapping[str, Any] | None = None) -> np.ndarray:
    """Fail-open: missing Kronos, forming, or ATOMIC_FLIP never blocks."""
    cfg = {**ALLOW_ALL, **dict(policy or {})}
    n = len(frame)
    kept = np.ones(n, dtype=bool)
    if n == 0:
        return kept

    reasons = frame["reason_codes"] if "reason_codes" in frame.columns else [None] * n
    extra = frame["extra_reasons"] if "extra_reasons" in frame.columns else [None] * n
    kinds = frame["context_bar_kind"] if "context_bar_kind" in frame.columns else [None] * n
    phases = (
        frame["lifecycle_phase"].astype(str).str.upper()
        if "lifecycle_phase" in frame.columns
        else pd.Series([""] * n)
    )
    flip = np.array(
        [is_atomic_flip(r, e) for r, e in zip(reasons, extra)],
        dtype=bool,
    )
    forming = np.array(
        [is_forming_context(r, k) for r, k in zip(reasons, kinds)],
        dtype=bool,
    )
    if "kronos_illegal_forming" in frame.columns:
        forming = forming | frame["kronos_illegal_forming"].fillna(False).to_numpy(dtype=bool)

    ok = (
        frame["kronos_ok"].fillna(False).to_numpy(dtype=bool)
        if "kronos_ok" in frame.columns
        else np.zeros(n, dtype=bool)
    )
    gated = ok & ~flip & ~forming

    agree = (
        pd.to_numeric(frame["kronos_agree_frac"], errors="coerce").to_numpy()
        if "kronos_agree_frac" in frame.columns
        else np.full(n, np.nan)
    )
    disagree = (
        pd.to_numeric(frame["kronos_disagreement"], errors="coerce").to_numpy()
        if "kronos_disagreement" in frame.columns
        else np.full(n, np.nan)
    )
    vol_ratio = (
        pd.to_numeric(frame["kronos_vol_ratio"], errors="coerce").to_numpy()
        if "kronos_vol_ratio" in frame.columns
        else np.full(n, np.nan)
    )
    sign = (
        pd.to_numeric(frame["kronos_sign"], errors="coerce").to_numpy()
        if "kronos_sign" in frame.columns
        else np.zeros(n)
    )
    side = frame["side"].astype(str).str.upper().to_numpy() if "side" in frame.columns else np.array([""] * n)

    missing = ~np.isfinite(agree)
    kept[gated & missing] = True

    agree_lt = float(cfg.get("block_if_agree_frac_lt") or 0.0)
    if agree_lt > 0:
        hit = gated & np.isfinite(agree) & (agree < agree_lt)
        kept &= ~hit

    disagree_gt = float(cfg.get("block_if_disagreement_gt") or 1.0)
    if disagree_gt < 1.0:
        hit = gated & np.isfinite(disagree) & (disagree > disagree_gt)
        kept &= ~hit

    vol_lt = float(cfg.get("block_if_vol_ratio_lt") or 0.0)
    if vol_lt > 0:
        hit = gated & np.isfinite(vol_ratio) & (vol_ratio < vol_lt)
        kept &= ~hit

    if bool(cfg.get("block_if_sign_against")):
        against = ((side == "LONG") & (sign < 0)) | ((side == "SHORT") & (sign > 0))
        kept &= ~(gated & against)

    challenged_floor = float(cfg.get("block_challenged_unless_agree_gte") or 0.0)
    if challenged_floor > 0:
        challenged = phases.to_numpy() == "CHALLENGED"
        weak = gated & challenged & np.isfinite(agree) & (agree < challenged_floor)
        kept &= ~weak
    return kept


def score_policy(
    frame: pd.DataFrame,
    policy: Mapping[str, Any] | None = None,
    *,
    min_keep_frac: float = 0.35,
) -> dict[str, Any]:
    r = pd.to_numeric(frame["R"], errors="coerce").to_numpy()
    baseline_total = float(np.nansum(r))
    kept = allow_mask(frame, policy)
    n = int(len(frame))
    n_kept = int(kept.sum())
    frac = (n_kept / n) if n else 0.0
    if n == 0 or frac < float(min_keep_frac):
        return {
            "n": n,
            "n_kept": n_kept,
            "keep_frac": round(frac, 4),
            "total_r": float("-inf"),
            "delta_total_r": float("-inf"),
            "mean_r": None,
            "wr": None,
            "blocked_mean_r": None,
            "rejected": "keep_frac_below_floor",
        }
    kept_r = r[kept]
    blocked_r = r[~kept]
    total = float(np.nansum(kept_r))
    return {
        "n": n,
        "n_kept": n_kept,
        "keep_frac": round(frac, 4),
        "total_r": round(total, 4),
        "delta_total_r": round(total - baseline_total, 4),
        "mean_r": round(float(np.nanmean(kept_r)), 4) if n_kept else None,
        "wr": round(float(np.mean(kept_r > 0)), 4) if n_kept else None,
        "blocked_mean_r": round(float(np.nanmean(blocked_r)), 4) if (~kept).any() else None,
        "rejected": None,
    }
