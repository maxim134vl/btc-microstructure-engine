#!/usr/bin/env python3
"""CatBoost sizing model on the canonical Hybrid tick book.

Objective
---------
Not a trade filter. On this book 71.5% of trades win and the break-even win
probability is 41.5%, so skipping trades destroys profit at any realistic model
quality (measured: AUC 0.65 dropping 20% of trades loses 8.9% of total R, and even a
perfect oracle that drops every loser gains only 38.9%). Reallocating risk across the
same trades converts the identical forecast into a gain instead: at AUC 0.65 a
0.25x-2x sizing curve is worth about +15.6%.

So the model is scored on how well it *ranks* trades by realised R, not on accuracy.

Validation protocol
-------------------
Only the train segment is touched here. Inside it, expanding purged walk-forward
folds: fold k trains on everything before a boundary, drops a 7-day purge window,
then scores the next chunk. The purge matters because a trade can live 92 hours, so
without it a training label overlaps the scoring window in wall time.

The validation segment is for choosing between survivors, and the holdout is opened
once at the very end. Neither is read by this script unless --evaluate-validation is
passed.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

MATRIX = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/trade_feature_matrix.parquet"
OUT_DIR = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml"
PURGE_DAYS = 7

# Anything that is an outcome, an identifier, or a raw timestamp must never be a
# feature. Prefix-matched so new joins inherit the rule.
DROP_PREFIXES = ("own_", "x", "feed_", "f_")  # kept — these ARE the features
LABEL_COLS = ("R", "win", "net_pnl_usd", "exit_reason", "exit_ts", "exit_ts_raw")
ID_COLS = (
    "trade_id", "position_id", "manager_command_id", "command_id", "lifecycle_episode_id",
    "canonical_episode_id", "timeframe_episode_id", "invalidation_reference",
    "cross_timeframe_metadata", "context_occurrence_timestamp", "source_bar_open",
    "source_bar_close", "source_state_timestamp", "source_event_timestamp",
    "evaluation_timestamp", "context_started_at", "context_started_at_ts",
    "entry_ts", "cutoff", "bar_open", "segment",
)
# Entry bookkeeping that would let the model read the book's own sizing decisions.
LEAK_COLS = (
    "quantity", "notional_usd", "risk_amount_usd", "equity_at_entry_usd",
    "requested_risk_usd", "approved_risk_usd", "net_pnl_usd",
)


def feature_columns(m: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Feature list plus the subset CatBoost must treat as categorical."""
    banned = set(LABEL_COLS) | set(ID_COLS) | set(LEAK_COLS)
    feats: list[str] = []
    for c in m.columns:
        if c in banned or c.endswith("_row_ts"):
            continue
        if not c.startswith(DROP_PREFIXES):
            continue
        if m[c].notna().mean() < 0.02:
            continue
        if m[c].dropna().nunique() <= 1:
            continue  # constant on entries, carries nothing
        feats.append(c)
    cats = [c for c in feats if not pd.api.types.is_numeric_dtype(m[c])]
    return feats, cats


def prepare(m: pd.DataFrame, feats: list[str], cats: list[str]) -> pd.DataFrame:
    x = m[feats].copy()
    for c in cats:
        x[c] = x[c].astype(str).fillna("NA").replace({"None": "NA", "nan": "NA", "<NA>": "NA"})
    for c in feats:
        if c not in cats:
            x[c] = pd.to_numeric(x[c], errors="coerce").astype(float)
    return x


