#!/usr/bin/env python3
"""LOGIC1 M15: Optuna over contested-push perception on the Hybrid book.

ACTIVE stays required. OPEN is skipped only when the closed M15 bar already
shows the push being eaten (footprint cluster / rejection / trapped wick / fade).
CatBoost is not trained. Holdout stays sealed unless --evaluate-holdout.

  python3 scripts/research/train_logic1_m15_perception_optuna.py
  python3 scripts/research/train_logic1_m15_perception_optuna.py --trials 80
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
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from btc_ml.research.logic1_m15_perception import (  # noqa: E402
    ALLOW_ALL,
    DEFAULT_FOOTPRINT_DIR,
    MIN_KEEP_FRAC,
    build_m15_open_matrix,
    mean_fold_remaining_losers,
    score_policy,
)
from btc_ml.research.logic1_open_gate import purged_folds, resolve_pack_root  # noqa: E402
from calibration_split import assign_segment, load_split  # noqa: E402

CFG_PATH = ROOT / "config/research/logic1_m15_perception.json"
OUT_DIR = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/logic1"


def load_cfg() -> dict[str, Any]:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def suggest_policy(trial: Any, space: dict[str, list[Any]]) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    for name, choices in space.items():
        policy[name] = trial.suggest_categorical(name, choices)
    if not bool(policy.get("reject_cluster")):
        policy["cluster_vol_share"] = 0.12
    if not any(
        bool(policy.get(k))
        for k in ("reject_fp_opp", "reject_rejection", "reject_cluster", "reject_trapped", "reject_fade")
    ) and float(policy.get("poc_against_max") or 0) == 0:
        # identical to allow-all; keep it legal
        pass
    return policy


def run_study(
    train: pd.DataFrame,
    folds: list,
    space: dict[str, list[Any]],
    *,
    trials: int,
    seed: int,
    min_keep_frac: float,
) -> tuple[dict[str, Any], Any]:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: Any) -> float:
        policy = suggest_policy(trial, space)
        mean_left, per = mean_fold_remaining_losers(train, policy, folds, min_keep_frac=min_keep_frac)
        trial.set_user_attr("policy", policy)
        trial.set_user_attr("fold_remaining_losers", [None if not np.isfinite(v) else int(v) for v in per])
        return mean_left

    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=seed, n_startup_trials=min(20, max(8, trials // 3))),
        study_name="logic1_m15_perception",
    )
    study.enqueue_trial(dict(ALLOW_ALL))
    study.optimize(objective, n_trials=trials, show_progress_bar=False)
    best = dict(study.best_trial.user_attrs.get("policy") or study.best_params)
    return best, study


def _seg(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    return frame.loc[frame["segment"] == name].reset_index(drop=True)


def main() -> int:
    cfg = load_cfg()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--footprint-dir", type=Path, default=DEFAULT_FOOTPRINT_DIR)
    parser.add_argument("--pack-root", type=Path, default=None)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--trials", type=int, default=0)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--out-name", default="logic1_m15_perception_train.json")
    parser.add_argument("--evaluate-validation", action="store_true")
    parser.add_argument("--evaluate-holdout", action="store_true")
    args = parser.parse_args()

    split = load_split()
    pack = resolve_pack_root(args.pack_root, ROOT)
    print("candidate: LOGIC1_M15_PERCEPTION")
    print(f"footprint: {args.footprint_dir}")
    print("catboost:  not used")
    matrix = build_m15_open_matrix(pack_root=pack, footprint_dir=args.footprint_dir)
    matrix["segment"] = assign_segment(matrix, split)
    train = _seg(matrix, "train")
    train = train.loc[train["R"].notna()].reset_index(drop=True)
    min_keep = float(cfg.get("min_keep_frac") or MIN_KEEP_FRAC)
    folds = purged_folds(
        train["entry_ts"],
        args.folds,
        purge_days=int(split["purge"]["days"]),
        min_fit=80,
        min_score=40,
    )

    print(f"M15 opens: {len(matrix)}  train={len(train)}  losers_train={int(train['loss'].sum())}")
    print(f"purged walk-forward: {len(folds)} folds")
    for i, (fit_idx, score_idx) in enumerate(folds, 1):
        print(
            f"  fold {i}: score {len(score_idx):>4}  losers {int(train['loss'].iloc[score_idx].sum()):>3}  "
            f"{pd.Timestamp(train['entry_ts'].iloc[score_idx].min()).date()}"
            f"->{pd.Timestamp(train['entry_ts'].iloc[score_idx].max()).date()}  fit {len(fit_idx)}"
        )

    baseline = score_policy(train, ALLOW_ALL, min_keep_frac=min_keep)
    fold_base, fold_base_per = mean_fold_remaining_losers(train, ALLOW_ALL, folds, min_keep_frac=min_keep)
    probes = {
        "allow_all": ALLOW_ALL,
        "rejection": {**ALLOW_ALL, "reject_rejection": True},
        "trapped": {**ALLOW_ALL, "reject_trapped": True},
        "fade": {**ALLOW_ALL, "reject_fade": True},
        "fp_opp": {**ALLOW_ALL, "reject_fp_opp": True},
        "cluster_12": {**ALLOW_ALL, "reject_cluster": True, "cluster_vol_share": 0.12},
        "contested_core": {
            **ALLOW_ALL,
            "reject_rejection": True,
            "reject_trapped": True,
            "reject_fade": True,
        },
    }
    probe_scores = {name: score_policy(train, pol, min_keep_frac=min_keep) for name, pol in probes.items()}

    print("\ntrain M15 (allow-all = current OPEN):")
    for name, result in probe_scores.items():
        print(
            f"  {name:<16} kept {result['n_kept']}/{result['n']}  "
            f"remainL {result['remaining_losers']}  caughtL {result['losers_caught']}  "
            f"dropW {result['winners_dropped']}  pLoss {result['p_loss_kept']}"
        )

    report: dict[str, Any] = {
        "candidate_id": "LOGIC1_M15_PERCEPTION",
        "timeframe": "M15",
        "segment": "train",
        "holdout": "sealed" if not args.evaluate_holdout else "OPENED",
        "catboost_used": False,
        "n_train": int(len(train)),
        "losers_train": int(train["loss"].sum()),
        "folds": len(folds),
        "baseline": baseline,
        "baseline_mean_fold_remaining_losers": None if not np.isfinite(fold_base) else round(fold_base, 4),
        "baseline_fold_remaining_losers": [int(v) for v in fold_base_per],
        "hand_probes": probe_scores,
    }

    best_policy = dict(ALLOW_ALL)
    optuna_path = OUT_DIR / "logic1_m15_perception_optuna_train.json"
    if args.trials == 0 and (args.evaluate_validation or args.evaluate_holdout) and optuna_path.exists():
        stored = json.loads(optuna_path.read_text(encoding="utf-8"))
        stored_policy = stored.get("optuna", {}).get("best_params")
        if stored_policy:
            best_policy = dict(stored_policy)
            print(f"using stored train policy from {optuna_path.name}")
    if args.trials > 0:
        print(f"\noptuna: {args.trials} trials, minimize mean fold remaining M15 losers")
        best_policy, study = run_study(
            train,
            folds,
            {k: list(v) for k, v in cfg["search_space"].items()},
            trials=args.trials,
            seed=args.seed,
            min_keep_frac=min_keep,
        )
        best_fold, best_per = mean_fold_remaining_losers(train, best_policy, folds, min_keep_frac=min_keep)
        best_full = score_policy(train, best_policy, min_keep_frac=min_keep)
        report["optuna"] = {
            "trials": len(study.trials),
            "best_params": best_policy,
            "best_mean_fold_remaining_losers": None if not np.isfinite(best_fold) else round(best_fold, 4),
            "best_fold_remaining_losers": [None if not np.isfinite(v) else int(v) for v in best_per],
            "delta_vs_allow_all_fold": None
            if not (np.isfinite(best_fold) and np.isfinite(fold_base))
            else round(best_fold - fold_base, 4),
            "train_overlay": best_full,
        }
        print(f"  best mean fold remaining losers {best_fold}  (allow-all {fold_base})")
        print(
            f"  train remainL {best_full['remaining_losers']}  caughtL {best_full['losers_caught']}  "
            f"dropW {best_full['winners_dropped']}  keep {best_full['keep_frac']}"
        )
        print("  best policy:")
        for key, value in best_policy.items():
            print(f"    {key:<24}{value}")

    if args.evaluate_validation:
        validation = _seg(matrix, "validation")
        chosen = report.get("optuna", {}).get("best_params", best_policy)
        val = score_policy(validation, chosen, min_keep_frac=min_keep)
        val_base = score_policy(validation, ALLOW_ALL, min_keep_frac=min_keep)
        report["validation"] = {"policy": chosen, "overlay": val, "allow_all": val_base}
        print("\nvalidation (selection only):")
        print(f"  allow-all remainL {val_base['remaining_losers']} / {val_base['n']}")
        print(
            f"  policy    remainL {val['remaining_losers']}  caughtL {val['losers_caught']}  "
            f"dropW {val['winners_dropped']}  keep {val['keep_frac']}"
        )

    if args.evaluate_holdout:
        print("\nWARNING: opening the sealed holdout")
        holdout = _seg(matrix, "holdout")
        chosen = report.get("optuna", {}).get("best_params", best_policy)
        ho = score_policy(holdout, chosen, min_keep_frac=min_keep)
        ho_base = score_policy(holdout, ALLOW_ALL, min_keep_frac=min_keep)
        report["holdout"] = {"policy": chosen, "overlay": ho, "allow_all": ho_base}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / args.out_name
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    if args.trials > 0:
        policy_path = OUT_DIR / "logic1_m15_perception_best_policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "candidate_id": "LOGIC1_M15_PERCEPTION",
                    "policy": report.get("optuna", {}).get("best_params", best_policy),
                    "holdout_opened": False,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"written: {policy_path}")
    matrix_path = OUT_DIR / "logic1_m15_open_matrix.parquet"
    keep_cols = [
        c
        for c in (
            "trade_id",
            "timeframe",
            "side",
            "R",
            "loss",
            "win",
            "exit_reason",
            "entry_ts",
            "segment",
            "fp_signed_delta",
            "fp_signed_delta_l1",
            "fp_opp",
            "fp_fade",
            "fp_trapped",
            "fp_rej_against",
            "vol_against",
            "delta_at_against",
            "fp_poc_position",
            "fp_exact_bar",
        )
        if c in matrix.columns
    ]
    matrix[keep_cols].to_parquet(matrix_path, index=False)
    print(f"\nwritten: {out_path}")
    print(f"written: {matrix_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
