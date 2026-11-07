from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor


ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "data/research/shadow_market_outcome_dataset_v1.parquet"
OUTPUT_DIR = ROOT / "data/research/shadow_market_outcome_baseline_v1"
REPORT_PATH = OUTPUT_DIR / "baseline_report.json"
PREDICTIONS_PATH = OUTPUT_DIR / "oos_predictions.parquet"
IMPORTANCE_PATH = OUTPUT_DIR / "feature_importance.csv"

TARGET = "target_return_8_bps"
PURGE_BARS = 16
RANDOM_SEED = 42

FOLD_SPECS = [
    (0.55, 0.70),
    (0.70, 0.85),
    (0.85, 1.00),
]


BASE_EXACT = [
    "cs_open",
    "cs_high",
    "cs_low",
    "cs_close",
    "cs_volume",
    "cs_taker_buy_volume",
    "cs_buy_volume",
    "cs_sell_volume",
    "cs_delta",
    "cs_candle_type",
    "cs_body",
    "cs_spread",
    "cs_upper_wick",
    "cs_lower_wick",
    "cs_close_position",
    "cs_spread_mean_20",
    "cs_spread_std_20",
    "cs_volume_mean_20",
    "cs_volume_std_20",
    "cs_spread_zscore",
    "cs_volume_zscore",
    "hour_utc",
    "day_of_week_utc",
    "session_utc",
]

LOCALIZATION_EXACT = [
    "loc_estimated_local_volume",
    "loc_total_volume",
    "loc_localized_volume_ratio",
    "loc_volume_concentration",
    "loc_behavior",
    "loc_zone_width",
    "loc_lower_rejection",
    "loc_upper_rejection",
    "loc_localized_behavior",
]

VR_EXACT = [
    "vr_volume_event",
    "vr_continuation_quality",
    "vr_unfinished_auction",
    "vr_unfinished_reason",
    "vr_localized_behavior",
    "vr_delta_efficiency",
    "vr_estimated_local_volume",
    "vr_effort_score",
    "vr_result_score",
    "vr_effort_result_ratio",
    "vr_normalized_result",
    "vr_effort_result_state",
    "vr_volume_class",
    "vr_climax_state",
    "vr_participation_state",
    "vr_relative_volume",
    "vr_relative_spread",
    "vr_volume_concentration",
    "vr_localization_join_status",
    "vr_localization_fresh",
]


def existing(frame: pd.DataFrame, names: list[str]) -> list[str]:
    return [name for name in names if name in frame.columns]


def prefix_features(frame: pd.DataFrame, prefixes: tuple[str, ...]) -> list[str]:
    return [
        col
        for col in frame.columns
        if any(col.startswith(prefix) for prefix in prefixes)
    ]


def build_feature_groups(frame: pd.DataFrame) -> dict[str, list[str]]:
    base = existing(frame, BASE_EXACT)

    base += prefix_features(
        frame,
        (
            "mtf_",
            "lag_",
            "past_return_",
        ),
    )

    base = sorted(set(base))

    localization = sorted(
        set(base + existing(frame, LOCALIZATION_EXACT))
    )

    vr = sorted(
        set(localization + existing(frame, VR_EXACT))
    )

    return {
        "A_MARKET": base,
        "B_MARKET_LOCALIZATION": localization,
        "C_MARKET_LOCALIZATION_VR": vr,
    }


