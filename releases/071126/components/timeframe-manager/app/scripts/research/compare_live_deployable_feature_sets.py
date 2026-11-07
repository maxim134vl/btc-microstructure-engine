#!/usr/bin/env python3
"""How much of the sizing edge survives if the model may only use live-available data.

The trained model reads seven context planes per timeframe from the research packs.
The live stack does not produce them that way: only M15 has live cognition planes, the
shadow chain that builds four of them runs on a 900s daemon the manager does not wait
for, and cognition_triggers_proxy has no live writer at all. So the full model is
research-only until that pipeline exists.

Three tiers are priced here:

* live_today   — only what the running stack already emits at decision time: the
                 cross-timeframe snapshot the manager writes every cycle, plus values
                 derived from the entry command itself. No new pipeline work.
* live_plus_m15 — adds the M15 candle-structure plane, which is live but M15-only and
                 missing number_of_trades.
* resampled_tf — everything except the pack-only trigger proxy. Reachable by resampling
                 the live M15 feed into M30/H1/H4 and running the existing builders on
                 each, which is pipeline work rather than new research.
* full         — the model as trained, for reference.

Train folds and validation only. Holdout was already spent on the full model, and
re-scoring a different candidate against it would quietly turn a one-shot test into a
selection set.
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

from evaluate_hybrid_sizing_curve import curve_stats, ev_weights  # noqa: E402
from train_hybrid_trade_sizing_catboost import (  # noqa: E402
    FILL_DERIVED,
    feature_columns,
    prepare,
    purged_folds,
)

MATRIX = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/trade_feature_matrix.parquet"
OUT_DIR = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml"
STUDY = OUT_DIR / "sizing_optuna_train.json"
CURVE = (0.5, 1.5)

# Live-writer status established by reading the runtime code, not guessed:
#   xtf_*                     timeframe_command_memory.parquet, every manager cycle, 4 TFs
#   f_*                       derived from the command and book fields present at entry
#   own_candle_structu_*      data/cognition/candle_structure_memory.parquet, M15 only
#   everything else           pack-only, or M15-only via the 900s shadow chain
LIVE_TODAY = ("xtf_", "f_")
PACK_ONLY = ("own_cognition_trig_",)


def tier_features(feats: list[str]) -> dict[str, list[str]]:
    live_today = [c for c in feats if c.startswith(LIVE_TODAY)]
    return {
        "live_today": live_today,
        "live_plus_m15": live_today + [c for c in feats if c.startswith("own_candle_structu_")],
        "resampled_tf": [c for c in feats if not c.startswith(PACK_ONLY)],
        "full": list(feats),
    }


def score_tier(
    full_df: pd.DataFrame, cols: list[str], params: dict[str, Any], folds_n: int
) -> dict[str, Any]:
    from catboost import CatBoostClassifier, Pool
    from sklearn.metrics import roc_auc_score

    tr = full_df.loc[(full_df["segment"] == "train") & full_df["R"].notna()].reset_index(drop=True)
    va = full_df.loc[(full_df["segment"] == "validation") & full_df["R"].notna()].reset_index(drop=True)
    _, all_cats = feature_columns(tr)
    cats = [c for c in all_cats if c in cols]

    xtr, xva = prepare(tr, cols, cats), prepare(va, cols, cats)
    cat_idx = [xtr.columns.get_loc(c) for c in cats]

    # Out-of-fold on train, purged.
    folds = purged_folds(tr["entry_ts"], folds_n)
    oof_p, oof_y = [], []
    for fit_idx, score_idx in folds:
        mdl = CatBoostClassifier(**params)
        mdl.fit(Pool(xtr.iloc[fit_idx], tr["win"].iloc[fit_idx], cat_features=cat_idx), verbose=False)
        oof_p.append(mdl.predict_proba(Pool(xtr.iloc[score_idx], cat_features=cat_idx))[:, 1])
        oof_y.append(tr["win"].iloc[score_idx].values)
    oof_auc = float(roc_auc_score(np.concatenate(oof_y), np.concatenate(oof_p)))

    # Fit on all of train, score validation once.
    mdl = CatBoostClassifier(**params)
    mdl.fit(Pool(xtr, tr["win"], cat_features=cat_idx), verbose=False)
    p = mdl.predict_proba(Pool(xva, cat_features=cat_idx))[:, 1]

    w = float(tr.loc[tr["win"] == 1, "R"].mean())
    loss = abs(float(tr.loc[tr["win"] == 0, "R"].mean()))
    scored = va.assign(p=p).sort_values("exit_ts").reset_index(drop=True)
    size = ev_weights(scored["p"].values, w=w, loss=loss, lo=CURVE[0], hi=CURVE[1])
    flat = curve_stats(scored, np.ones(len(scored)))
    sized = curve_stats(scored, size)
    return {
        "n_features": len(cols),
        "train_oof_auc": round(oof_auc, 4),
        "validation_auc": round(float(roc_auc_score(scored["win"], scored["p"])), 4),
        "validation_flat_r": flat["total_r"],
        "validation_sized_r": sized["total_r"],
        "validation_uplift_pct": round(100 * (sized["total_r"] / flat["total_r"] - 1), 2),
        "validation_maxdd_flat": flat["max_dd_r"],
        "validation_maxdd_sized": sized["max_dd_r"],
        "validation_dd_change_pct": round(100 * (sized["max_dd_r"] / flat["max_dd_r"] - 1), 2)
        if flat["max_dd_r"]
        else None,
    }


def score_holdout(full_df: pd.DataFrame, cols: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Fit on train only and score holdout, mirroring the full model's test exactly.

    Train-only fit (not train+validation) so the number is directly comparable to the
    +13.83% the full model produced on the same trades.
    """
    from catboost import CatBoostClassifier, Pool
    from sklearn.metrics import roc_auc_score

    tr = full_df.loc[(full_df["segment"] == "train") & full_df["R"].notna()].reset_index(drop=True)
    ho = full_df.loc[(full_df["segment"] == "holdout") & full_df["R"].notna()].reset_index(drop=True)
    _, all_cats = feature_columns(tr)
    cats = [c for c in all_cats if c in cols]
    xtr, xho = prepare(tr, cols, cats), prepare(ho, cols, cats)
    cat_idx = [xtr.columns.get_loc(c) for c in cats]

    mdl = CatBoostClassifier(**params)
    mdl.fit(Pool(xtr, tr["win"], cat_features=cat_idx), verbose=False)
    p = mdl.predict_proba(Pool(xho, cat_features=cat_idx))[:, 1]

    w = float(tr.loc[tr["win"] == 1, "R"].mean())
    loss = abs(float(tr.loc[tr["win"] == 0, "R"].mean()))
    scored = ho.assign(p=p).sort_values("exit_ts").reset_index(drop=True)
    size = ev_weights(scored["p"].values, w=w, loss=loss, lo=CURVE[0], hi=CURVE[1])
    flat = curve_stats(scored, np.ones(len(scored)))
    sized = curve_stats(scored, size)
    return {
        "n_features": len(cols),
        "trades": int(len(scored)),
        "span": [str(scored["entry_ts"].min())[:10], str(scored["entry_ts"].max())[:10]],
        "auc": round(float(roc_auc_score(scored["win"], scored["p"])), 4),
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
    parser.add_argument("--out-name", default="live_deployability.json")
    parser.add_argument("--holdout-tier", choices=["live_today", "live_plus_m15", "resampled_tf"])
    args = parser.parse_args()

    if args.holdout_tier:
        params = dict(json.loads(STUDY.read_text(encoding="utf-8"))["optuna"]["best_params"])
        full_df = pd.read_parquet(args.matrix)
        tr0 = full_df.loc[full_df["segment"] == "train"].reset_index(drop=True)
        feats0, _ = feature_columns(tr0)
        feats0 = [c for c in feats0 if c not in FILL_DERIVED]
        cols = tier_features(feats0)[args.holdout_tier]
        r = score_holdout(full_df, cols, params)
        f, s = r["flat"], r["sized"]
        print(f"\nHOLDOUT — tier '{args.holdout_tier}' ({r['n_features']} features), trained on train only")
        print(f"  trades {r['trades']}   span {r['span'][0]} -> {r['span'][1]}   AUC {r['auc']}\n")
        print(f"  {'variant':<12}{'total R':>10}{'maxDD':>9}{'ret/DD':>9}{'worst mo':>10}{'neg mo':>9}")
        print("-" * 59)
        for nm, d in (("flat", f), ("sized", s)):
            print(
                f"  {nm:<12}{d['total_r']:>10.1f}{d['max_dd_r']:>9.1f}"
                f"{d['return_over_maxdd'] or 0:>9.2f}{d['worst_month_r']:>10.1f}"
                f"{d['negative_months']:>6}/{d['months']:<2}"
            )
        print(f"\n  uplift {r['uplift_pct']:+.2f}%   drawdown change {r['dd_change_pct']:+.2f}%")
        out = OUT_DIR / f"holdout_{args.holdout_tier}.json"
        out.write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        print(f"\nwritten: {out}")
        return 0

    params = dict(json.loads(STUDY.read_text(encoding="utf-8"))["optuna"]["best_params"])
    full_df = pd.read_parquet(args.matrix)
    tr = full_df.loc[full_df["segment"] == "train"].reset_index(drop=True)
    feats, _ = feature_columns(tr)
    feats = [c for c in feats if c not in FILL_DERIVED]
    tiers = tier_features(feats)

    print("deployability tiers, scored on train folds and validation (holdout not reused)\n")
    hdr = (
        f"{'tier':<16}{'feats':>7}{'OOF AUC':>10}{'val AUC':>10}"
        f"{'val uplift':>12}{'val DD chg':>12}{'sized R':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    results: dict[str, Any] = {}
    for name, cols in tiers.items():
        r = score_tier(full_df, cols, params, args.folds)
        results[name] = r
        print(
            f"{name:<16}{r['n_features']:>7}{r['train_oof_auc']:>10.4f}{r['validation_auc']:>10.4f}"
            f"{r['validation_uplift_pct']:>11.2f}%{r['validation_dd_change_pct']:>11.2f}%"
            f"{r['validation_sized_r']:>10.1f}"
        )

    report = {
        "stage": "LIVE_DEPLOYABILITY_TIERS",
        "curve": f"{CURVE[0]}-{CURVE[1]}",
        "params": params,
        "note": "holdout deliberately not re-scored; it was already spent on the full model",
        "tiers": results,
        "tier_definitions": {
            "live_today": "cross_timeframe_metadata + entry-derived fields; no new pipeline work",
            "live_plus_m15": "adds live M15 candle_structure_memory",
            "resampled_tf": "all planes except pack-only trigger proxy; needs M15->M30/H1/H4 resample + builders",
            "full": "model as trained on research packs",
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / args.out_name).write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    print(f"\nwritten: {OUT_DIR / args.out_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
