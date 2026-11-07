from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


ROOT = Path(__file__).resolve().parents[2]

DATASET_PATH = (
    ROOT
    / "data/research/shadow_market_outcome_dataset_v2.parquet"
)

OUTPUT_DIR = (
    ROOT
    / "data/research/shadow_market_outcome_hurdle_v3"
)

REPORT_PATH = OUTPUT_DIR / "hurdle_report.json"
PREDICTIONS_PATH = OUTPUT_DIR / "oos_predictions.parquet"
IMPORTANCE_PATH = OUTPUT_DIR / "feature_importance.csv"

TARGET_SOURCE = "target_first_touch_h8_50bps"

PURGE_BARS = 16
BAR_MINUTES = 15
RANDOM_SEED = 42

FOLD_SPECS = [
    (0.55, 0.70),
    (0.70, 0.85),
    (0.85, 1.00),
]

CONFIDENCE_THRESHOLDS = [
    0.55,
    0.60,
    0.65,
    0.70,
]


def build_feature_groups(
    frame: pd.DataFrame,
) -> dict[str, list[str]]:
    all_features = sorted(
        col
        for col in frame.columns
        if col.startswith("f_")
    )

    market = [
        col
        for col in all_features
        if not col.startswith("f_loc_")
        and not col.startswith("f_vr_")
    ]

    localization = [
        col
        for col in all_features
        if col.startswith("f_loc_")
    ]

    vr = [
        col
        for col in all_features
        if col.startswith("f_vr_")
    ]

    return {
        "A_MARKET": sorted(
            market
        ),
        "B_MARKET_LOCALIZATION": sorted(
            market
            + localization
        ),
        "C_MARKET_LOCALIZATION_VR": sorted(
            market
            + localization
            + vr
        ),
    }


def build_tasks(
    frame: pd.DataFrame,
) -> dict[str, dict]:
    source = (
        frame[TARGET_SOURCE]
        .fillna("")
        .astype(str)
    )

    touch = frame[
        source.isin(
            [
                "UP",
                "DOWN",
                "NO_MOVE",
            ]
        )
    ].copy()

    touch["target"] = np.where(
        touch[TARGET_SOURCE].isin(
            ["UP", "DOWN"]
        ),
        "TOUCH",
        "NO_TOUCH",
    )

    direction = frame[
        source.isin(
            [
                "UP",
                "DOWN",
            ]
        )
    ].copy()

    direction["target"] = (
        direction[TARGET_SOURCE]
        .astype(str)
    )

    return {
        "TOUCH": {
            "frame": touch,
            "positive_class": "TOUCH",
        },
        "DIRECTION": {
            "frame": direction,
            "positive_class": "UP",
        },
    }


def categorical_features(
    frame: pd.DataFrame,
    features: list[str],
) -> list[str]:
    cats = []

    for col in features:
        if (
            pd.api.types.is_object_dtype(
                frame[col]
            )
            or isinstance(
                frame[col].dtype,
                pd.CategoricalDtype,
            )
            or pd.api.types.is_bool_dtype(
                frame[col]
            )
        ):
            cats.append(col)

    return cats


def prepare_matrix(
    frame: pd.DataFrame,
    features: list[str],
    cat_features: list[str],
) -> pd.DataFrame:
    out = frame[features].copy()

    for col in features:
        if col in cat_features:
            out[col] = (
                out[col]
                .fillna("MISSING")
                .astype(str)
            )
        else:
            out[col] = pd.to_numeric(
                out[col],
                errors="coerce",
            )

    return out


def safe_binary_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    positive_probability: np.ndarray,
    positive_class: str,
) -> dict:
    unique = set(
        map(str, np.unique(y_true))
    )

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

    f1 = float(
        f1_score(
            y_true,
            y_pred,
            pos_label=positive_class,
            zero_division=0,
        )
    )

    precision = float(
        precision_score(
            y_true,
            y_pred,
            pos_label=positive_class,
            zero_division=0,
        )
    )

    recall = float(
        recall_score(
            y_true,
            y_pred,
            pos_label=positive_class,
            zero_division=0,
        )
    )

    binary_true = (
        np.asarray(y_true)
        == positive_class
    ).astype(int)

    roc_auc = None
    average_precision = None

    if len(unique) == 2:
        roc_auc = float(
            roc_auc_score(
                binary_true,
                positive_probability,
            )
        )

        average_precision = float(
            average_precision_score(
                binary_true,
                positive_probability,
            )
        )

    return {
        "accuracy": accuracy,
        "balanced_accuracy": balanced,
        "f1": f1,
        "precision": precision,
        "recall": recall,
        "roc_auc": roc_auc,
        "average_precision": average_precision,
    }


