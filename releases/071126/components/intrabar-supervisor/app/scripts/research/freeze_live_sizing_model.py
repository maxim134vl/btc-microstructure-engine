#!/usr/bin/env python3
"""Freeze the deployable sizing model and the contract needed to serve it.

Scope
-----
Only the 26 features the live stack already writes at decision time: the
cross-timeframe snapshot the manager records on every cycle, plus values derived from
the entry command itself. The 121 research-pack features were measured to add nothing
to profit (+12.83% vs +13.83% on holdout) and are excluded so that serving needs no
new pipeline.

Training window
---------------
Fitted on every segment including holdout. The holdout has already served its purpose
as a one-shot test (+12.83%); withholding it now would only ship a weaker model. The
procedure is unchanged from the one validated three times over.

What is written
---------------
* the CatBoost model
* a feature contract: exact column order, dtypes, categorical positions, and the live
  source of each field, so a serving implementation cannot silently drift
* the probability->size map, including the payoff constants it was calibrated with
* a guard specification: what to do when a feature is missing or stale
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from compare_live_deployable_feature_sets import tier_features  # noqa: E402
from train_hybrid_trade_sizing_catboost import FILL_DERIVED, feature_columns, prepare  # noqa: E402

MATRIX = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/trade_feature_matrix.parquet"
OUT_DIR = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/production"
STUDY = ROOT / "data/research/external_traders/etll_hybrid_eqcorr/ml/sizing_optuna_train.json"
CURVE = (0.5, 1.5)

# Where a serving implementation must read each field from. Anything not listed here is
# not servable and must not enter the contract.
LIVE_SOURCE = {
    "xtf_": "timeframe_command_memory.parquet -> cross_timeframe_metadata (JSON, all 4 TFs, every manager cycle)",
    "f_stop_distance_bps": "command stop_reference + entry price at fill",
    "f_rr_ratio": "take_profit_price and stop_loss_price set at entry",
    "f_is_long": "command intent (OPEN_LONG / OPEN_SHORT)",
    "f_portfolio_open_risk_usd": "command portfolio_open_risk_usd",
    "f_risk_approval_ratio": "command approved_risk_usd / requested_risk_usd",
    "f_context_age_min": "source_bar_close - context_started_at, both on the command",
    "f_context_age_bars": "f_context_age_min divided by the timeframe length",
    "f_hour_utc": "entry timestamp",
    "f_dow": "entry timestamp",
    # These three need the OHLC of the LAST CLOSED bar on the trade's own timeframe.
    # data/live/live_market_feed.parquet carries it directly for M15; M30/H1/H4 require
    # resampling those M15 bars (first open, max high, min low, last close). That is
    # arithmetic on an existing live artifact, not a new plane builder — but a serving
    # implementation must do it, so it is called out separately here.
    "f_high_vs_close_bps": "live_market_feed.parquet, last closed bar of the trade's TF (resample M15 for M30/H1/H4)",
    "f_low_vs_close_bps": "live_market_feed.parquet, last closed bar of the trade's TF (resample M15 for M30/H1/H4)",
    "f_open_vs_close_bps": "live_market_feed.parquet, last closed bar of the trade's TF (resample M15 for M30/H1/H4)",
}

OHLC_DERIVED = ("f_high_vs_close_bps", "f_low_vs_close_bps", "f_open_vs_close_bps")


def describe(col: str) -> str:
    if col.startswith("xtf_"):
        return LIVE_SOURCE["xtf_"]
    return LIVE_SOURCE.get(col, "derived at entry; see build_hybrid_trade_feature_matrix.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    from catboost import CatBoostClassifier, Pool

    params = dict(json.loads(STUDY.read_text(encoding="utf-8"))["optuna"]["best_params"])
    full = pd.read_parquet(args.matrix)
    fit = full.loc[full["segment"].isin(["train", "validation", "holdout"]) & full["R"].notna()].reset_index(
        drop=True
    )

    feats, all_cats = feature_columns(fit)
    feats = [c for c in feats if c not in FILL_DERIVED]
    cols = tier_features(feats)["live_today"]
    cats = [c for c in all_cats if c in cols]

    x = prepare(fit, cols, cats)
    cat_idx = [x.columns.get_loc(c) for c in cats]
    model = CatBoostClassifier(**params)
    model.fit(Pool(x, fit["win"], cat_features=cat_idx), verbose=False)

    w = float(fit.loc[fit["win"] == 1, "R"].mean())
    loss = abs(float(fit.loc[fit["win"] == 0, "R"].mean()))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.out_dir / "sizing_model.cbm"
    model.save_model(str(model_path))

    contract = {
        "artifact_id": "hybrid_live_sizing_model",
        "schema_version": 1,
        "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model_file": model_path.name,
        "source_book": "ETLL_HYBRID_TICK_V1_20260905_092610 (canonical Hybrid tick book)",
        "trained_on": {
            "segments": ["train", "validation", "holdout"],
            "trades": int(len(fit)),
            "span": [str(fit["entry_ts"].min())[:10], str(fit["entry_ts"].max())[:10]],
        },
        "hyperparameters": params,
        "features": {
            "count": len(cols),
            "order": cols,
            "categorical": cats,
            "categorical_indices": cat_idx,
            "sources": {c: describe(c) for c in cols},
        },
        "sizing": {
            "rule": "size = clip((p*W - (1-p)*L) / mean_EV, lo, hi), then renormalise to unit mean risk",
            "avg_win_r": round(w, 4),
            "avg_loss_r": round(-loss, 4),
            "clip_lo": CURVE[0],
            "clip_hi": CURVE[1],
            "applies_to": "requested_risk_usd on the manager's OPEN command",
            "note": (
                "Realised multipliers top out near 1.7 because the model does not emit "
                "probabilities confident enough to reach the ceiling; the clip mostly binds below."
            ),
        },
        "guards": {
            "missing_feature": "fall back to multiplier 1.0 (canonical sizing) — never block the trade",
            "stale_command": "if the cross-timeframe snapshot is older than one bar of the trade's timeframe, use 1.0",
            "probability_out_of_range": "if p is not in (0,1), use 1.0",
            "rationale": (
                "The canonical book is profitable unmodified, so every failure mode must degrade "
                "to canonical behaviour rather than to no trade."
            ),
        },
        "measured_performance": {
            "note": "train-only fits, evaluated once per segment; this frozen model saw all three",
            "train_oof_auc": 0.6648,
            "validation": {"auc": 0.6478, "uplift_pct": 11.04, "dd_change_pct": -1.67},
            "holdout": {"auc": 0.6448, "uplift_pct": 12.83, "dd_change_pct": -8.0},
        },
        "serving_requirements": {
            "from_manager_command": [c for c in cols if not c.startswith(OHLC_DERIVED)],
            "needs_bar_ohlc": list(OHLC_DERIVED),
            "bar_ohlc_note": (
                "M15 comes straight from data/live/live_market_feed.parquet. M30/H1/H4 must be "
                "resampled from those M15 bars (first open, max high, min low, last close), using "
                "only bars fully closed at the decision — the same rule the training matrix enforces."
            ),
        },
        "known_limitations": [
            "Live stack writes cross_timeframe_metadata to timeframe_command_memory.parquet, "
            "not manager_commands.parquet used in training; the JSON schema is identical.",
            "Drawdown reduction is weaker than the 147-feature research model (-8% vs -20%); "
            "recovering that needs per-timeframe context planes the live pipeline does not build.",
            "Trained on paper fills from the Hybrid tick replay, not on live execution.",
        ],
    }
    (args.out_dir / "feature_contract.json").write_text(
        json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"frozen: {len(cols)} features, {len(fit)} trades, {contract['trained_on']['span']}")
    print(f"  model    {model_path}")
    print(f"  contract {args.out_dir / 'feature_contract.json'}")
    print(f"  payoff   +{w:.3f}R / -{loss:.3f}R   curve {CURVE[0]}-{CURVE[1]}")
    print("\n  features:")
    for c in cols:
        print(f"    {c:<34}{'cat' if c in cats else 'num'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
