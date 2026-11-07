from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

STRUCTURE_PATH = ROOT / "data/cognition/candle_structure_memory.parquet"
LOCALIZATION_PATH = ROOT / "data/cognition/volume_localization_memory.parquet"
RESPONSE_PATH = ROOT / "data/cognition/volume_response_state.parquet"
AUCTION_PATH = ROOT / "data/cognition/auction_episode_memory.parquet"
STATE_PATH = ROOT / "data/cognition/cognitive_market_state_memory.parquet"
CONTEXT_PATH = ROOT / "data/cognition/final_market_context_memory.parquet"

OUTPUT_DIR = ROOT / "data/research"
OUTPUT_PATH = OUTPUT_DIR / "shadow_market_outcome_dataset_v1.parquet"
REPORT_PATH = OUTPUT_DIR / "shadow_market_outcome_dataset_v1_report.json"

HORIZONS = [1, 2, 4, 8, 16]
LAGS = [1, 2, 4, 8]


def load_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    if "timestamp" in frame.columns:
        frame = frame.copy()
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"],
            utc=True,
            errors="coerce",
        )
        frame = (
            frame.dropna(subset=["timestamp"])
            .sort_values("timestamp")
        )
    return frame


def prefix_columns(
    frame: pd.DataFrame,
    prefix: str,
    key: str = "timestamp",
) -> pd.DataFrame:
    rename = {
        col: f"{prefix}{col}"
        for col in frame.columns
        if col != key
    }
    return frame.rename(columns=rename)