def selective_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    probabilities: np.ndarray,
) -> dict:
    confidence = probabilities.max(
        axis=1
    )

    out = {}

    for threshold in CONFIDENCE_THRESHOLDS:
        selected = (
            confidence >= threshold
        )

        key = str(
            int(threshold * 100)
        )

        coverage = float(
            selected.mean()
        )

        if selected.any():
            accuracy = float(
                np.mean(
                    y_pred[selected]
                    == y_true[selected]
                )
            )
            rows = int(
                selected.sum()
            )
        else:
            accuracy = None
            rows = 0

        out[f"coverage_{key}"] = coverage
        out[f"accuracy_{key}"] = accuracy
        out[f"rows_{key}"] = rows

    return out


def run_fold(
    task_name: str,
    task_frame: pd.DataFrame,
    positive_class: str,
    group_name: str,
    features: list[str],
    fold_id: int,
    train_fraction: float,
    valid_fraction: float,
) -> tuple[
    dict,
    pd.DataFrame,
    pd.DataFrame,
]:
    frame = (
        task_frame
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    n = len(frame)

    valid_start_index = int(
        n * train_fraction
    )

    valid_end_index = int(
        n * valid_fraction
    )

    valid_start_timestamp = (
        frame.iloc[
            valid_start_index
        ]["timestamp"]
    )

    purge_delta = pd.Timedelta(
        minutes=(
            PURGE_BARS
            * BAR_MINUTES
        )
    )

    train_cutoff = (
        valid_start_timestamp
        - purge_delta
    )

    train = frame[
        frame["timestamp"]
        < train_cutoff
    ].copy()

    valid = frame.iloc[
        valid_start_index:
        valid_end_index
    ].copy()

    cat_features = categorical_features(
        train,
        features,
    )

    cat_indices = [
        features.index(col)
        for col in cat_features
    ]

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
        train["target"]
        .astype(str)
        .to_numpy()
    )

    y_valid = (
        valid["target"]
        .astype(str)
        .to_numpy()
    )

    train_counts = (
        pd.Series(y_train)
        .value_counts()
    )

    majority_class = str(
        train_counts.index[0]
    )

    baseline_pred = np.full(
        len(y_valid),
        majority_class,
        dtype=object,
    )

    baseline_accuracy = float(
        accuracy_score(
            y_valid,
            baseline_pred,
        )
    )

    model = CatBoostClassifier(
        iterations=600,
        depth=6,
        learning_rate=0.03,
        loss_function="Logloss",
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

    prediction = (
        model
        .predict(x_valid)
        .reshape(-1)
        .astype(str)
    )

    probabilities = (
        model.predict_proba(
            x_valid
        )
    )

    classes = [
        str(x)
        for x in model.classes_
    ]

    positive_index = (
        classes.index(
            positive_class
        )
    )

    positive_probability = (
        probabilities[
            :,
            positive_index,
        ]
    )

    metrics = safe_binary_metrics(
        y_valid,
        prediction,
        positive_probability,
        positive_class,
    )

    metrics.update(
        {
            "task": task_name,
            "group": group_name,
            "fold": fold_id,
            "rows_train": int(
                len(train)
            ),
            "rows_valid": int(
                len(valid)
            ),
            "feature_count": int(
                len(features)
            ),
            "categorical_feature_count": int(
                len(cat_features)
            ),
            "baseline_class": majority_class,
            "baseline_accuracy": baseline_accuracy,
            "accuracy_improvement_pct_points": float(
                (
                    metrics["accuracy"]
                    - baseline_accuracy
                )
                * 100.0
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
            "train_distribution": {
                str(k): int(v)
                for k, v
                in train_counts.items()
            },
            "valid_distribution": {
                str(k): int(v)
                for k, v
                in pd.Series(
                    y_valid
                ).value_counts().items()
            },
        }
    )

    if task_name == "DIRECTION":
        metrics.update(
            selective_metrics(
                y_valid,
                prediction,
                probabilities,
            )
        )

    prediction_frame = pd.DataFrame(
        {
            "timestamp": (
                valid["timestamp"]
                .to_numpy()
            ),
            "task": task_name,
            "group": group_name,
            "fold": fold_id,
            "actual": y_valid,
            "predicted": prediction,
            "confidence": (
                probabilities.max(
                    axis=1
                )
            ),
        }
    )

    for index, class_name in enumerate(
        classes
    ):
        prediction_frame[
            f"prob_{class_name}"
        ] = probabilities[
            :,
            index,
        ]

    importance_frame = pd.DataFrame(
        {
            "task": task_name,
            "group": group_name,
            "fold": fold_id,
            "feature": features,
            "importance": (
                model.get_feature_importance()
            ),
        }
    )

    return (
        metrics,
        prediction_frame,
        importance_frame,
    )


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    frame = pd.read_parquet(
        DATASET_PATH
    )

    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="coerce",
    )

    frame = (
        frame
        .dropna(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    feature_groups = (
        build_feature_groups(
            frame
        )
    )

    tasks = build_tasks(
        frame
    )

    print(
        "SOURCE_ROWS",
        len(frame),
    )

    for task_name, spec in tasks.items():
        task_frame = spec["frame"]

        print()
        print(
            "TASK",
            task_name,
        )

        print(
            "ROWS",
            len(task_frame),
        )

        print(
            "DISTRIBUTION"
        )

        print(
            task_frame[
                "target"
            ]
            .value_counts()
            .to_string()
        )

    all_results = []
    all_predictions = []
    all_importance = []

    for task_name, spec in tasks.items():
        task_frame = spec[
            "frame"
        ]

        positive_class = spec[
            "positive_class"
        ]

        for group_name, features in (
            feature_groups.items()
        ):
            print()
            print(
                "RUN",
                task_name,
                group_name,
            )

            for fold_id, (
                train_fraction,
                valid_fraction,
            ) in enumerate(
                FOLD_SPECS,
                start=1,
            ):
                (
                    metrics,
                    predictions,
                    importance,
                ) = run_fold(
                    task_name,
                    task_frame,
                    positive_class,
                    group_name,
                    features,
                    fold_id,
                    train_fraction,
                    valid_fraction,
                )

                all_results.append(
                    metrics
                )

                all_predictions.append(
                    predictions
                )

                all_importance.append(
                    importance
                )

                print(
                    "FOLD",
                    fold_id,
                    "ACC",
                    round(
                        metrics[
                            "accuracy"
                        ],
                        4,
                    ),
                    "BASE",
                    round(
                        metrics[
                            "baseline_accuracy"
                        ],
                        4,
                    ),
                    "BAL_ACC",
                    round(
                        metrics[
                            "balanced_accuracy"
                        ],
                        4,
                    ),
                    "AUC",
                    None
                    if metrics[
                        "roc_auc"
                    ] is None
                    else round(
                        metrics[
                            "roc_auc"
                        ],
                        4,
                    ),
                    "PREC",
                    round(
                        metrics[
                            "precision"
                        ],
                        4,
                    ),
                )

                if task_name == "DIRECTION":
                    print(
                        "CONF",
                        "55",
                        round(
                            metrics[
                                "coverage_55"
                            ],
                            4,
                        ),
                        metrics[
                            "accuracy_55"
                        ],
                        "60",
                        round(
                            metrics[
                                "coverage_60"
                            ],
                            4,
                        ),
                        metrics[
                            "accuracy_60"
                        ],
                        "65",
                        round(
                            metrics[
                                "coverage_65"
                            ],
                            4,
                        ),
                        metrics[
                            "accuracy_65"
                        ],
                        "70",
                        round(
                            metrics[
                                "coverage_70"
                            ],
                            4,
                        ),
                        metrics[
                            "accuracy_70"
                        ],
                    )

    results_df = pd.DataFrame(
        all_results
    )

    summary = (
        results_df
        .groupby(
            [
                "task",
                "group",
            ],
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
            mean_f1=(
                "f1",
                "mean",
            ),
            mean_precision=(
                "precision",
                "mean",
            ),
            mean_recall=(
                "recall",
                "mean",
            ),
            mean_roc_auc=(
                "roc_auc",
                "mean",
            ),
            mean_average_precision=(
                "average_precision",
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
        .groupby(
            [
                "task",
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
                "task",
                "group",
                "importance",
            ],
            ascending=[
                True,
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
            "shadow_market_outcome_hurdle_v3"
        ),
        "source_target": TARGET_SOURCE,
        "purge_bars": PURGE_BARS,
        "fold_specs": FOLD_SPECS,
        "confidence_thresholds": (
            CONFIDENCE_THRESHOLDS
        ),
        "feature_groups": feature_groups,
        "task_rows": {
            name: int(
                len(spec["frame"])
            )
            for name, spec
            in tasks.items()
        },
        "fold_results": all_results,
        "summary": summary.to_dict(
            orient="records"
        ),
        "safety": {
            "stationary_features_only": True,
            "absolute_price_features_used": False,
            "calendar_features_used": False,
            "audit_context_used": False,
            "audit_auction_used": False,
            "audit_state_used": False,
            "ambiguous_rows_excluded": True,
            "random_split_used": False,
            "time_based_purge_used": True,
            "optuna_used": False,
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
    print("DIRECTION_SELECTIVE")

    direction = results_df[
        results_df["task"]
        == "DIRECTION"
    ]

    selective_columns = [
        "group",
        "fold",
        "coverage_55",
        "accuracy_55",
        "coverage_60",
        "accuracy_60",
        "coverage_65",
        "accuracy_65",
        "coverage_70",
        "accuracy_70",
    ]

    print(
        direction[
            selective_columns
        ].to_string(
            index=False
        )
    )

    print()
    print("TOP_FEATURES")

    for task_name in [
        "TOUCH",
        "DIRECTION",
    ]:
        for group_name in feature_groups:
            print()
            print(
                task_name,
                group_name,
            )

            print(
                mean_importance[
                    (
                        mean_importance[
                            "task"
                        ]
                        == task_name
                    )
                    & (
                        mean_importance[
                            "group"
                        ]
                        == group_name
                    )
                ]
                .head(12)[
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
