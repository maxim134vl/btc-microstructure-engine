#!/usr/bin/env python3
"""LOGIC1: Optuna over an S4.1 OPEN gate on the canonical Hybrid tick book.

CatBoost sizing is not trained here. Train / validation / holdout follow
config/research/etll_hybrid_calibration_split.json. Holdout stays sealed unless
--evaluate-holdout is passed exactly once on a frozen policy.

  python3 scripts/research/train_logic1_s41_open_gate_optuna.py
  python3 scripts/research/train_logic1_s41_open_gate_optuna.py --trials 80
  python3 scripts/research/train_logic1_s41_open_gate_optuna.py --evaluate-validation
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

from btc_ml.research.logic1_open_gate import (  # noqa: E402
    ALLOW_ALL,
    DEFAULT_ARCHIVE,
    build_open_events,
    mean_fold_total_r,
    purged_folds,
    resolve_pack_root,
    score_policy,
)
from calibration_split import assign_segment, load_split  # noqa: E402

CFG_PATH = ROOT / "config/research/logic1_s41_open_gate.json"
OUT_DIR = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/logic1"
HAND_PROBES: dict[str, dict[str, Any]] = {
    "allow_all": dict(ALLOW_ALL),
    "block_higher_tf_opposite": {**ALLOW_ALL, "block_higher_tf_opposite": True},
    "block_long_below_origin_20": {**ALLOW_ALL, "block_long_below_origin_bps": 20},
    "block_short_above_origin_20": {**ALLOW_ALL, "block_short_above_origin_bps": 20},
    "dump_long_gate": {
        **ALLOW_ALL,
        "block_higher_tf_opposite": True,
        "block_long_below_origin_bps": 20,
        "ret_lookback_bars": 8,
        "block_adverse_ret_bps": 40,
    },
}


def load_candidate() -> dict[str, Any]:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def space_from_cfg(cfg: dict[str, Any]) -> dict[str, list[Any]]:
    return {k: list(v) for k, v in cfg["search_space"].items()}


def suggest_policy(trial: Any, space: dict[str, list[Any]]) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    for name, choices in space.items():
        policy[name] = trial.suggest_categorical(name, choices)
    if int(policy.get("ret_lookback_bars") or 0) == 0:
        policy["block_adverse_ret_bps"] = 0
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
        mean_r, per = mean_fold_total_r(train, policy, folds, min_keep_frac=min_keep_frac)
        trial.set_user_attr("policy", policy)
        trial.set_user_attr("fold_total_r", [None if not np.isfinite(v) else round(v, 4) for v in per])
        return mean_r

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed, n_startup_trials=min(20, max(5, trials // 3))),
        study_name="logic1_s41_open_gate",
    )
    study.enqueue_trial(dict(ALLOW_ALL))
    study.optimize(objective, n_trials=trials, show_progress_bar=False)
    best = dict(study.best_trial.user_attrs.get("policy") or study.best_params)
    return best, study


def _segment_frame(events: pd.DataFrame, name: str) -> pd.DataFrame:
    return events.loc[events["segment"] == name].reset_index(drop=True)


def main() -> int:
    cfg = load_candidate()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--pack-root", type=Path, default=None)
    parser.add_argument("--folds", type=int, default=int(cfg["protocol"]["folds"]))
    parser.add_argument("--trials", type=int, default=0, help="0 = hand probes on train only")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--out-name", default="logic1_open_gate_train.json")
    parser.add_argument("--evaluate-validation", action="store_true")
    parser.add_argument(
        "--evaluate-holdout",
        action="store_true",
        help="SEALED. One look at the holdout. Do not pass this while searching.",
    )
    args = parser.parse_args()

    split = load_split()
    pack_root = resolve_pack_root(args.pack_root, ROOT)
    print(f"candidate: {cfg['candidate_id']}")
    print(f"archive:   {args.archive}")
    print(f"packs:     {pack_root or 'none (origin vs entry_price only)'}")
    print("catboost:  not used")

    events = build_open_events(args.archive, pack_root=pack_root)
    events["segment"] = assign_segment(events, split)
    train = _segment_frame(events, "train")
    train = train.loc[train["R"].notna()].reset_index(drop=True)
    min_keep = float(cfg["scoring"]["min_keep_frac"])
    folds = purged_folds(train["entry_ts"], args.folds, purge_days=int(cfg["protocol"]["purge_days"]))

    print(f"events:    {len(events)} executed opens  train={len(train)}")
    print(f"purged walk-forward: {len(folds)} folds, {cfg['protocol']['purge_days']}-day purge")
    for i, (fit_idx, score_idx) in enumerate(folds, 1):
        print(
            f"  fold {i}: score {len(score_idx):>5}  "
            f"{pd.Timestamp(train['entry_ts'].iloc[score_idx].min()).date()}"
            f"->{pd.Timestamp(train['entry_ts'].iloc[score_idx].max()).date()}"
            f"  (fit pool {len(fit_idx)})"
        )

    probes = {name: score_policy(train, policy, min_keep_frac=min_keep) for name, policy in HAND_PROBES.items()}
    fold_allow, fold_allow_per = mean_fold_total_r(train, ALLOW_ALL, folds, min_keep_frac=min_keep)
    report: dict[str, Any] = {
        "candidate_id": cfg["candidate_id"],
        "segment": "train",
        "holdout": "sealed" if not args.evaluate_holdout else "OPENED",
        "catboost_used": False,
        "trades_train": int(len(train)),
        "folds": len(folds),
        "purge_days": cfg["protocol"]["purge_days"],
        "pack_root": str(pack_root) if pack_root else None,
        "baseline_allow_all": probes["allow_all"],
        "baseline_mean_fold_total_r": None if not np.isfinite(fold_allow) else round(fold_allow, 4),
        "baseline_fold_total_r": [round(v, 4) for v in fold_allow_per],
        "hand_probes": probes,
        "detectable_effect_r_holdout": split["statistical_power"]["detectable_effect_r_95pct_holdout"],
    }

    print("\ntrain overlay (allow-all is the book):")
    for name, result in probes.items():
        print(
            f"  {name:<28} kept {result['n_kept']:>5}/{result['n']:<5}  "
            f"meanR {result['mean_r']}  dTotalR {result['delta_total_r']}  "
            f"blockedMeanR {result['blocked_mean_r']}"
        )

    best_policy = dict(ALLOW_ALL)
    if args.trials > 0:
        print(f"\noptuna: {args.trials} trials, objective = mean fold total R on train")
        best_policy, study = run_study(
            train,
            folds,
            space_from_cfg(cfg),
            trials=args.trials,
            seed=args.seed,
            min_keep_frac=min_keep,
        )
        best_score, best_per = mean_fold_total_r(train, best_policy, folds, min_keep_frac=min_keep)
        best_full = score_policy(train, best_policy, min_keep_frac=min_keep)
        report["optuna"] = {
            "trials": len(study.trials),
            "best_params": best_policy,
            "best_mean_fold_total_r": None if not np.isfinite(best_score) else round(best_score, 4),
            "best_fold_total_r": [None if not np.isfinite(v) else round(v, 4) for v in best_per],
            "best_vs_allow_all_fold": None
            if not (np.isfinite(best_score) and np.isfinite(fold_allow))
            else round(best_score - fold_allow, 4),
            "train_overlay": best_full,
        }
        print(f"  best mean fold total R {best_score:.4f}  (allow-all {fold_allow:.4f})")
        print(f"  train overlay dTotalR {best_full['delta_total_r']}  kept {best_full['n_kept']}/{best_full['n']}")
        print("  best policy:")
        for key, value in best_policy.items():
            print(f"    {key:<32}{value}")

    if args.evaluate_validation:
        validation = _segment_frame(events, "validation")
        chosen = report.get("optuna", {}).get("best_params", best_policy)
        val = score_policy(validation, chosen, min_keep_frac=min_keep)
        val_base = score_policy(validation, ALLOW_ALL, min_keep_frac=min_keep)
        report["validation"] = {"policy": chosen, "overlay": val, "allow_all": val_base}
        print("\nvalidation (selection only):")
        print(f"  allow-all meanR {val_base['mean_r']}  n={val_base['n']}")
        print(f"  policy    meanR {val['mean_r']}  dTotalR {val['delta_total_r']}  kept {val['n_kept']}")

    if args.evaluate_holdout:
        print("\nWARNING: opening the sealed holdout")
        holdout = _segment_frame(events, "holdout")
        chosen = report.get("optuna", {}).get("best_params", best_policy)
        ho = score_policy(holdout, chosen, min_keep_frac=min_keep)
        ho_base = score_policy(holdout, ALLOW_ALL, min_keep_frac=min_keep)
        report["holdout"] = {"policy": chosen, "overlay": ho, "allow_all": ho_base}
        print(f"  allow-all meanR {ho_base['mean_r']}  n={ho_base['n']}")
        print(f"  policy    meanR {ho['mean_r']}  dTotalR {ho['delta_total_r']}  kept {ho['n_kept']}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / args.out_name
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    policy_path = OUT_DIR / "logic1_open_gate_best_policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "candidate_id": cfg["candidate_id"],
                "policy": report.get("optuna", {}).get("best_params", best_policy),
                "holdout_opened": bool(args.evaluate_holdout),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwritten: {out_path}")
    print(f"written: {policy_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
