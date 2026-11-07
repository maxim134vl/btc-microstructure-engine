from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
)


ROOT = Path(__file__).resolve().parents[2]

SOURCE_PATH = (
    ROOT
    / "data/research/shadow_market_outcome_dataset_v1.parquet"
)

OUTPUT_DIR = (
    ROOT
    / "data/research/shadow_market_outcome_first_touch_v2"
)

DATASET_V2_PATH = (
    ROOT
    / "data/research/shadow_market_outcome_dataset_v2.parquet"
)

REPORT_PATH = OUTPUT_DIR / "first_touch_report.json"
PREDICTIONS_PATH = OUTPUT_DIR / "oos_predictions.parquet"
IMPORTANCE_PATH = OUTPUT_DIR / "feature_importance.csv"

HORIZON = 8
BARRIER_BPS = 50.0
PURGE_BARS = 16
RANDOM_SEED = 42

CLASSES = [
    "UP",
    "DOWN",
    "AMBIGUOUS",
    "NO_MOVE",
]

FOLD_SPECS = [
    (0.55, 0.70),
    (0.70, 0.85),
    (0.85, 1.00),
]


def safe_div(
    numerator: pd.Series,
    denominator: pd.Series,
) -> pd.Series:
    den = pd.to_numeric(
        denominator,
        errors="coerce",
    ).replace(0, np.nan)

    num = pd.to_numeric(
        numerator,
        errors="coerce",
    )

    return num / den