def prepare_vr_causal_mask(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()

    cert_col = "vr_vr_causal_certified"

    if cert_col not in out.columns:
        return out

    certified = out[cert_col].fillna(False).astype(bool)

    for col in existing(out, VR_EXACT):
        if pd.api.types.is_numeric_dtype(out[col]):
            out.loc[~certified, col] = np.nan
        else:
            out[col] = out[col].astype("object")
            out.loc[~certified, col] = None

    return out


def categorical_columns(frame: pd.DataFrame, features: list[str]) -> list[str]:
    cats = []

    for col in features:
        if (
            pd.api.types.is_object_dtype(frame[col])
            or isinstance(frame[col].dtype, pd.CategoricalDtype)
            or pd.api.types.is_bool_dtype(frame[col])
        ):
            cats.append(col)

    return cats


def prepare_matrix(
    frame: pd.DataFrame,
    features: list[str],
    cat_cols: list[str],
) -> pd.DataFrame:
    x = frame[features].copy()

    for col in features:
        if col in cat_cols:
            x[col] = x[col].fillna("MISSING").astype(str)
        else:
            x[col] = pd.to_numeric(x[col], errors="coerce")

    return x


def metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    baseline_pred: np.ndarray,
) -> dict[str, float | int | None]:
    valid = (
        np.isfinite(y_true)
        & np.isfinite(y_pred)
        & np.isfinite(baseline_pred)
    )

    y = y_true[valid]
    p = y_pred[valid]
    b = baseline_pred[valid]

    if len(y) == 0:
        return {}

    rmse = float(np.sqrt(np.mean((y - p) ** 2)))
    mae = float(np.mean(np.abs(y - p)))

    baseline_rmse = float(np.sqrt(np.mean((y - b) ** 2)))
    baseline_mae = float(np.mean(np.abs(y - b)))

    if baseline_rmse > 0:
        rmse_improvement = float(
            (baseline_rmse - rmse) / baseline_rmse * 100.0
        )
    else:
        rmse_improvement = None

    if np.std(y) > 0 and np.std(p) > 0:
        correlation = float(np.corrcoef(y, p)[0, 1])
    else:
        correlation = None

    sign_accuracy = float(
        np.mean(np.sign(y) == np.sign(p))
    )

    meaningful = np.abs(y) >= 25.0

    if meaningful.any():
        direction_accuracy_25 = float(
            np.mean(
                np.sign(y[meaningful])
                == np.sign(p[meaningful])
            )
        )
        meaningful_rows = int(meaningful.sum())
    else:
        direction_accuracy_25 = None
        meaningful_rows = 0

    order = np.argsort(p)
    decile_n = max(1, len(order) // 10)

    bottom_idx = order[:decile_n]
    top_idx = order[-decile_n:]

    bottom_realized = float(np.mean(y[bottom_idx]))
    top_realized = float(np.mean(y[top_idx]))
    top_bottom_spread = float(top_realized - bottom_realized)

    return {
        "rows": int(len(y)),
        "rmse_bps": rmse,
        "mae_bps": mae,
        "baseline_rmse_bps": baseline_rmse,
        "baseline_mae_bps": baseline_mae,
        "rmse_improvement_pct": rmse_improvement,
        "correlation": correlation,
        "sign_accuracy": sign_accuracy,
        "direction_accuracy_abs25bps": direction_accuracy_25,
        "direction_rows_abs25bps": meaningful_rows,
        "top_decile_realized_bps": top_realized,
        "bottom_decile_realized_bps": bottom_realized,
        "top_bottom_spread_bps": top_bottom_spread,
    }


def run_group(
    frame: pd.DataFrame,
    group_name: str,
    features: list[str],
) -> tuple[list[dict], list[pd.DataFrame], list[pd.DataFrame]]:
    results = []
    prediction_frames = []
    importance_frames = []

    cat_cols = categorical_columns(frame, features)
    cat_indices = [features.index(col) for col in cat_cols]

    n = len(frame)

    for fold_id, (train_fraction, valid_fraction) in enumerate(
        FOLD_SPECS,
        start=1,
    ):
        valid_start = int(n * train_fraction)
        valid_end = int(n * valid_fraction)

        train_end = max(0, valid_start - PURGE_BARS)

        train = frame.iloc[:train_end].copy()
        valid = frame.iloc[valid_start:valid_end].copy()

        train = train[train[TARGET].notna()].copy()
        valid = valid[valid[TARGET].notna()].copy()

        x_train = prepare_matrix(train, features, cat_cols)
        x_valid = prepare_matrix(valid, features, cat_cols)

        y_train = train[TARGET].astype(float).to_numpy()
        y_valid = valid[TARGET].astype(float).to_numpy()

        baseline_value = float(np.mean(y_train))
        baseline_pred = np.full(len(y_valid), baseline_value)

        model = CatBoostRegressor(
            iterations=500,
            depth=6,
            learning_rate=0.03,
            loss_function="RMSE",
            l2_leaf_reg=5.0,
            random_strength=1.0,
            random_seed=RANDOM_SEED,
            verbose=False,
            allow_writing_files=False,
            thread_count=-1,
        )

        model.fit(
            x_train,
            y_train,
            cat_features=cat_indices,
        )

        pred = model.predict(x_valid)

        fold_metrics = metrics(
            y_valid,
            pred,
            baseline_pred,
        )

        fold_metrics.update(
            {
                "group": group_name,
                "fold": fold_id,
                "train_rows": int(len(train)),
                "valid_rows": int(len(valid)),
                "train_time_min": str(train["timestamp"].min()),
                "train_time_max": str(train["timestamp"].max()),
                "valid_time_min": str(valid["timestamp"].min()),
                "valid_time_max": str(valid["timestamp"].max()),
                "feature_count": int(len(features)),
                "categorical_feature_count": int(len(cat_cols)),
            }
        )

        results.append(fold_metrics)

        pred_frame = pd.DataFrame(
            {
                "timestamp": valid["timestamp"].to_numpy(),
                "group": group_name,
                "fold": fold_id,
                "actual_return_8_bps": y_valid,
                "predicted_return_8_bps": pred,
                "baseline_return_8_bps": baseline_pred,
            }
        )

        prediction_frames.append(pred_frame)

        importance = pd.DataFrame(
            {
                "feature": features,
                "importance": model.get_feature_importance(),
                "group": group_name,
                "fold": fold_id,
            }
        )

        importance_frames.append(importance)

        print(
            "FOLD",
            fold_id,
            group_name,
            "RMSE",
            round(fold_metrics["rmse_bps"], 3),
            "BASE",
            round(fold_metrics["baseline_rmse_bps"], 3),
            "IMPROVEMENT_PCT",
            round(fold_metrics["rmse_improvement_pct"], 3),
            "CORR",
            None
            if fold_metrics["correlation"] is None
            else round(fold_metrics["correlation"], 4),
            "SIGN_ACC",
            round(fold_metrics["sign_accuracy"], 4),
            "TOP_BOTTOM_BPS",
            round(fold_metrics["top_bottom_spread_bps"], 3),
        )

    return results, prediction_frames, importance_frames


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not DATASET_PATH.exists():
        raise RuntimeError(f"Missing dataset: {DATASET_PATH}")

    frame = pd.read_parquet(DATASET_PATH)
    frame = frame.sort_values("timestamp").reset_index(drop=True)

    if TARGET not in frame.columns:
        raise RuntimeError(f"Missing target: {TARGET}")

    frame = prepare_vr_causal_mask(frame)

    feature_groups = build_feature_groups(frame)

    all_results = []
    all_predictions = []
    all_importance = []

    print("ROWS", len(frame))
    print("TARGET", TARGET)
    print("PURGE_BARS", PURGE_BARS)

    for group_name, features in feature_groups.items():
        print()
        print("GROUP", group_name)
        print("FEATURES", len(features))

        results, predictions, importance = run_group(
            frame,
            group_name,
            features,
        )

        all_results.extend(results)
        all_predictions.extend(predictions)
        all_importance.extend(importance)

    results_df = pd.DataFrame(all_results)

    summary = (
        results_df
        .groupby("group", as_index=False)
        .agg(
            folds=("fold", "count"),
            mean_rmse_bps=("rmse_bps", "mean"),
            mean_baseline_rmse_bps=("baseline_rmse_bps", "mean"),
            mean_rmse_improvement_pct=("rmse_improvement_pct", "mean"),
            mean_correlation=("correlation", "mean"),
            mean_sign_accuracy=("sign_accuracy", "mean"),
            mean_direction_accuracy_abs25bps=(
                "direction_accuracy_abs25bps",
                "mean",
            ),
            mean_top_bottom_spread_bps=(
                "top_bottom_spread_bps",
                "mean",
            ),
        )
    )

    predictions_df = pd.concat(
        all_predictions,
        ignore_index=True,
    )

    importance_df = pd.concat(
        all_importance,
        ignore_index=True,
    )

    mean_importance = (
        importance_df
        .groupby(["group", "feature"], as_index=False)["importance"]
        .mean()
        .sort_values(["group", "importance"], ascending=[True, False])
    )

    predictions_df.to_parquet(
        PREDICTIONS_PATH,
        index=False,
    )

    mean_importance.to_csv(
        IMPORTANCE_PATH,
        index=False,
    )

    report = {
        "version": "shadow_market_outcome_catboost_baseline_v1",
        "target": TARGET,
        "purge_bars": PURGE_BARS,
        "fold_specs": FOLD_SPECS,
        "model_parameters": {
            "iterations": 500,
            "depth": 6,
            "learning_rate": 0.03,
            "l2_leaf_reg": 5.0,
            "random_strength": 1.0,
            "random_seed": RANDOM_SEED,
        },
        "feature_groups": feature_groups,
        "fold_results": all_results,
        "summary": summary.to_dict(orient="records"),
        "safety": {
            "target_columns_used_as_features": False,
            "audit_columns_used_as_features": False,
            "trading_state_used": False,
            "volume_response_requires_vr_causal_certified": True,
            "random_train_test_split_used": False,
            "purged_walk_forward_used": True,
        },
    }

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )
    )

    print()
    print("SUMMARY")
    print(summary.to_string(index=False))

    print()
    print("TOP_FEATURES")

    for group_name in feature_groups:
        print()
        print(group_name)
        print(
            mean_importance[
                mean_importance["group"] == group_name
            ]
            .head(15)
            [["feature", "importance"]]
            .to_string(index=False)
        )

    print()
    print("REPORT", REPORT_PATH)
    print("PREDICTIONS", PREDICTIONS_PATH)
    print("IMPORTANCE", IMPORTANCE_PATH)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