def purged_folds(entry: pd.Series, n_folds: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding folds with a PURGE_DAYS gap between fit and score windows."""
    order = np.argsort(entry.values)
    ts = entry.values[order]
    bounds = np.linspace(0, len(ts), n_folds + 2, dtype=int)[1:]
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for k in range(n_folds):
        lo, hi = bounds[k], bounds[k + 1]
        score_idx = order[lo:hi]
        cut = pd.Timestamp(ts[lo]) - pd.Timedelta(days=PURGE_DAYS)
        fit_idx = order[:lo][entry.values[order[:lo]] < cut.to_numpy()]
        if len(fit_idx) < 300 or len(score_idx) < 100:
            continue
        folds.append((fit_idx, score_idx))
    return folds


def sizing_gain(score: np.ndarray, r: np.ndarray, *, lo: float, hi: float) -> float:
    """Total-R uplift from mapping the score's rank onto a risk multiplier."""
    if len(score) < 10 or r.sum() == 0:
        return float("nan")
    rank = (np.argsort(np.argsort(score)) + 0.5) / len(score)
    w = lo + (hi - lo) * rank
    w = w / w.mean()
    return float((w * r).sum() / r.sum() - 1.0)


def evaluate(oof: pd.DataFrame) -> dict[str, Any]:
    from scipy.stats import spearmanr
    from sklearn.metrics import roc_auc_score

    s, r, y = oof["score"].values, oof["R"].values, oof["win"].values
    out: dict[str, Any] = {
        "n": int(len(oof)),
        "auc": round(float(roc_auc_score(y, s)), 4) if len(set(y)) > 1 else None,
        "spearman_vs_r": round(float(spearmanr(s, r).statistic), 4),
        "sizing_gain_mild_pct": round(100 * sizing_gain(s, r, lo=0.5, hi=1.5), 2),
        "sizing_gain_med_pct": round(100 * sizing_gain(s, r, lo=0.25, hi=2.0), 2),
    }
    # Does the ranking actually separate outcomes? Report R by score quintile.
    q = pd.qcut(oof["score"], 5, labels=False, duplicates="drop")
    out["r_by_score_quintile"] = [
        {
            "quintile": int(k),
            "n": int(len(g)),
            "wr_pct": round(float(g["win"].mean()) * 100, 2),
            "mean_r": round(float(g["R"].mean()), 4),
        }
        for k, g in oof.assign(q=q).groupby("q")
    ]
    return out


def run_cv(
    x: pd.DataFrame,
    m: pd.DataFrame,
    cats: list[str],
    params: dict[str, Any],
    folds: list,
    *,
    y: pd.Series | None = None,
    collect_importance: bool = False,
) -> tuple[pd.DataFrame, list[float], pd.Series | None]:
    from catboost import CatBoostClassifier, Pool
    from sklearn.metrics import roc_auc_score

    label = m["win"] if y is None else y
    cat_idx = [x.columns.get_loc(c) for c in cats]
    rows: list[pd.DataFrame] = []
    per_fold: list[float] = []
    imps: list[pd.Series] = []
    for fit_idx, score_idx in folds:
        model = CatBoostClassifier(**params)
        model.fit(Pool(x.iloc[fit_idx], label.iloc[fit_idx], cat_features=cat_idx), verbose=False)
        p = model.predict_proba(Pool(x.iloc[score_idx], cat_features=cat_idx))[:, 1]
        yy = label.iloc[score_idx].values
        per_fold.append(float(roc_auc_score(yy, p)) if len(set(yy)) > 1 else float("nan"))
        if collect_importance:
            imps.append(pd.Series(model.get_feature_importance(), index=x.columns))
        rows.append(
            pd.DataFrame(
                {
                    "score": p,
                    "R": m["R"].iloc[score_idx].values,
                    "win": label.iloc[score_idx].values,
                }
            )
        )
    importance = pd.concat(imps, axis=1).mean(axis=1).sort_values(ascending=False) if imps else None
    return pd.concat(rows, ignore_index=True), per_fold, importance


FILL_DERIVED = ("f_entry_vs_bar_close_bps", "f_entry_vs_context_bps")


def run_study(
    x: pd.DataFrame, m: pd.DataFrame, cats: list[str], folds: list, *, trials: int, seed: int
) -> tuple[dict[str, Any], Any]:
    """Optuna over CatBoost hyperparameters, scored on purged walk-forward folds.

    The objective is the mean per-fold AUC rather than the pooled AUC: pooling lets a
    single easy period carry the score, whereas the mean penalises a configuration that
    only works in one regime. Nothing outside the train segment is read.
    """
    import optuna
    from sklearn.metrics import roc_auc_score

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: Any) -> float:
        params = {
            "iterations": trial.suggest_int("iterations", 250, 1400, step=50),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.12, log=True),
            "depth": trial.suggest_int("depth", 3, 7),
            "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 30.0, log=True),
            "random_strength": trial.suggest_float("random_strength", 0.0, 3.0),
            "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 1.5),
            "border_count": trial.suggest_categorical("border_count", [64, 128, 254]),
            "one_hot_max_size": trial.suggest_categorical("one_hot_max_size", [2, 8, 24]),
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 5, 80),
            "loss_function": "Logloss",
            "random_seed": seed,
            "allow_writing_files": False,
            "thread_count": -1,
        }
        oof, per_fold, _ = run_cv(x, m, cats, params, folds)
        # Report folds one by one so a hopeless configuration can be pruned early.
        for i, a in enumerate(per_fold):
            trial.report(a, i)
        score = float(np.nanmean(per_fold))
        trial.set_user_attr("auc_pooled", float(roc_auc_score(oof["win"], oof["score"])))
        trial.set_user_attr("sizing_gain_med_pct", 100 * sizing_gain(
            oof["score"].values, oof["R"].values, lo=0.25, hi=2.0
        ))
        trial.set_user_attr("auc_per_fold", [round(a, 4) for a in per_fold])
        trial.set_user_attr("auc_fold_std", float(np.nanstd(per_fold)))
        return score

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed, n_startup_trials=20),
        study_name="hybrid_trade_sizing",
    )
    study.optimize(objective, n_trials=trials, show_progress_bar=False)

    best = dict(study.best_params)
    best.update(
        {
            "loss_function": "Logloss",
            "random_seed": seed,
            "allow_writing_files": False,
            "thread_count": -1,
        }
    )
    return best, study