def add_first_touch_target(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    out = frame.copy()

    close = pd.to_numeric(
        out["cs_close"],
        errors="coerce",
    )

    high = pd.to_numeric(
        out["cs_high"],
        errors="coerce",
    )

    low = pd.to_numeric(
        out["cs_low"],
        errors="coerce",
    )

    upper = close * (
        1.0 + BARRIER_BPS / 10000.0
    )

    lower = close * (
        1.0 - BARRIER_BPS / 10000.0
    )

    labels = []
    touch_steps = []

    n = len(out)

    for i in range(n):
        if i + HORIZON >= n:
            labels.append(None)
            touch_steps.append(np.nan)
            continue

        label = "NO_MOVE"
        touch_step = np.nan

        for step in range(1, HORIZON + 1):
            future_i = i + step

            up_hit = (
                pd.notna(high.iloc[future_i])
                and pd.notna(upper.iloc[i])
                and high.iloc[future_i] >= upper.iloc[i]
            )

            down_hit = (
                pd.notna(low.iloc[future_i])
                and pd.notna(lower.iloc[i])
                and low.iloc[future_i] <= lower.iloc[i]
            )

            if up_hit and down_hit:
                label = "AMBIGUOUS"
                touch_step = float(step)
                break

            if up_hit:
                label = "UP"
                touch_step = float(step)
                break

            if down_hit:
                label = "DOWN"
                touch_step = float(step)
                break

        labels.append(label)
        touch_steps.append(touch_step)

    out["target_first_touch_h8_50bps"] = labels
    out["target_first_touch_step"] = touch_steps

    return out


def build_stationary_features(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    out = frame.copy()

    close = pd.to_numeric(
        out["cs_close"],
        errors="coerce",
    )

    open_ = pd.to_numeric(
        out["cs_open"],
        errors="coerce",
    )

    volume = pd.to_numeric(
        out["cs_volume"],
        errors="coerce",
    )

    volume_mean = pd.to_numeric(
        out["cs_volume_mean_20"],
        errors="coerce",
    )

    out["f_body_bps"] = (
        safe_div(
            out["cs_close"] - out["cs_open"],
            open_,
        )
        * 10000.0
    )

    out["f_range_bps"] = (
        safe_div(
            out["cs_high"] - out["cs_low"],
            open_,
        )
        * 10000.0
    )

    out["f_upper_wick_bps"] = (
        safe_div(
            out["cs_upper_wick"],
            close,
        )
        * 10000.0
    )

    out["f_lower_wick_bps"] = (
        safe_div(
            out["cs_lower_wick"],
            close,
        )
        * 10000.0
    )

    out["f_spread_bps"] = (
        safe_div(
            out["cs_spread"],
            close,
        )
        * 10000.0
    )

    out["f_spread_mean_20_bps"] = (
        safe_div(
            out["cs_spread_mean_20"],
            close,
        )
        * 10000.0
    )

    out["f_spread_std_20_bps"] = (
        safe_div(
            out["cs_spread_std_20"],
            close,
        )
        * 10000.0
    )

    out["f_volume_ratio_20"] = safe_div(
        volume,
        volume_mean,
    )

    out["f_delta_volume_ratio"] = safe_div(
        out["cs_delta"],
        volume,
    )

    out["f_taker_buy_share"] = safe_div(
        out["cs_taker_buy_volume"],
        volume,
    )

    out["f_buy_share"] = safe_div(
        out["cs_buy_volume"],
        volume,
    )

    out["f_sell_share"] = safe_div(
        out["cs_sell_volume"],
        volume,
    )

    out["f_close_position"] = pd.to_numeric(
        out["cs_close_position"],
        errors="coerce",
    )

    out["f_volume_zscore"] = pd.to_numeric(
        out["cs_volume_zscore"],
        errors="coerce",
    )

    out["f_spread_zscore"] = pd.to_numeric(
        out["cs_spread_zscore"],
        errors="coerce",
    )

    out["f_candle_type"] = (
        out["cs_candle_type"]
        .fillna("MISSING")
        .astype(str)
    )

    for lag in [1, 2, 4, 8]:
        ret_col = f"past_return_{lag}_bps"

        if ret_col in out.columns:
            out[f"f_return_{lag}_bps"] = pd.to_numeric(
                out[ret_col],
                errors="coerce",
            )

        volume_col = f"lag_{lag}_volume"
        delta_col = f"lag_{lag}_delta"
        spread_col = f"lag_{lag}_spread"
        cp_col = f"lag_{lag}_close_position"
        vz_col = f"lag_{lag}_volume_zscore"
        sz_col = f"lag_{lag}_spread_zscore"

        if volume_col in out.columns:
            out[f"f_lag_{lag}_volume_ratio_20"] = safe_div(
                out[volume_col],
                volume_mean,
            )

        if (
            volume_col in out.columns
            and delta_col in out.columns
        ):
            out[f"f_lag_{lag}_delta_volume_ratio"] = safe_div(
                out[delta_col],
                out[volume_col],
            )

        if spread_col in out.columns:
            out[f"f_lag_{lag}_spread_bps"] = (
                safe_div(
                    out[spread_col],
                    close,
                )
                * 10000.0
            )

        if cp_col in out.columns:
            out[f"f_lag_{lag}_close_position"] = pd.to_numeric(
                out[cp_col],
                errors="coerce",
            )

        if vz_col in out.columns:
            out[f"f_lag_{lag}_volume_zscore"] = pd.to_numeric(
                out[vz_col],
                errors="coerce",
            )

        if sz_col in out.columns:
            out[f"f_lag_{lag}_spread_zscore"] = pd.to_numeric(
                out[sz_col],
                errors="coerce",
            )

    if "past_return_16_bps" in out.columns:
        out["f_return_16_bps"] = pd.to_numeric(
            out["past_return_16_bps"],
            errors="coerce",
        )

    tf_windows = {
        "m30": 2.0,
        "h1": 4.0,
        "h4": 16.0,
    }

    for tf, bars in tf_windows.items():
        ret_col = f"mtf_{tf}_return_bps"
        range_col = f"mtf_{tf}_range"
        volume_col = f"mtf_{tf}_volume"
        buy_col = f"mtf_{tf}_buy_volume"
        sell_col = f"mtf_{tf}_sell_volume"
        delta_col = f"mtf_{tf}_delta"

        if ret_col in out.columns:
            out[f"f_{tf}_return_bps"] = pd.to_numeric(
                out[ret_col],
                errors="coerce",
            )

        if range_col in out.columns:
            out[f"f_{tf}_range_bps"] = (
                safe_div(
                    out[range_col],
                    close,
                )
                * 10000.0
            )

        if volume_col in out.columns:
            expected_volume = volume_mean * bars

            out[f"f_{tf}_volume_ratio_20"] = safe_div(
                out[volume_col],
                expected_volume,
            )

            if delta_col in out.columns:
                out[f"f_{tf}_delta_volume_ratio"] = safe_div(
                    out[delta_col],
                    out[volume_col],
                )

            if buy_col in out.columns:
                out[f"f_{tf}_buy_share"] = safe_div(
                    out[buy_col],
                    out[volume_col],
                )

            if sell_col in out.columns:
                out[f"f_{tf}_sell_share"] = safe_div(
                    out[sell_col],
                    out[volume_col],
                )

    out["f_loc_volume_ratio"] = pd.to_numeric(
        out.get("loc_localized_volume_ratio"),
        errors="coerce",
    )

    out["f_loc_concentration"] = pd.to_numeric(
        out.get("loc_volume_concentration"),
        errors="coerce",
    )

    out["f_loc_zone_width_bps"] = (
        safe_div(
            out.get(
                "loc_zone_width",
                pd.Series(np.nan, index=out.index),
            ),
            close,
        )
        * 10000.0
    )

    for source, target in [
        ("loc_behavior", "f_loc_behavior"),
        (
            "loc_localized_behavior",
            "f_loc_localized_behavior",
        ),
    ]:
        if source in out.columns:
            out[target] = (
                out[source]
                .fillna("MISSING")
                .astype(str)
            )

    for source, target in [
        (
            "loc_lower_rejection",
            "f_loc_lower_rejection",
        ),
        (
            "loc_upper_rejection",
            "f_loc_upper_rejection",
        ),
    ]:
        if source in out.columns:
            out[target] = (
                out[source]
                .fillna(False)
                .astype(str)
            )

    certified = (
        out["vr_vr_causal_certified"]
        .fillna(False)
        .astype(bool)
        if "vr_vr_causal_certified" in out.columns
        else pd.Series(False, index=out.index)
    )

    vr_numeric = [
        "vr_delta_efficiency",
        "vr_effort_score",
        "vr_result_score",
        "vr_effort_result_ratio",
        "vr_normalized_result",
        "vr_relative_volume",
        "vr_relative_spread",
        "vr_volume_concentration",
    ]

    for source in vr_numeric:
        if source not in out.columns:
            continue

        target = f"f_{source}"

        values = pd.to_numeric(
            out[source],
            errors="coerce",
        )

        out[target] = values.where(
            certified,
            np.nan,
        )

    vr_categorical = [
        "vr_volume_event",
        "vr_continuation_quality",
        "vr_unfinished_auction",
        "vr_unfinished_reason",
        "vr_localized_behavior",
        "vr_effort_result_state",
        "vr_volume_class",
        "vr_climax_state",
        "vr_participation_state",
        "vr_localization_join_status",
    ]

    for source in vr_categorical:
        if source not in out.columns:
            continue

        target = f"f_{source}"

        values = (
            out[source]
            .fillna("MISSING")
            .astype(str)
        )

        out[target] = np.where(
            certified,
            values,
            "MISSING",
        )

    market_features = sorted(
        col
        for col in out.columns
        if col.startswith("f_")
        and not col.startswith("f_loc_")
        and not col.startswith("f_vr_")
    )

    localization_features = sorted(
        col
        for col in out.columns
        if col.startswith("f_loc_")
    )

    vr_features = sorted(
        col
        for col in out.columns
        if col.startswith("f_vr_")
    )

    groups = {
        "A_MARKET": market_features,
        "B_MARKET_LOCALIZATION": sorted(
            market_features
            + localization_features
        ),
        "C_MARKET_LOCALIZATION_VR": sorted(
            market_features
            + localization_features
            + vr_features
        ),
    }

    return out, groups


def get_cat_features(
    frame: pd.DataFrame,
    features: list[str],
) -> list[str]:
    cats = []

    for col in features:
        if (
            pd.api.types.is_object_dtype(frame[col])
            or isinstance(
                frame[col].dtype,
                pd.CategoricalDtype,
            )
            or pd.api.types.is_bool_dtype(frame[col])
        ):
            cats.append(col)

    return cats


def prepare_matrix(
    frame: pd.DataFrame,
    features: list[str],
    cat_features: list[str],
) -> pd.DataFrame:
    x = frame[features].copy()

    for col in features:
        if col in cat_features:
            x[col] = (
                x[col]
                .fillna("MISSING")
                .astype(str)
            )
        else:
            x[col] = pd.to_numeric(
                x[col],
                errors="coerce",
            )

    return x


def fold_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    probabilities: np.ndarray,
    model_classes: list[str],
    baseline_class: str,
) -> dict:
    labels = CLASSES

    accuracy = float(
        accuracy_score(
            y_true,
            y_pred,
        )
    )

    balanced = float(
        balanced_accuracy_score(
            y_true,
            y_pred,
        )
    )

    macro_f1 = float(
        f1_score(
            y_true,
            y_pred,
            labels=labels,
            average="macro",
            zero_division=0,
        )
    )

    baseline_pred = np.full(
        len(y_true),
        baseline_class,
        dtype=object,
    )

    baseline_accuracy = float(
        accuracy_score(
            y_true,
            baseline_pred,
        )
    )

    prob_aligned = np.zeros(
        (len(y_true), len(labels)),
        dtype=float,
    )

    model_class_to_idx = {
        str(label): idx
        for idx, label in enumerate(model_classes)
    }

    for target_idx, label in enumerate(labels):
        if label in model_class_to_idx:
            prob_aligned[:, target_idx] = probabilities[
                :,
                model_class_to_idx[label],
            ]

    row_sum = prob_aligned.sum(axis=1)

    valid_prob = row_sum > 0

    prob_aligned[
        valid_prob
    ] = (
        prob_aligned[valid_prob]
        / row_sum[valid_prob, None]
    )

    ll = None

    if valid_prob.all():
        ll = float(
            log_loss(
                y_true,
                prob_aligned,
                labels=labels,
            )
        )

    actionable = np.isin(
        y_pred,
        ["UP", "DOWN"],
    )

    action_coverage = float(
        actionable.mean()
    )

    if actionable.any():
        action_precision = float(
            np.mean(
                y_pred[actionable]
                == y_true[actionable]
            )
        )
    else:
        action_precision = None

    directional_actual = np.isin(
        y_true,
        ["UP", "DOWN"],
    )

    if directional_actual.any():
        directional_accuracy = float(
            np.mean(
                y_pred[directional_actual]
                == y_true[directional_actual]
            )
        )
    else:
        directional_accuracy = None

    cm = confusion_matrix(
        y_true,
        y_pred,
        labels=labels,
    )

    return {
        "rows": int(len(y_true)),
        "accuracy": accuracy,
        "balanced_accuracy": balanced,
        "macro_f1": macro_f1,
        "log_loss": ll,
        "baseline_class": baseline_class,
        "baseline_accuracy": baseline_accuracy,
        "accuracy_improvement_pct_points": float(
            (accuracy - baseline_accuracy)
            * 100.0
        ),
        "action_coverage": action_coverage,
        "action_precision": action_precision,
        "directional_accuracy": directional_accuracy,
        "confusion_matrix": cm.tolist(),
    }


def run_group(
    frame: pd.DataFrame,
    group_name: str,
    features: list[str],
) -> tuple[
    list[dict],
    list[pd.DataFrame],
    list[pd.DataFrame],
]:
    results = []
    predictions = []
    importances = []

    cat_features = get_cat_features(
        frame,
        features,
    )

    cat_indices = [
        features.index(col)
        for col in cat_features
    ]

    n = len(frame)

    for fold_id, (
        train_fraction,
        valid_fraction,
    ) in enumerate(
        FOLD_SPECS,
        start=1,
    ):
        valid_start = int(
            n * train_fraction
        )

        valid_end = int(
            n * valid_fraction
        )

        train_end = max(
            0,
            valid_start - PURGE_BARS,
        )

        train = frame.iloc[
            :train_end
        ].copy()

        valid = frame.iloc[
            valid_start:valid_end
        ].copy()

        target = "target_first_touch_h8_50bps"

        train = train[
            train[target].notna()
        ].copy()

        valid = valid[
            valid[target].notna()
        ].copy()

        x_train = prepare_matrix(
            train,
            features,
            cat_features,
        )

        x_valid = prepare_matrix(
            valid,
            features,
            cat_features,
        )

        y_train = (
            train[target]
            .astype(str)
            .to_numpy()
        )

        y_valid = (
            valid[target]
            .astype(str)
            .to_numpy()
        )

        counts = pd.Series(
            y_train
        ).value_counts()

        baseline_class = str(
            counts.index[0]
        )

        model = CatBoostClassifier(
            iterations=600,
            depth=6,
            learning_rate=0.03,
            loss_function="MultiClass",
            random_seed=RANDOM_SEED,
            l2_leaf_reg=5.0,
            random_strength=1.0,
            verbose=False,
            allow_writing_files=False,
            thread_count=-1,
        )

        model.fit(
            x_train,
            y_train,
            cat_features=cat_indices,
        )

        pred = (
            model.predict(x_valid)
            .reshape(-1)
            .astype(str)
        )

        proba = model.predict_proba(
            x_valid
        )

        metrics = fold_metrics(
            y_valid,
            pred,
            proba,
            [str(x) for x in model.classes_],
            baseline_class,
        )

        metrics.update(
            {
                "group": group_name,
                "fold": fold_id,
                "train_rows": int(
                    len(train)
                ),
                "valid_rows": int(
                    len(valid)
                ),
                "feature_count": int(
                    len(features)
                ),
                "categorical_feature_count": int(
                    len(cat_features)
                ),
                "train_time_min": str(
                    train["timestamp"].min()
                ),
                "train_time_max": str(
                    train["timestamp"].max()
                ),
                "valid_time_min": str(
                    valid["timestamp"].min()
                ),
                "valid_time_max": str(
                    valid["timestamp"].max()
                ),
                "train_class_distribution": {
                    str(k): int(v)
                    for k, v in counts.items()
                },
                "valid_class_distribution": {
                    str(k): int(v)
                    for k, v in pd.Series(
                        y_valid
                    ).value_counts().items()
                },
            }
        )

        results.append(
            metrics
        )

        pred_frame = pd.DataFrame(
            {
                "timestamp": valid[
                    "timestamp"
                ].to_numpy(),
                "group": group_name,
                "fold": fold_id,
                "actual": y_valid,
                "predicted": pred,
            }
        )

        for idx, class_name in enumerate(
            model.classes_
        ):
            pred_frame[
                f"prob_{class_name}"
            ] = proba[:, idx]

        predictions.append(
            pred_frame
        )

        importance = pd.DataFrame(
            {
                "group": group_name,
                "fold": fold_id,
                "feature": features,
                "importance": (
                    model.get_feature_importance()
                ),
            }
        )

        importances.append(
            importance
        )

        print(
            "FOLD",
            fold_id,
            group_name,
            "ACC",
            round(
                metrics["accuracy"],
                4,
            ),
            "BASE",
            round(
                metrics["baseline_accuracy"],
                4,
            ),
            "BAL_ACC",
            round(
                metrics["balanced_accuracy"],
                4,
            ),
            "MACRO_F1",
            round(
                metrics["macro_f1"],
                4,
            ),
            "ACTION_COVERAGE",
            round(
                metrics["action_coverage"],
                4,
            ),
            "ACTION_PRECISION",
            None
            if metrics[
                "action_precision"
            ] is None
            else round(
                metrics[
                    "action_precision"
                ],
                4,
            ),
        )

    return (
        results,
        predictions,
        importances,
    )


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    frame = pd.read_parquet(
        SOURCE_PATH
    )

    frame = (
        frame.sort_values(
            "timestamp"
        )
        .reset_index(drop=True)
    )

    frame = add_first_touch_target(
        frame
    )

    frame, feature_groups = (
        build_stationary_features(
            frame
        )
    )

    target = (
        "target_first_touch_h8_50bps"
    )

    valid_target = frame[
        frame[target].notna()
    ].copy()

    print(
        "ROWS",
        len(frame),
    )

    print(
        "VALID_TARGET_ROWS",
        len(valid_target),
    )

    print(
        "TARGET_DISTRIBUTION"
    )

    print(
        valid_target[
            target
        ]
        .value_counts()
        .to_string()
    )

    keep_features = sorted(
        set(
            feature
            for features
            in feature_groups.values()
            for feature in features
        )
    )

    dataset_columns = [
        "timestamp",
        target,
        "target_first_touch_step",
    ] + keep_features

    frame[
        dataset_columns
    ].to_parquet(
        DATASET_V2_PATH,
        index=False,
    )

    all_results = []
    all_predictions = []
    all_importances = []

    for group_name, features in (
        feature_groups.items()
    ):
        print()
        print(
            "GROUP",
            group_name,
        )

        print(
            "FEATURES",
            len(features),
        )

        (
            results,
            predictions,
            importances,
        ) = run_group(
            valid_target,
            group_name,
            features,
        )

        all_results.extend(
            results
        )

        all_predictions.extend(
            predictions
        )

        all_importances.extend(
            importances
        )

    results_df = pd.DataFrame(
        all_results
    )

    summary = (
        results_df
        .groupby(
            "group",
            as_index=False,
        )
        .agg(
            folds=(
                "fold",
                "count",
            ),
            mean_accuracy=(
                "accuracy",
                "mean",
            ),
            mean_baseline_accuracy=(
                "baseline_accuracy",
                "mean",
            ),
            mean_accuracy_improvement_pct_points=(
                "accuracy_improvement_pct_points",
                "mean",
            ),
            mean_balanced_accuracy=(
                "balanced_accuracy",
                "mean",
            ),
            mean_macro_f1=(
                "macro_f1",
                "mean",
            ),
            mean_log_loss=(
                "log_loss",
                "mean",
            ),
            mean_action_coverage=(
                "action_coverage",
                "mean",
            ),
            mean_action_precision=(
                "action_precision",
                "mean",
            ),
            mean_directional_accuracy=(
                "directional_accuracy",
                "mean",
            ),
        )
    )

    predictions_df = pd.concat(
        all_predictions,
        ignore_index=True,
    )

    importance_df = pd.concat(
        all_importances,
        ignore_index=True,
    )

    mean_importance = (
        importance_df
        .groupby(
            [
                "group",
                "feature",
            ],
            as_index=False,
        )[
            "importance"
        ]
        .mean()
        .sort_values(
            [
                "group",
                "importance",
            ],
            ascending=[
                True,
                False,
            ],
        )
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
        "version": (
            "shadow_market_outcome_first_touch_v2"
        ),
        "horizon_bars": HORIZON,
        "barrier_bps": BARRIER_BPS,
        "purge_bars": PURGE_BARS,
        "classes": CLASSES,
        "feature_groups": feature_groups,
        "target_distribution": {
            str(k): int(v)
            for k, v in valid_target[
                target
            ]
            .value_counts()
            .items()
        },
        "fold_results": all_results,
        "summary": summary.to_dict(
            orient="records"
        ),
        "safety": {
            "absolute_price_features_used": False,
            "hour_used": False,
            "day_of_week_used": False,
            "audit_context_used": False,
            "audit_auction_used": False,
            "audit_state_used": False,
            "future_target_features_used": False,
            "volume_response_requires_causal_certification": True,
            "random_split_used": False,
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

    print(
        summary.to_string(
            index=False
        )
    )

    print()
    print("TOP_FEATURES")

    for group_name in feature_groups:
        print()
        print(group_name)

        print(
            mean_importance[
                mean_importance[
                    "group"
                ]
                == group_name
            ]
            .head(15)[
                [
                    "feature",
                    "importance",
                ]
            ]
            .to_string(
                index=False
            )
        )

    print()
    print(
        "DATASET_V2",
        DATASET_V2_PATH,
    )

    print(
        "REPORT",
        REPORT_PATH,
    )

    print(
        "PREDICTIONS",
        PREDICTIONS_PATH,
    )

    print(
        "IMPORTANCE",
        IMPORTANCE_PATH,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
