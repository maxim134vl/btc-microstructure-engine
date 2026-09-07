#!/usr/bin/env python3
"""Turn the CatBoost score into a position size and price the result honestly.

Why not rank-based sizing
-------------------------
Scoring by rank inside the evaluated sample needs the whole score distribution up
front, which is not knowable when the trade fires. Every curve here is instead a fixed
function of the predicted probability, calibrated on train only, so it can be applied
to one trade at a time in production.

The size follows expected value. With the train-measured payoff (avg win +W R, avg
loss -L R) a trade with win probability p is worth EV(p) = p*W - (1-p)*L, and risk is
allocated proportionally to that, clipped to a floor and a ceiling and renormalised so
mean risk matches the canonical book. That keeps the comparison honest: the same
average capital at risk, redistributed.

What is reported
----------------
Total R is not enough. A curve that concentrates risk raises variance, and profit
bought with a deeper drawdown is not an improvement, so max drawdown, return over
drawdown and the worst month are reported next to the profit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from train_hybrid_trade_sizing_catboost import (  # noqa: E402
    FILL_DERIVED,
    PURGE_DAYS,
    feature_columns,
    prepare,
    purged_folds,
)

MATRIX = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/trade_feature_matrix.parquet"
OUT_DIR = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml"
STUDY = OUT_DIR / "sizing_optuna_train.json"

CURVES: dict[str, tuple[float, float]] = {
    "flat (canonical)": (1.0, 1.0),
    "mild 0.75-1.25": (0.75, 1.25),
    "mild 0.5-1.5": (0.5, 1.5),
    "medium 0.4-1.8": (0.4, 1.8),
    "medium 0.25-2.0": (0.25, 2.0),
    "aggressive 0.1-2.5": (0.1, 2.5),
    "aggressive 0.0-3.0": (0.0, 3.0),
}


def oof_predictions(m: pd.DataFrame, params: dict[str, Any], folds: list, x: pd.DataFrame, cats: list[str]) -> pd.DataFrame:
    from catboost import CatBoostClassifier, Pool

    cat_idx = [x.columns.get_loc(c) for c in cats]
    out: list[pd.DataFrame] = []
    for fit_idx, score_idx in folds:
        model = CatBoostClassifier(**params)
        model.fit(Pool(x.iloc[fit_idx], m["win"].iloc[fit_idx], cat_features=cat_idx), verbose=False)
        p = model.predict_proba(Pool(x.iloc[score_idx], cat_features=cat_idx))[:, 1]
        out.append(
            pd.DataFrame(
                {
                    "p": p,
                    "R": m["R"].iloc[score_idx].values,
                    "win": m["win"].iloc[score_idx].values,
                    "entry_ts": m["entry_ts"].iloc[score_idx].values,
                    "exit_ts": m["exit_ts"].iloc[score_idx].values,
                    "timeframe": m["timeframe"].iloc[score_idx].values,
                }
            )
        )
    return pd.concat(out, ignore_index=True).sort_values("exit_ts").reset_index(drop=True)


def ev_weights(p: np.ndarray, *, w: float, loss: float, lo: float, hi: float) -> np.ndarray:
    """Expected-value sizing, clipped then renormalised to unit mean risk."""
    ev = p * w - (1.0 - p) * loss
    base = ev.mean()
    if base <= 0:
        return np.ones_like(p)
    size = np.clip(ev / base, lo, hi)
    return size / size.mean()


def curve_stats(frame: pd.DataFrame, size: np.ndarray) -> dict[str, Any]:
    """Equity in R ordered by exit, with drawdown and monthly detail."""
    r = frame["R"].values * size
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    max_dd = float(dd.max()) if len(dd) else 0.0

    monthly = (
        pd.DataFrame({"exit_ts": pd.to_datetime(frame["exit_ts"]), "r": r})
        .set_index("exit_ts")
        .resample("MS")["r"]
        .sum()
    )
    total = float(r.sum())
    # Longest stretch under water, in days.
    under = pd.Series(dd > 1e-9, index=pd.to_datetime(frame["exit_ts"]))
    longest = 0.0
    start = None
    for t, flag in under.items():
        if flag and start is None:
            start = t
        elif not flag and start is not None:
            longest = max(longest, (t - start).total_seconds() / 86400.0)
            start = None
    return {
        "total_r": round(total, 1),
        "mean_size": round(float(size.mean()), 3),
        "max_size": round(float(size.max()), 3),
        "min_size": round(float(size.min()), 3),
        "max_dd_r": round(max_dd, 1),
        "return_over_maxdd": round(total / max_dd, 2) if max_dd > 0 else None,
        "worst_month_r": round(float(monthly.min()), 1) if len(monthly) else None,
        "negative_months": int((monthly < 0).sum()),
        "months": int(len(monthly)),
        "longest_underwater_days": round(longest, 1),
        "r_std_per_trade": round(float(np.std(frame["R"].values * size)), 4),
    }


def evaluate_segment(
    full: pd.DataFrame,
    *,
    segment: str,
    params: dict[str, Any],
    curve: tuple[float, float],
) -> dict[str, Any]:
    """Fit on the whole train segment, score an untouched segment once.

    Everything the curve needs — the payoff constants and the probability->size map —
    is fixed from train before this segment is read, so nothing here is tuned.
    """
    from catboost import CatBoostClassifier, Pool
    from sklearn.metrics import roc_auc_score

    tr = full.loc[(full["segment"] == "train") & full["R"].notna()].reset_index(drop=True)
    te = full.loc[(full["segment"] == segment) & full["R"].notna()].reset_index(drop=True)

    feats, cats = feature_columns(tr)
    feats = [c for c in feats if c not in FILL_DERIVED]
    cats = [c for c in cats if c in feats]
    xtr, xte = prepare(tr, feats, cats), prepare(te, feats, cats)
    cat_idx = [xtr.columns.get_loc(c) for c in cats]

    model = CatBoostClassifier(**params)
    model.fit(Pool(xtr, tr["win"], cat_features=cat_idx), verbose=False)
    p = model.predict_proba(Pool(xte, cat_features=cat_idx))[:, 1]

    w = float(tr.loc[tr["win"] == 1, "R"].mean())
    loss = abs(float(tr.loc[tr["win"] == 0, "R"].mean()))
    lo, hi = curve
    size = ev_weights(p, w=w, loss=loss, lo=lo, hi=hi)

    scored = te.assign(p=p).sort_values("exit_ts").reset_index(drop=True)
    size = ev_weights(scored["p"].values, w=w, loss=loss, lo=lo, hi=hi)
    flat = curve_stats(scored, np.ones(len(scored)))
    sized = curve_stats(scored, size)
    return {
        "segment": segment,
        "trades": int(len(scored)),
        "span": [str(scored["entry_ts"].min()), str(scored["entry_ts"].max())],
        "auc": round(float(roc_auc_score(scored["win"], scored["p"])), 4),
        "train_payoff_used": {"avg_win_r": round(w, 4), "avg_loss_r": round(-loss, 4)},
        "curve": f"{lo}-{hi}",
        "flat": flat,
        "sized": sized,
        "uplift_pct": round(100 * (sized["total_r"] / flat["total_r"] - 1), 2),
        "dd_change_pct": round(100 * (sized["max_dd_r"] / flat["max_dd_r"] - 1), 2)
        if flat["max_dd_r"]
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--out-name", default="sizing_curve_train.json")
    parser.add_argument(
        "--evaluate",
        choices=["validation", "holdout"],
        help="score an untouched segment once with the frozen train configuration",
    )
    parser.add_argument("--curve-lo", type=float, default=0.5)
    parser.add_argument("--curve-hi", type=float, default=1.5)
    args = parser.parse_args()

    if args.evaluate:
        study = json.loads(STUDY.read_text(encoding="utf-8"))
        params = dict(study["optuna"]["best_params"])
        full = pd.read_parquet(args.matrix)
        res = evaluate_segment(
            full, segment=args.evaluate, params=params, curve=(args.curve_lo, args.curve_hi)
        )
        f, s = res["flat"], res["sized"]
        print(f"\n{args.evaluate.upper()} — scored once with the train-frozen configuration")
        print(f"  trades {res['trades']}   span {res['span'][0][:10]} -> {res['span'][1][:10]}")
        print(f"  AUC    {res['auc']}   curve {res['curve']}\n")
        print(f"  {'variant':<12}{'total R':>10}{'maxDD':>9}{'ret/DD':>9}{'worst mo':>10}{'neg mo':>9}")
        print("-" * 59)
        for nm, d in (("flat", f), ("sized", s)):
            print(
                f"  {nm:<12}{d['total_r']:>10.1f}{d['max_dd_r']:>9.1f}"
                f"{d['return_over_maxdd'] or 0:>9.2f}{d['worst_month_r']:>10.1f}"
                f"{d['negative_months']:>6}/{d['months']:<2}"
            )
        print(f"\n  uplift {res['uplift_pct']:+.2f}%   drawdown change {res['dd_change_pct']:+.2f}%")
        out = OUT_DIR / f"sizing_{args.evaluate}.json"
        out.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        print(f"\nwritten: {out}")
        return 0

    study = json.loads(STUDY.read_text(encoding="utf-8"))
    params = dict(study["optuna"]["best_params"])

    full = pd.read_parquet(args.matrix)
    m = full.loc[full["segment"] == "train"].reset_index(drop=True)
    m = m.loc[m["R"].notna()].reset_index(drop=True)
    feats, cats = feature_columns(m)
    feats = [c for c in feats if c not in FILL_DERIVED]
    cats = [c for c in cats if c in feats]
    x = prepare(m, feats, cats)
    folds = purged_folds(m["entry_ts"], args.folds)

    oof = oof_predictions(m, params, folds, x, cats)
    wins = oof.loc[oof["win"] == 1, "R"]
    losses = oof.loc[oof["win"] == 0, "R"]
    w, loss = float(wins.mean()), abs(float(losses.mean()))
    print(f"train OOF: {len(oof)} trades, payoff +{w:.3f}R / -{loss:.3f}R, purge {PURGE_DAYS}d")
    print(f"score range: p {oof['p'].min():.3f} .. {oof['p'].max():.3f}\n")

    base = curve_stats(oof, np.ones(len(oof)))
    rows: dict[str, Any] = {}
    hdr = (
        f"{'curve':<22}{'total R':>10}{'vs flat':>9}{'maxDD':>9}{'ret/DD':>8}"
        f"{'worst mo':>10}{'neg mo':>8}{'uw days':>9}{'size rng':>13}"
    )
    print(hdr)
    print("-" * len(hdr))
    for name, (lo, hi) in CURVES.items():
        size = np.ones(len(oof)) if (lo, hi) == (1.0, 1.0) else ev_weights(
            oof["p"].values, w=w, loss=loss, lo=lo, hi=hi
        )
        s = curve_stats(oof, size)
        s["vs_flat_pct"] = round(100 * (s["total_r"] / base["total_r"] - 1), 2)
        s["dd_vs_flat_pct"] = round(100 * (s["max_dd_r"] / base["max_dd_r"] - 1), 2) if base["max_dd_r"] else None
        rows[name] = s
        print(
            f"{name:<22}{s['total_r']:>10.1f}{s['vs_flat_pct']:>8.1f}%{s['max_dd_r']:>9.1f}"
            f"{s['return_over_maxdd'] or 0:>8.2f}{s['worst_month_r']:>10.1f}"
            f"{s['negative_months']:>5}/{s['months']:<2}{s['longest_underwater_days']:>9.1f}"
            f"{s['min_size']:>6.2f}-{s['max_size']:<6.2f}"
        )

    report = {
        "stage": "HYBRID_SIZING_CURVE_TRAIN",
        "segment": "train only (validation and holdout untouched)",
        "method": "expected-value sizing from a fixed probability->size map calibrated on train",
        "trades": int(len(oof)),
        "payoff": {"avg_win_r": round(w, 4), "avg_loss_r": round(-loss, 4)},
        "best_params": params,
        "curves": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / args.out_name).write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    print(f"\nwritten: {OUT_DIR / args.out_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