BASE_PARAMS = {
    "iterations": 400,
    "learning_rate": 0.05,
    "depth": 4,
    "l2_leaf_reg": 6.0,
    "loss_function": "Logloss",
    "eval_metric": "AUC",
    "random_seed": 17,
    "allow_writing_files": False,
    "thread_count": -1,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--trials", type=int, default=0, help="0 = baseline probe only")
    parser.add_argument("--out-name", default="sizing_probe.json")
    parser.add_argument(
        "--ablate",
        action="store_true",
        help="score feature families separately to see what the signal actually rests on",
    )
    parser.add_argument("--keep-fill-derived", action="store_true")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    full = pd.read_parquet(args.matrix)
    m = full.loc[full["segment"] == "train"].reset_index(drop=True)
    m = m.loc[m["R"].notna()].reset_index(drop=True)
    feats, cats = feature_columns(m)
    if not args.keep_fill_derived:
        # Dropped by default: measured to be worth only 0.027 AUC while being the one
        # family that could embed directional slippage from the realised fill.
        feats = [c for c in feats if c not in FILL_DERIVED]
        cats = [c for c in cats if c in feats]
    x = prepare(m, feats, cats)
    folds = purged_folds(m["entry_ts"], args.folds)

    print(f"train segment: {len(m)} trades, {len(feats)} features ({len(cats)} categorical)")
    print(f"purged walk-forward: {len(folds)} folds, {PURGE_DAYS}-day purge")
    for i, (f, s) in enumerate(folds, 1):
        print(
            f"  fold {i}: fit {len(f):>5}  score {len(s):>5}   "
            f"fit<= {pd.Timestamp(m['entry_ts'].iloc[f].max()).date()}  "
            f"score {pd.Timestamp(m['entry_ts'].iloc[s].min()).date()}"
            f"->{pd.Timestamp(m['entry_ts'].iloc[s].max()).date()}"
        )

    oof, per_fold, importance = run_cv(x, m, cats, BASE_PARAMS, folds, collect_importance=True)
    result = evaluate(oof)
    result["auc_per_fold"] = [round(a, 4) for a in per_fold]

    # Control: with labels shuffled the same pipeline must land on AUC ~0.50. Anything
    # meaningfully above that is structural leakage rather than signal.
    rng = np.random.default_rng(101)
    shuffled = pd.Series(rng.permutation(m["win"].values), index=m.index)
    _, shuf_folds, _ = run_cv(x, m, cats, BASE_PARAMS, folds, y=shuffled)
    result["shuffled_label_auc_mean"] = round(float(np.nanmean(shuf_folds)), 4)
    result["shuffled_label_auc_per_fold"] = [round(a, 4) for a in shuf_folds]

    report: dict[str, Any] = {
        "stage": "HYBRID_SIZING_CATBOOST_PROBE",
        "segment": "train only (validation and holdout untouched)",
        "trades": int(len(m)),
        "features": len(feats),
        "categorical": len(cats),
        "folds": len(folds),
        "purge_days": PURGE_DAYS,
        "params": BASE_PARAMS,
        "baseline_expectancy_r": round(float(m["R"].mean()), 4),
        "out_of_fold": result,
    }

    print("\nout-of-fold on train:")
    print(f"  AUC              {result['auc']}   per fold {result['auc_per_fold']}")
    print(f"  Spearman vs R    {result['spearman_vs_r']}")
    print(f"  sizing gain mild {result['sizing_gain_mild_pct']:+.2f}%")
    print(f"  sizing gain med  {result['sizing_gain_med_pct']:+.2f}%")
    print(
        f"  CONTROL shuffled-label AUC {result['shuffled_label_auc_mean']} "
        f"(must be ~0.50)   per fold {result['shuffled_label_auc_per_fold']}"
    )
    print("\n  R by predicted-score quintile (rising score should mean rising R):")
    for q in result["r_by_score_quintile"]:
        print(f"    Q{q['quintile'] + 1}  n={q['n']:>4}  WR {q['wr_pct']:>5.1f}%  mean R {q['mean_r']:+.4f}")
    if importance is not None:
        report["top_features"] = {k: round(float(v), 3) for k, v in importance.head(30).items()}
        print("\n  top 20 features by mean importance across folds:")
        for k, v in importance.head(20).items():
            print(f"    {k:<50}{v:>7.2f}")

    if args.ablate:
        # Features derived from the realised fill price are the ones worth doubting: the
        # BBO is observable before sending the order, but a realised fill also embeds
        # slippage that correlates with the direction price is already moving.
        fill_derived = [c for c in feats if c in ("f_entry_vs_bar_close_bps", "f_entry_vs_context_bps")]
        families = {
            "full": feats,
            "no_fill_derived": [c for c in feats if c not in fill_derived],
            "no_cross_timeframe": [c for c in feats if not c.startswith(("xtf_", "xM15_", "xM30_", "xH1_", "xH4_"))],
            "cross_timeframe_only": [c for c in feats if c.startswith(("xtf_", "xM15_", "xM30_", "xH1_", "xH4_"))],
            "own_planes_only": [c for c in feats if c.startswith(("own_", "feed_"))],
            "fill_derived_only": fill_derived,
        }
        print("\nablation (out-of-fold AUC and sizing gain by feature family):")
        print(f"  {'family':<24}{'n_feat':>8}{'AUC':>8}{'spearman':>10}{'gain_med%':>11}")
        report["ablation"] = {}
        for fam, cols in families.items():
            if not cols:
                continue
            sub_cats = [c for c in cats if c in cols]
            o, pf, _ = run_cv(x[cols], m, sub_cats, BASE_PARAMS, folds)
            e = evaluate(o)
            report["ablation"][fam] = {
                "n_features": len(cols),
                "auc": e["auc"],
                "spearman_vs_r": e["spearman_vs_r"],
                "sizing_gain_med_pct": e["sizing_gain_med_pct"],
                "auc_per_fold": [round(a, 4) for a in pf],
            }
            print(
                f"  {fam:<24}{len(cols):>8}{e['auc']:>8.4f}{e['spearman_vs_r']:>10.4f}"
                f"{e['sizing_gain_med_pct']:>11.2f}"
            )

    if args.trials > 0:
        print(f"\noptuna: {args.trials} trials, objective = mean per-fold AUC on train folds")
        best, study = run_study(x, m, cats, folds, trials=args.trials, seed=args.seed)
        bt = study.best_trial
        oof_best, pf_best, imp_best = run_cv(x, m, cats, best, folds, collect_importance=True)
        e_best = evaluate(oof_best)
        report["optuna"] = {
            "trials": len(study.trials),
            "best_params": best,
            "best_mean_fold_auc": round(float(study.best_value), 4),
            "best_auc_pooled": round(float(bt.user_attrs["auc_pooled"]), 4),
            "best_auc_per_fold": bt.user_attrs["auc_per_fold"],
            "best_auc_fold_std": round(float(bt.user_attrs["auc_fold_std"]), 4),
            "best_sizing_gain_med_pct": round(float(bt.user_attrs["sizing_gain_med_pct"]), 2),
            "baseline_mean_fold_auc": round(float(np.nanmean(per_fold)), 4),
            "refit_out_of_fold": e_best,
            "top_features": {k: round(float(v), 3) for k, v in imp_best.head(30).items()}
            if imp_best is not None
            else {},
        }
        print(f"  best mean fold AUC {study.best_value:.4f}  (baseline {np.nanmean(per_fold):.4f})")
        print(f"  pooled AUC         {bt.user_attrs['auc_pooled']:.4f}")
        print(f"  per-fold           {bt.user_attrs['auc_per_fold']}  std {bt.user_attrs['auc_fold_std']:.4f}")
        print(f"  sizing gain med    {e_best['sizing_gain_med_pct']:+.2f}%")
        print("  best params:")
        for k, v in sorted(best.items()):
            if k not in ("loss_function", "allow_writing_files", "thread_count", "random_seed"):
                print(f"    {k:<24}{v}")
        print("\n  R by score quintile at best params:")
        for q in e_best["r_by_score_quintile"]:
            print(f"    Q{q['quintile'] + 1}  n={q['n']:>4}  WR {q['wr_pct']:>5.1f}%  mean R {q['mean_r']:+.4f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / args.out_name).write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    print(f"\nwritten: {OUT_DIR / args.out_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