def prepare_volume_response(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame

    work = frame.copy()

    evaluated = pd.to_datetime(
        work.get("evaluated_at", work["timestamp"]),
        utc=True,
        errors="coerce",
    )

    explicit_source = pd.to_datetime(
        work.get("source_candle_timestamp"),
        utc=True,
        errors="coerce",
    )

    legacy_source = pd.to_datetime(
        work["timestamp"],
        utc=True,
        errors="coerce",
    ).dt.floor("15min")

    work["join_timestamp"] = explicit_source.fillna(legacy_source)

    work["vr_join_mode"] = np.where(
        explicit_source.notna(),
        "EXPLICIT_SOURCE_CANDLE",
        "LEGACY_TIMESTAMP_FLOOR",
    )

    source_tf = (
        work["source_timeframe"].fillna("").astype(str).str.upper()
        if "source_timeframe" in work.columns
        else pd.Series("", index=work.index)
    )

    work = work[
        source_tf.isin(["", "M15"])
    ].copy()

    if "source_candle_close" in work.columns:
        source_close = pd.to_datetime(
            work["source_candle_close"],
            utc=True,
            errors="coerce",
        )
    else:
        source_close = pd.Series(pd.NaT, index=work.index)

    delay_seconds = (
        evaluated - source_close
    ).dt.total_seconds()

    work["vr_delay_seconds"] = delay_seconds

    work["vr_temporal_order_valid"] = (
        explicit_source.notna()
        & source_close.notna()
        & evaluated.notna()
        & delay_seconds.ge(0)
    )

    work["vr_fresh_300s"] = (
        work["vr_temporal_order_valid"]
        & delay_seconds.le(300)
    )

    work["vr_causal_certified"] = work["vr_fresh_300s"]

    work["_evaluated"] = evaluated

    work = (
        work.dropna(subset=["join_timestamp"])
        .sort_values(["join_timestamp", "_evaluated"])
        .drop_duplicates(subset=["join_timestamp"], keep="last")
    )

    keep = [
        "join_timestamp",
        "volume_event",
        "continuation_quality",
        "unfinished_auction",
        "unfinished_reason",
        "localized_behavior",
        "delta_efficiency",
        "estimated_local_volume",
        "effort_score",
        "result_score",
        "effort_result_ratio",
        "normalized_result",
        "effort_result_state",
        "volume_class",
        "climax_state",
        "participation_state",
        "relative_volume",
        "relative_spread",
        "volume_concentration",
        "localization_join_status",
        "localization_fresh",
        "source_timeframe",
        "vr_join_mode",
        "vr_delay_seconds",
        "vr_temporal_order_valid",
        "vr_fresh_300s",
        "vr_causal_certified",
    ]

    keep = [col for col in keep if col in work.columns]

    work = work[keep].copy()
    work = work.rename(columns={"join_timestamp": "timestamp"})

    return prefix_columns(work, "vr_")


def add_causal_aggregates(
    dataset: pd.DataFrame,
    structure: pd.DataFrame,
) -> pd.DataFrame:
    out = dataset.copy()
    source = structure.reset_index(drop=True).copy()

    windows = {
        "m30": 2,
        "h1": 4,
        "h4": 16,
    }

    for name, window in windows.items():
        out[f"mtf_{name}_volume"] = (
            source["volume"].rolling(window, min_periods=window).sum()
        )

        if "buy_volume" in source.columns:
            out[f"mtf_{name}_buy_volume"] = (
                source["buy_volume"].rolling(window, min_periods=window).sum()
            )

        if "sell_volume" in source.columns:
            out[f"mtf_{name}_sell_volume"] = (
                source["sell_volume"].rolling(window, min_periods=window).sum()
            )

        if "delta" in source.columns:
            out[f"mtf_{name}_delta"] = (
                source["delta"].rolling(window, min_periods=window).sum()
            )

        rolling_high = source["high"].rolling(
            window,
            min_periods=window,
        ).max()

        rolling_low = source["low"].rolling(
            window,
            min_periods=window,
        ).min()

        out[f"mtf_{name}_range"] = rolling_high - rolling_low

        first_open = source["open"].shift(window - 1)

        out[f"mtf_{name}_return_bps"] = (
            (source["close"] / first_open) - 1.0
        ) * 10000.0

    for lag in LAGS:
        for col in [
            "volume",
            "delta",
            "spread",
            "close_position",
            "volume_zscore",
            "spread_zscore",
        ]:
            if col in source.columns:
                out[f"lag_{lag}_{col}"] = source[col].shift(lag)

    for lag in [1, 2, 4, 8, 16]:
        out[f"past_return_{lag}_bps"] = (
            (source["close"] / source["close"].shift(lag)) - 1.0
        ) * 10000.0

    return out


def add_price_outcome_labels(
    dataset: pd.DataFrame,
    structure: pd.DataFrame,
) -> pd.DataFrame:
    out = dataset.copy()
    source = structure.reset_index(drop=True)

    close = source["close"]

    for horizon in HORIZONS:
        out[f"target_return_{horizon}_bps"] = (
            (close.shift(-horizon) / close) - 1.0
        ) * 10000.0

        future_highs = pd.concat(
            [source["high"].shift(-step) for step in range(1, horizon + 1)],
            axis=1,
        )

        future_lows = pd.concat(
            [source["low"].shift(-step) for step in range(1, horizon + 1)],
            axis=1,
        )

        max_high = future_highs.max(axis=1)
        min_low = future_lows.min(axis=1)

        out[f"target_mfe_{horizon}_bps"] = (
            (max_high / close) - 1.0
        ) * 10000.0

        out[f"target_mae_{horizon}_bps"] = (
            (min_low / close) - 1.0
        ) * 10000.0

        valid = close.shift(-horizon).notna()

        out.loc[
            ~valid,
            [
                f"target_return_{horizon}_bps",
                f"target_mfe_{horizon}_bps",
                f"target_mae_{horizon}_bps",
            ],
        ] = np.nan

    return out


def add_context_outcome_labels(dataset: pd.DataFrame) -> pd.DataFrame:
    out = dataset.copy()

    col = "audit_context_market_context"
    if col not in out.columns:
        return out

    context = out[col].fillna("UNKNOWN").astype(str)

    for horizon in HORIZONS:
        target = context.shift(-horizon)
        out[f"target_context_at_{horizon}"] = target

        future = pd.concat(
            [context.shift(-step) for step in range(1, horizon + 1)],
            axis=1,
        )

        valid = target.notna()

        changed = future.ne(context, axis=0).any(axis=1)
        changed = changed.where(valid)

        out[f"target_context_changed_within_{horizon}"] = changed

    group_id = context.ne(context.shift()).cumsum()

    bars_to_change = pd.Series(
        np.nan,
        index=out.index,
        dtype=float,
    )

    next_context = pd.Series(
        pd.NA,
        index=out.index,
        dtype="object",
    )

    groups = list(out.groupby(group_id, sort=False).groups.values())

    for positions in groups:
        idx = list(positions)
        last_index = idx[-1]

        if last_index + 1 >= len(out):
            continue

        next_value = context.iloc[last_index + 1]

        for position in idx:
            bars_to_change.iloc[position] = last_index - position + 1
            next_context.iloc[position] = next_value

    out["target_bars_to_context_change"] = bars_to_change
    out["target_next_market_context"] = next_context

    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    structure = load_frame(STRUCTURE_PATH)

    if structure.empty:
        raise RuntimeError("Missing candle structure memory")

    structure = (
        structure.drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    dataset = prefix_columns(structure, "cs_")
    dataset = dataset.rename(columns={"cs_timestamp": "timestamp"})

    localization = load_frame(LOCALIZATION_PATH)
    if not localization.empty:
        localization = (
            localization.drop_duplicates(
                subset=["timestamp"],
                keep="last",
            )
            .sort_values("timestamp")
        )
        localization = prefix_columns(localization, "loc_")
        dataset = dataset.merge(
            localization,
            on="timestamp",
            how="left",
        )

    response = load_frame(RESPONSE_PATH)
    if not response.empty:
        response = prepare_volume_response(response)
        dataset = dataset.merge(
            response,
            on="timestamp",
            how="left",
        )

    auction = load_frame(AUCTION_PATH)
    if not auction.empty:
        auction = (
            auction.drop_duplicates(
                subset=["timestamp"],
                keep="last",
            )
            .sort_values("timestamp")
        )
        auction = prefix_columns(auction, "audit_auction_")
        dataset = dataset.merge(
            auction,
            on="timestamp",
            how="left",
        )

    state = load_frame(STATE_PATH)
    if not state.empty:
        state = (
            state.drop_duplicates(
                subset=["timestamp"],
                keep="last",
            )
            .sort_values("timestamp")
        )
        state = prefix_columns(state, "audit_state_")
        dataset = dataset.merge(
            state,
            on="timestamp",
            how="left",
        )

    context = load_frame(CONTEXT_PATH)
    if not context.empty:
        context = (
            context.drop_duplicates(
                subset=["timestamp"],
                keep="last",
            )
            .sort_values("timestamp")
        )
        context = prefix_columns(context, "audit_context_")
        dataset = dataset.merge(
            context,
            on="timestamp",
            how="left",
        )

    dataset = add_causal_aggregates(
        dataset,
        structure,
    )

    dataset = add_price_outcome_labels(
        dataset,
        structure,
    )

    dataset = add_context_outcome_labels(dataset)

    dataset["hour_utc"] = dataset["timestamp"].dt.hour
    dataset["day_of_week_utc"] = dataset["timestamp"].dt.dayofweek

    dataset["session_utc"] = pd.cut(
        dataset["hour_utc"],
        bins=[-1, 7, 15, 23],
        labels=["ASIA", "EUROPE", "AMERICA"],
    ).astype(str)

    dataset["training_ready_h16"] = (
        dataset["target_return_16_bps"].notna()
        & dataset["target_mfe_16_bps"].notna()
        & dataset["target_mae_16_bps"].notna()
    )

    dataset.to_parquet(
        OUTPUT_PATH,
        index=False,
    )

    report = {
        "dataset_version": "shadow_market_outcome_dataset_v1",
        "rows": int(len(dataset)),
        "columns": int(len(dataset.columns)),
        "time_min": str(dataset["timestamp"].min()),
        "time_max": str(dataset["timestamp"].max()),
        "training_ready_h16": int(dataset["training_ready_h16"].sum()),
        "localization_rows_joined": int(
            dataset["loc_estimated_local_volume"].notna().sum()
        ) if "loc_estimated_local_volume" in dataset.columns else 0,
        "volume_response_rows_joined": int(
            dataset["vr_volume_event"].notna().sum()
        ) if "vr_volume_event" in dataset.columns else 0,
        "volume_response_causal_certified": int(
            dataset["vr_vr_causal_certified"].fillna(False).sum()
        ) if "vr_vr_causal_certified" in dataset.columns else 0,
        "context_rows_joined": int(
            dataset["audit_context_market_context"].notna().sum()
        ) if "audit_context_market_context" in dataset.columns else 0,
        "notes": [
            "M15 candle_structure_memory is the master clock.",
            "MTF features are causal rolling aggregates of completed M15 bars.",
            "Price targets use future bars and must never be used as features.",
            "audit_auction, audit_state, and audit_context columns are retained for research but are not automatically approved as causal model features.",
            "Legacy volume-response rows are retained and explicitly marked LEGACY_TIMESTAMP_FLOOR.",
            "trading_state_memory is excluded from V1 because its history ends before the main dataset.",
        ],
    }

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )
    )

    print("OUTPUT", OUTPUT_PATH)
    print("REPORT", REPORT_PATH)
    print("ROWS", len(dataset))
    print("COLUMNS", len(dataset.columns))
    print("TIME_MIN", dataset["timestamp"].min())
    print("TIME_MAX", dataset["timestamp"].max())
    print("TRAINING_READY_H16", int(dataset["training_ready_h16"].sum()))

    if "loc_estimated_local_volume" in dataset.columns:
        print(
            "LOCALIZATION_JOINED",
            int(dataset["loc_estimated_local_volume"].notna().sum()),
        )

    if "vr_volume_event" in dataset.columns:
        print(
            "VOLUME_RESPONSE_JOINED",
            int(dataset["vr_volume_event"].notna().sum()),
        )

    if "vr_vr_causal_certified" in dataset.columns:
        print(
            "VR_CAUSAL_CERTIFIED",
            int(dataset["vr_vr_causal_certified"].fillna(False).sum()),
        )

    if "audit_context_market_context" in dataset.columns:
        print(
            "CONTEXT_JOINED",
            int(dataset["audit_context_market_context"].notna().sum()),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
