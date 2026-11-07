"""Step 5b: what the stack already knew at MFE peak and at origin giveback.

Not a trainer. Not an OPEN gate. Universe is NO_CHASE trades that followed
from origin. CatBoost and holdout stay untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from btc_ml.research.logic1_continuation_fade import attach_fade_timing
from btc_ml.research.logic1_loser_origin import (
    CHASE_NONE,
    PATH_FOLLOWED,
    utc_ns,
)

GIVEBACK_FLAGS = (
    "passive_defense",
    "absorption_volume",
    "exhaustion_volume",
    "failed_or_stalled",
    "efficient_continuation",
    "climax",
)


def load_m15_volume(pack_root: Path) -> pd.DataFrame:
    path = Path(pack_root) / "market_pack_btc_m15" / "context" / "volume_response_state.parquet"
    vol = pd.read_parquet(path)
    vol["_k"] = utc_ns(vol["timestamp"])
    keep = [
        "_k",
        "volume_event",
        "continuation_quality",
        "effort_result_state",
        "climax_state",
        "effort_score",
        "result_score",
        "effort_result_ratio",
        "localized_behavior",
    ]
    have = [c for c in keep if c in vol.columns]
    return vol[have].dropna(subset=["_k"]).sort_values("_k").reset_index(drop=True)


def _bar_open_from_close(close_ts: pd.Series) -> pd.Series:
    return utc_ns(close_ts) - pd.Timedelta(minutes=15)


def _join_volume(events: pd.DataFrame, vol: pd.DataFrame, ts_col: str, prefix: str) -> pd.DataFrame:
    left = events.copy().reset_index(drop=True)
    left["_row"] = np.arange(len(left))
    left["_k"] = _bar_open_from_close(left[ts_col])
    right = vol.rename(columns={c: f"{prefix}_{c}" for c in vol.columns if c != "_k"})
    valid = left["_k"].notna()
    vol_cols = [c for c in right.columns if c.startswith(f"{prefix}_")]
    for col in vol_cols:
        left[col] = pd.Series([pd.NA] * len(left), dtype="object")
    if valid.any():
        piece = pd.merge_asof(
            left.loc[valid, ["_row", "_k"]].sort_values("_k"),
            right.sort_values("_k"),
            on="_k",
            direction="backward",
            allow_exact_matches=True,
        )
        for col in vol_cols:
            if col in piece.columns:
                left.loc[piece["_row"].to_numpy(), col] = piece[col].to_numpy()
    return left.drop(columns=["_k", "_row"], errors="ignore")


def _add_flags(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    cq = frame.get(f"{prefix}_continuation_quality", pd.Series("", index=frame.index)).astype(str)
    ve = frame.get(f"{prefix}_volume_event", pd.Series("", index=frame.index)).astype(str)
    er = frame.get(f"{prefix}_effort_result_state", pd.Series("", index=frame.index)).astype(str)
    cl = frame.get(f"{prefix}_climax_state", pd.Series("", index=frame.index)).astype(str)
    frame[f"{prefix}_passive_defense"] = cq.eq("PASSIVE_DEFENSE")
    frame[f"{prefix}_absorption_volume"] = ve.eq("ABSORPTION_VOLUME")
    frame[f"{prefix}_exhaustion_volume"] = ve.eq("EXHAUSTION_VOLUME")
    frame[f"{prefix}_failed_or_stalled"] = cq.isin(["FAILED_CONTINUATION", "AUCTION_STALLED"])
    frame[f"{prefix}_efficient_continuation"] = er.eq("EFFICIENT_CONTINUATION")
    frame[f"{prefix}_climax"] = ~cl.isin(["NO_CLIMAX", "", "nan", "None"])
    return frame


def attach_peak_giveback_volume(events: pd.DataFrame, m15: pd.DataFrame, pack_root: Path) -> pd.DataFrame:
    timed = attach_fade_timing(events, m15)
    vol = load_m15_volume(pack_root)
    out = timed.copy()
    if "peak_bar_close" in out.columns:
        out = _join_volume(out, vol, "peak_bar_close", "peak")
        out = _add_flags(out, "peak")
    if "giveback_bar_close" in out.columns:
        out = _join_volume(out, vol, "giveback_bar_close", "gb")
        out = _add_flags(out, "gb")
    return out


def _c_masks(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    no_chase = frame["chase_axis"].astype(str).eq(CHASE_NONE)
    followed = frame["path_axis"].astype(str).eq(PATH_FOLLOWED)
    c_loss = no_chase & frame["loser"].astype(bool) & followed
    c_win = no_chase & (pd.to_numeric(frame["R"], errors="coerce") > 0) & followed
    return c_loss, c_win


def _rate(mask: pd.Series, flag: pd.Series) -> dict[str, Any]:
    m = flag.fillna(False).astype(bool)
    n = int(mask.sum())
    hit = int((m & mask).sum())
    return {
        "n_flagged": hit,
        "frac": round(hit / n, 4) if n else None,
    }


def _flag_block(frame: pd.DataFrame, mask: pd.Series, prefix: str) -> dict[str, Any]:
    return {name: _rate(mask, frame[f"{prefix}_{name}"]) for name in GIVEBACK_FLAGS if f"{prefix}_{name}" in frame.columns}


def _combo_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    gave = pd.to_numeric(frame.get("gave_back_after_mfe"), errors="coerce").fillna(0).eq(1)
    efficient = frame.get("gb_efficient_continuation", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    exhaustion = frame.get("gb_exhaustion_volume", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    passive = frame.get("gb_passive_defense", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    failed = frame.get("gb_failed_or_stalled", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    return {
        "giveback_all": gave,
        "giveback_not_efficient": gave & ~efficient,
        "giveback_efficient": gave & efficient,
        "giveback_not_efficient_not_exhaustion": gave & ~efficient & ~exhaustion,
        "giveback_passive_or_failed": gave & (passive | failed),
        "giveback_not_efficient_and_dead_quality": gave & ~efficient & (passive | failed),
    }


def score_combo(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    c_loss, c_win = _c_masks(frame)
    r = pd.to_numeric(frame["R"], errors="coerce")
    tp = frame["exit_reason"].astype(str).str.upper().eq("TP")
    losers = mask & c_loss
    winners = mask & c_win
    tp_hit = winners & tp
    loser_sum = float(r.loc[losers].sum()) if losers.any() else 0.0
    winner_sum = float(r.loc[winners].sum()) if winners.any() else 0.0
    tp_sum = float(r.loc[tp_hit].sum()) if tp_hit.any() else 0.0
    slice_net = loser_sum + winner_sum
    return {
        "losers_hit": int(losers.sum()),
        "losers_sum_r": round(loser_sum, 3),
        "winners_hit": int(winners.sum()),
        "winners_sum_r": round(winner_sum, 3),
        "tp_hit": int(tp_hit.sum()),
        "tp_sum_r": round(tp_sum, 3),
        "slice_net_r": round(slice_net, 3),
        "flatten_erases_positive_slice": bool(slice_net > 0),
    }


def summarize_giveback_combos(frame: pd.DataFrame) -> dict[str, Any]:
    c_loss, c_win = _c_masks(frame)
    combos = {name: score_combo(frame, mask) for name, mask in _combo_masks(frame).items()}
    usable = [
        name
        for name, row in combos.items()
        if name != "giveback_efficient"
        and row["losers_hit"] > 0
        and not row["flatten_erases_positive_slice"]
    ]
    return {
        "segment": "train",
        "holdout": "sealed",
        "question": (
            "Giveback plus not-efficient at the giveback bar, to spare TP recoveries. "
            "Total R is a report. Flattening a still-positive slice is forbidden."
        ),
        "n_c_losers": int(c_loss.sum()),
        "n_c_winners": int(c_win.sum()),
        "combos": combos,
        "combos_whose_slice_is_currently_net_negative": usable,
        "decision": (
            "No live exit. Every giveback combo that still catches losers also sits on a "
            "net-positive winner slice, or catches too few losers to matter."
            if not usable
            else (
                "Candidate slices are net-negative on train, but this is not a live rule yet: "
                "no Optuna, no holdout, no OPEN gate, paper stays down."
            )
        ),
    }


def summarize_giveback(frame: pd.DataFrame) -> dict[str, Any]:
    c_loss, c_win = _c_masks(frame)
    gave = pd.to_numeric(frame.get("gave_back_after_mfe"), errors="coerce").fillna(0).eq(1)
    loss_gave = c_loss & gave
    win_gave = c_win & gave
    n_loss = int(c_loss.sum())
    n_win = int(c_win.sum())
    sl_loss = c_loss & frame["exit_reason"].astype(str).str.upper().eq("SL")
    close_loss = c_loss & frame["exit_reason"].astype(str).str.upper().eq("S41_COMMAND_CLOSE")
    return {
        "segment": "train",
        "holdout": "sealed",
        "universe": "NO_CHASE followed-from-origin trades; volume joined at M15 peak and origin-giveback bars",
        "n_c_losers": n_loss,
        "n_c_winners": n_win,
        "gave_back": {
            "losers": int(loss_gave.sum()),
            "losers_frac": round(float(loss_gave.sum() / n_loss), 4) if n_loss else None,
            "winners": int(win_gave.sum()),
            "winners_frac": round(float(win_gave.sum() / n_win), 4) if n_win else None,
        },
        "losers_who_never_gave_back_exit": {
            "SL": int((c_loss & ~gave & sl_loss).sum()) if n_loss else 0,
            "S41_COMMAND_CLOSE": int((c_loss & ~gave & close_loss).sum()) if n_loss else 0,
            "other": int((c_loss & ~gave & ~sl_loss & ~close_loss).sum()) if n_loss else 0,
        },
        "volume_at_peak": {
            "losers": _flag_block(frame, c_loss, "peak"),
            "winners": _flag_block(frame, c_win, "peak"),
        },
        "volume_at_giveback": {
            "losers_who_gave_back": _flag_block(frame, loss_gave, "gb"),
            "winners_who_gave_back": _flag_block(frame, win_gave, "gb"),
        },
        "origin_giveback_exit_is_not_free": (
            "Flattening when M15 close gives origin back after a ≥50bps push would "
            "also flatten the share of winners who later recovered through TP. "
            "That collateral is the constraint; total R is a report, not the objective."
        ),
        "reading": {
            "peak_volume": (
                "If peak already looks like absorption/failed continuation on losers "
                "but not winners, continuation was dying at the high. If both look the same, "
                "volume at the high does not distinguish C."
            ),
            "giveback_close": (
                "Origin given back on a closed M15 is the first hard invalidation of the "
                "paid thesis. It is an exit reading, not an OPEN filter, and not a 1-bar wait to enter."
            ),
            "do_not_train_yet": (
                "Do not Optuna this into an overlay on total R. Report catch vs winner "
                "collateral first. Do not mix with dead-birth B."
            ),
        },
    }
