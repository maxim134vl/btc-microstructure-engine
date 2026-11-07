#!/usr/bin/env python3
"""Optuna + RandomForest on living-process strength and VSA entry patterns.

Rebuilds nothing live. Reads ETLL pack context. Train folds only; validation
selects; holdout stays sealed unless --evaluate-holdout.

  python3 scripts/research/train_living_context_vsa_optuna.py
  python3 scripts/research/train_living_context_vsa_optuna.py --trials 60
  python3 scripts/research/train_living_context_vsa_optuna.py --evaluate-validation
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.research.living_context_vsa_calibration import (  # noqa: E402
    DEFAULT_PACK,
    build_feature_frame,
    encode_features,
    load_cfg,
    load_split,
    mean_fold_score,
    purged_folds,
    rf_signed_pred,
    score_policy,
    score_signed,
)

ALLOW_ALL: dict[str, Any] = {
    "mode": "vsa_only",
    "min_process_strength": 0.0,
    "allow_accumulation": True,
    "allow_distribution": True,
    "allow_test": True,
    "allow_no_effort": True,
    "allow_absorption": True,
    "allow_shock": True,
    "allow_nr7": True,
    "allow_false_break": True,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def suggest_policy(trial: Any, space: dict[str, list[Any]]) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    for name, choices in space.items():
        policy[name] = trial.suggest_categorical(name, list(choices))
    return policy


def run_optuna(
    train: pd.DataFrame,
    folds: list,
    space: dict[str, list[Any]],
    *,
    trials: int,
    seed: int,
    min_keep_frac: float,
) -> dict[str, Any]:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: Any) -> float:
        policy = suggest_policy(trial, space)
        mean, _ = mean_fold_score(train, policy, folds, min_keep_frac=min_keep_frac)
        return mean

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed, n_startup_trials=min(16, max(6, trials // 3))),
    )
    study.optimize(objective, n_trials=int(trials), show_progress_bar=False)
    best = dict(study.best_params)
    mean, per = mean_fold_score(train, best, folds, min_keep_frac=min_keep_frac)
    return {"best_params": best, "best_mean": mean, "fold_means": per, "n_trials": int(trials)}


def run_rf(
    train: pd.DataFrame,
    folds: list,
    space: dict[str, list[Any]],
    *,
    trials: int,
    seed: int,
    min_keep_frac: float,
) -> dict[str, Any]:
    from sklearn.ensemble import RandomForestRegressor

    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    x_all = encode_features(train)
    y_all = pd.to_numeric(train["fwd_atr_return"], errors="coerce").to_numpy()

    def objective(trial: Any) -> float:
        params = {
            "n_estimators": trial.suggest_categorical("n_estimators", space["n_estimators"]),
            "max_depth": trial.suggest_categorical("max_depth", space["max_depth"]),
            "min_samples_leaf": trial.suggest_categorical("min_samples_leaf", space["min_samples_leaf"]),
        }
        min_abs = float(trial.suggest_categorical("min_abs_pred", space["min_abs_pred"]))
        fold_scores: list[float] = []
        for fit_idx, score_idx in folds:
            model = RandomForestRegressor(
                n_estimators=int(params["n_estimators"]),
                max_depth=None if params["max_depth"] is None else int(params["max_depth"]),
                min_samples_leaf=int(params["min_samples_leaf"]),
                random_state=seed,
                n_jobs=-1,
            )
            xf = x_all.iloc[fit_idx].to_numpy()
            yf = y_all[fit_idx]
            fit_ok = np.isfinite(yf)
            if int(fit_ok.sum()) < 50:
                continue
            model.fit(xf[fit_ok], yf[fit_ok])
            pred = rf_signed_pred(model, x_all.iloc[score_idx], min_abs)
            scored = score_signed(y_all[score_idx], pred, min_keep_frac=min_keep_frac)
            fold_scores.append(float(scored["mean"]))
        return float(np.mean(fold_scores)) if fold_scores else float("-inf")

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed + 7, n_startup_trials=min(10, max(4, trials // 3))),
    )
    study.optimize(objective, n_trials=int(trials), show_progress_bar=False)
    best = dict(study.best_params)
    model = RandomForestRegressor(
        n_estimators=int(best["n_estimators"]),
        max_depth=None if best["max_depth"] is None else int(best["max_depth"]),
        min_samples_leaf=int(best["min_samples_leaf"]),
        random_state=seed,
        n_jobs=-1,
    )
    ok = np.isfinite(y_all)
    model.fit(x_all.to_numpy()[ok], y_all[ok])
    names = list(x_all.columns)
    importance = {
        names[i]: round(float(model.feature_importances_[i]), 6)
        for i in np.argsort(model.feature_importances_)[::-1]
    }
    return {
        "best_params": best,
        "best_mean": float(study.best_value),
        "feature_importance": importance,
        "n_trials": int(trials),
        "model": model,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--rf-trials", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--evaluate-validation", action="store_true")
    parser.add_argument("--evaluate-holdout", action="store_true")
    parser.add_argument("--skip-rf", action="store_true")
    args = parser.parse_args()

    cfg = load_cfg()
    split = load_split()
    horizon = int(cfg.get("horizon_bars") or 4)
    min_keep = float(cfg.get("min_keep_frac") or 0.05)
    delta_floor = float(cfg.get("candidate_min_delta_mean") or 0.02)
    frame = build_feature_frame(pack_dir=args.pack_dir, horizon_bars=horizon)
    labeled = frame.loc[frame["fwd_atr_return"].notna()].copy()
    train = labeled.loc[labeled["segment"] == "train"].copy()
    validation = labeled.loc[labeled["segment"] == "validation"].copy()
    holdout = labeled.loc[labeled["segment"] == "holdout"].copy()
    purge_days = int(split.get("purge", {}).get("days") or 7)
    folds = purged_folds(train["timestamp"], n_folds=4, purge_days=purge_days)
    baseline = score_policy(train, ALLOW_ALL, min_keep_frac=min_keep)

    out_dir = args.pack_dir / "context" / "living_vsa_calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "generated_at": _utc_now(),
        "pack_dir": str(args.pack_dir),
        "horizon_bars": horizon,
        "rows": {
            "all_labeled": int(len(labeled)),
            "train": int(len(train)),
            "validation": int(len(validation)),
            "holdout": int(len(holdout)),
            "purged": int((labeled["segment"] == "purged").sum()),
        },
        "baseline_vsa_only": baseline,
        "folds": int(len(folds)),
        "live_cognition_touched": False,
        "holdout_opened": False,
    }
    if not folds:
        report["status"] = "NO_FOLDS"
        (out_dir / "living_context_vsa_optuna_train.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1

    print(f"optuna: {args.trials} trials on {len(train)} train bars, {len(folds)} folds")
    optuna_result = run_optuna(
        train,
        folds,
        cfg["search_space"],
        trials=args.trials,
        seed=args.seed,
        min_keep_frac=min_keep,
    )
    report["optuna"] = {k: v for k, v in optuna_result.items() if k != "model"}
    train_best = score_policy(train, optuna_result["best_params"], min_keep_frac=min_keep)
    report["optuna"]["train_score"] = train_best
    report["optuna"]["delta_vs_baseline"] = round(
        float(train_best["mean"]) - float(baseline["mean"]), 6
    )

    optuna_cv = float(optuna_result["best_mean"])
    baseline_mean = float(baseline["mean"])
    optuna_delta = optuna_cv - baseline_mean
    report["optuna"]["cv_delta_vs_baseline"] = round(optuna_delta, 6)

    candidate = None
    reason = "no candidate"
    if optuna_delta >= delta_floor and train_best.get("rejected") is None:
        candidate = {"kind": "optuna_rule", "policy": optuna_result["best_params"]}
        reason = "optuna rule beat VSA-only baseline on purged train folds"

    if not args.skip_rf:
        print(f"random forest: {args.rf_trials} trials")
        rf_result = run_rf(
            train,
            folds,
            cfg["rf"],
            trials=args.rf_trials,
            seed=args.seed,
            min_keep_frac=min_keep,
        )
        model = rf_result.pop("model")
        x_train = encode_features(train)
        y_train = pd.to_numeric(train["fwd_atr_return"], errors="coerce").to_numpy()
        pred_train = rf_signed_pred(model, x_train, float(rf_result["best_params"]["min_abs_pred"]))
        rf_result["train_score"] = score_signed(y_train, pred_train, min_keep_frac=min_keep)
        rf_cv = float(rf_result["best_mean"])
        rf_result["cv_delta_vs_baseline"] = round(rf_cv - baseline_mean, 6)
        report["random_forest"] = rf_result
        if (
            rf_cv - baseline_mean >= delta_floor
            and rf_cv > optuna_cv + delta_floor
        ):
            candidate = {
                "kind": "random_forest",
                "params": report["random_forest"]["best_params"],
                "feature_importance": report["random_forest"]["feature_importance"],
            }
            reason = "random forest beat the Optuna rule on purged train folds by the detectable floor"
            import joblib

            joblib.dump(model, out_dir / "living_context_vsa_rf.joblib")
        else:
            model = None
    else:
        model = None

    report["candidate"] = candidate
    report["candidate_reason"] = reason
    report["status"] = "CANDIDATE" if candidate else "NO_CANDIDATE"

    if args.evaluate_validation and candidate is not None:
        if candidate["kind"] == "optuna_rule":
            report["validation"] = score_policy(
                validation, candidate["policy"], min_keep_frac=min_keep
            )
        elif model is not None:
            pred = rf_signed_pred(
                model,
                encode_features(validation),
                float(candidate["params"]["min_abs_pred"]),
            )
            y = pd.to_numeric(validation["fwd_atr_return"], errors="coerce").to_numpy()
            report["validation"] = score_signed(y, pred, min_keep_frac=min_keep)
        val_base = score_policy(validation, ALLOW_ALL, min_keep_frac=min_keep)
        report["validation_baseline"] = val_base
        val_mean = float(report["validation"]["mean"])
        if val_mean - float(val_base["mean"]) < delta_floor:
            report["status"] = "REJECTED_ON_VALIDATION"
            report["candidate"] = None
            report["candidate_reason"] = "train fold win did not survive validation"

    if args.evaluate_holdout:
        if report.get("candidate") is None:
            report["holdout"] = {"status": "SKIPPED_NO_CANDIDATE"}
        else:
            report["holdout_opened"] = True
            if report["candidate"]["kind"] == "optuna_rule":
                report["holdout"] = score_policy(
                    holdout, report["candidate"]["policy"], min_keep_frac=min_keep
                )
            elif model is not None:
                pred = rf_signed_pred(
                    model,
                    encode_features(holdout),
                    float(report["candidate"]["params"]["min_abs_pred"]),
                )
                y = pd.to_numeric(holdout["fwd_atr_return"], errors="coerce").to_numpy()
                report["holdout"] = score_signed(y, pred, min_keep_frac=min_keep)

    path = out_dir / "living_context_vsa_optuna_train.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "random_forest" or True}, indent=2, ensure_ascii=False))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
